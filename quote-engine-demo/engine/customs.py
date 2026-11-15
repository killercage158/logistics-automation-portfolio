"""Customs lookup: which HS code, which duty and VAT, which licence or inspection,
and what the clearance costs, for ONE product.

The customs team's AI proposes; code decides. The AI reads the tariff table and the
legal documents and proposes an HS code with a quote from the law. Then plain code
checks the proposal against the real tariff table and the real document text.

Rules in this file (written in skills/customs-lookup.md):
  CU-01  the HS code must exist in the tariff table
  CU-02  the legal text the AI quotes must appear word for word in the cited document
  CU-03  duty and VAT rates and the licence / inspection flags come from the table, never from the AI
  CU-04  duty = rate x customs value;  VAT = VAT rate x (customs value + duty)
  CU-05  licence and inspection flags add their processing fees and procedure notes
  CU-06  doubt becomes a visible warning, never a silent choice

WHY the AI may not give rates: a rate that the AI "remembers" can be out of date or
invented. A rate copied by code from the tariff row cannot be.

All codes, rates, documents and fees in this demo are fictional.

In production, the same checks guard the customs team's lookups: every HS code must
exist in the tariff, and every legal quote must be found in the cited document.
"""
import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from engine.ai_reader import ReplyError, ask_for_json
from engine.money import vnd_to_usd
from engine.rulebook import hit, rule

OUTPUT_SPEC = """Return ONLY a JSON array of candidates, best first. Each item has these keys:
  hs_code      (8-digit HS code as a string)
  description  (short name of the goods under that code)
  legal_basis  ({"document": file name of the legal document, "quote": ONE sentence copied word for word from it})
  doubt        (empty string if you are sure; otherwise say what makes you unsure)
No text before or after the JSON. Do NOT state duty, VAT or licence information."""


@dataclass
class CustomsResult:
    product: str
    direction: str                   # "export" or "import"
    value_usd: float
    hs_code: str = ""
    description: str = ""
    duty_pct: float = 0.0
    vat_pct: float = 0.0
    duty_usd: float = 0.0
    vat_usd: float = 0.0
    fees: list = field(default_factory=list)         # list[(name, vnd)]
    procedures: list = field(default_factory=list)   # staff-facing notes (internal)
    licence: bool = False            # from the tariff table (CU-03)
    inspection: str = ""             # "physical", "documents" or "none" (from the tariff table)
    basis: str = ""                  # verified legal quote, or ""
    source: str = "AI proposal, verified"            # or "entered by staff"
    candidates: list = field(default_factory=list)   # list[(candidate dict, accepted, reason, rule id)]
    warnings: list = field(default_factory=list)
    rules: list = field(default_factory=list)

    @property
    def fees_usd(self):
        return sum(vnd_to_usd(v) for _, v in self.fees)

    @property
    def ok(self):
        return bool(self.hs_code)


def _csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def normalise_text(text):
    """Lower-case, remove accents, collapse every run of non-letters/digits to one space."""
    text = unicodedata.normalize("NFKD", str(text).lower().replace("đ", "d"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


@rule("CU-01", "The HS code must exist in the tariff table")
def find_tariff_row(hs_code, tariff_rows):
    """Return the tariff row for an 8-digit code, or None."""
    code = re.sub(r"\D", "", str(hs_code))
    return next((r for r in tariff_rows if r["hs_code"] == code), None) if len(code) == 8 else None


@rule("CU-02", "The legal text the AI quotes must appear word for word in the cited document")
def quote_is_in_document(document, quote, legal_dir):
    """True if `quote` appears in the document (case, accents and spacing are ignored)."""
    path = Path(legal_dir) / Path(str(document)).name       # never follow a path the AI wrote
    if not path.is_file() or len(normalise_text(quote)) < 20:
        return False
    return normalise_text(quote) in normalise_text(path.read_text(encoding="utf-8"))


@rule("CU-03", "Rates and flags come from the tariff table by HS code, never from the AI")
def rates_from_tariff(row, direction):
    """Duty %, VAT % and the licence / inspection flags for this direction, copied from the row."""
    return {"duty_pct": float(row[f"{direction}_duty_pct"]), "vat_pct": float(row[f"{direction}_vat_pct"]),
            "licence": row["licence_required"] == "yes", "inspection": row["inspection"]}


@rule("CU-04", "Duty = rate x customs value; VAT = VAT rate x (customs value + duty)")
def duty_and_vat(value_usd, duty_pct, vat_pct):
    """Return (duty, vat) in USD. VAT is charged on the value PLUS the duty."""
    duty = value_usd * duty_pct / 100
    return round(duty, 2), round((value_usd + duty) * vat_pct / 100, 2)


@rule("CU-05", "Licence and inspection flags add processing fees and procedure notes")
def procedure_fees(flags, fee_rows):
    """Return (fees [(name, vnd)], notes). The base broker fee always applies."""
    wanted = ["declaration"]
    if flags["licence"]:
        wanted.append("licence")
    if flags["inspection"] in ("physical", "documents"):
        wanted.append(f"inspection_{flags['inspection']}")
    fees = [(r["item"], float(r["amount_vnd"])) for r in fee_rows if r["applies_when"] in wanted]
    notes = []
    if flags["licence"]:
        notes.append("an export/import licence must be obtained before clearance")
    if flags["inspection"] == "physical":
        notes.append("the goods will be physically inspected at the port")
    elif flags["inspection"] == "documents":
        notes.append("the documents will be inspected")
    return fees, notes


@rule("CU-06", "Doubt becomes a visible warning, never a silent choice")
def doubt_warnings(accepted, alternatives, basis_ok, ai_available):
    """Collect the reasons a person must look at this answer."""
    warnings = []
    if not ai_available:
        warnings.append("no AI answer: enter the HS code by hand (--hs) or ask the customs team")
    if accepted is None:
        return warnings
    if accepted["doubt"]:
        warnings.append(f"AI is unsure: {accepted['doubt']}")
    if alternatives:
        warnings.append("other plausible HS codes: " + ", ".join(alternatives) + " - confirm the right one")
    if not basis_ok:
        warnings.append("legal basis could not be verified in the document - not shown as a citation")
    return warnings


def _evaluate(row, direction, value_usd, fee_rows, result):
    """Fill a CustomsResult from a tariff row (CU-03, CU-04, CU-05)."""
    rates = rates_from_tariff(row, direction)
    result.hs_code, result.description = row["hs_code"], row["description"]
    result.duty_pct, result.vat_pct = rates["duty_pct"], rates["vat_pct"]
    result.duty_usd, result.vat_usd = duty_and_vat(value_usd, rates["duty_pct"], rates["vat_pct"])
    result.licence, result.inspection = rates["licence"], rates["inspection"]
    result.fees, result.procedures = procedure_fees(rates, fee_rows)


def run_customs(product, direction, value_usd, data_dir, llm, log, trace=None, manual_hs=None, system=True):
    """Full customs step for one product. `manual_hs` lets staff type the HS code themselves.

    system=False means the team declined the work item: without a manual HS code there is no answer.
    """
    folder = Path(data_dir) / "customs"
    tariff, fees = _csv(folder / "tariff.csv"), _csv(folder / "customs_fees.csv")
    result = CustomsResult(product, direction, value_usd)

    if manual_hs:                                         # manual path: no AI, same checks on the code
        row = find_tariff_row(manual_hs, tariff)
        hit(trace, "CU-01", "customs", f"HS {manual_hs} " + ("found" if row else "NOT in the tariff"))
        if row is None:
            result.warnings.append(f"HS code {manual_hs} is not in the tariff table")
            return result
        result.source = "entered by staff"
        _evaluate(row, direction, value_usd, fees, result)
        for rid in ("CU-03", "CU-04", "CU-05"):
            hit(trace, rid, "customs", "applied to the HS code typed by staff")
        log.add(f"  HS {result.hs_code} entered by staff; rates copied from the tariff table")
        return result

    if not system:
        result.warnings.append("the customs team declined this work item: enter the HS code by hand (--hs)")
        hit(trace, "CU-06", "customs", result.warnings[0])
        return result

    docs = sorted((folder / "legal").glob("*.txt"))
    body = (f"Product: {product}\n\n# Tariff table\n" + (folder / "tariff.csv").read_text(encoding="utf-8")
            + "\n# Legal documents\n" + "\n".join(f"## {d.name}\n{d.read_text(encoding='utf-8')}" for d in docs))
    ai_available = True
    try:
        candidates = ask_for_json(llm, "customs", "customs-lookup", OUTPUT_SPEC,
                                  f"Product: {product}", body, log, "customs")
    except (ReplyError, FileNotFoundError) as e:
        candidates, ai_available = [], False
        log.add(f"  no usable AI answer ({e})")

    accepted, row, alternatives = None, None, []
    for cand in candidates:                               # CU-01 on every candidate
        found = find_tariff_row(cand.get("hs_code", ""), tariff)
        cand.setdefault("doubt", "")
        if found is None:
            result.candidates.append((cand, False, f"HS code {cand.get('hs_code')} is not in the tariff table", "CU-01"))
            hit(trace, "CU-01", "customs", f"rejected invented code {cand.get('hs_code')}")
            log.add(f"  REJECTED HS {cand.get('hs_code')}: not in the tariff table")
        elif accepted is None:
            accepted, row = cand, found
            result.candidates.append((cand, True, "exists in the tariff table (chosen: best first)", "CU-01"))
            hit(trace, "CU-01", "customs", f"HS {found['hs_code']} found in the tariff")
        else:
            alternatives.append(found["hs_code"])
            result.candidates.append((cand, True, "exists in the tariff table (kept as an alternative)", "CU-01"))

    basis_ok = False
    if accepted is not None:
        basis = accepted.get("legal_basis") or {}
        basis_ok = quote_is_in_document(basis.get("document", ""), basis.get("quote", ""), folder / "legal")
        hit(trace, "CU-02", "customs", "quote found in " + basis.get("document", "?") if basis_ok
            else "quote NOT found in the cited document")
        if basis_ok:
            result.basis = f"{basis['document']}: \"{basis['quote']}\""
        _evaluate(row, direction, value_usd, fees, result)
        for rid in ("CU-03", "CU-04", "CU-05"):
            hit(trace, rid, "customs", f"applied to HS {row['hs_code']}")
    result.warnings = doubt_warnings(accepted, alternatives, basis_ok, ai_available)
    for w in result.warnings:
        hit(trace, "CU-06", "customs", w)
    return result
