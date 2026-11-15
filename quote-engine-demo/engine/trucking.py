"""Trucking: the road leg from the customer's pickup place to the loading port.

The trucking team keeps its hauliers' price lists as messy spreadsheets (some are
route lists, some are matrices, some are pasted email text). Like the booking
team, it uses an AI reader that follows its own skill file, and code verifies
every cell the AI cites.

Rules in this file (written in skills/trucking-rates.md):
  TR-01  the AI reader follows the trucking skill file and cites price AND diesel cell
  TR-03  fuel-indexed price: a share of the price moves with the diesel price
  TR-04  expired haulier quotes are dropped and listed
  TR-05  the truck type follows the container type
  TR-06  keep alternatives: every verified haulier stays in the list
  TR-07  identical prices in two hauliers' files are flagged as doubtful
(TR-02, the citation check, is in verify.py.)

WHY fuel-indexed: a haulier quotes a price when diesel costs one amount; by the
time we quote the customer, diesel may cost more. Part of the trucking price is
fixed (driver, truck, margin) and part follows fuel. The made-up split in this
demo is 70% fixed and 30% fuel. Only the freight price is adjusted, never fees.

WHY keep alternatives: Sales Support, not the trucking team, decides which haulier
the customer gets. The team's job ends when it has produced the options.

In production, the same structure applies with the trucking team's own price folder,
its own fuel formula and its own diesel price source.
"""
import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from engine.ai_reader import ReplyError, ask_for_json
from engine.price_files import grid_text
from engine.request import key, normalise_place
from engine.rulebook import hit, rule
from engine.verify import verify_haulier_row

FIXED_SHARE, FUEL_SHARE = 0.70, 0.30             # made-up split of a trucking price

OUTPUT_SPEC = """Return ONLY a JSON array. Each item has these keys:
  haulier         (string, the haulier the file belongs to)
  pickup          (place the truck starts from)
  port            (the port or place the truck goes to)
  truck           ("20ft" or "40ft" trailer)
  price_vnd       (number: price per trip in VND)
  diesel_base_vnd (number: the diesel price per litre the quote is based on)
  valid_until     (YYYY-MM-DD, or null)
  source          ({"sheet": sheet name, "cell": the exact cell where the PRICE sits})
  diesel_source   ({"sheet": sheet name, "cell": the exact cell where the DIESEL price sits})
No text before or after the JSON."""


@dataclass
class HaulierRow:
    """One haulier price as the AI read it, before any checking."""
    haulier: str
    pickup: str
    port: str
    truck: str
    price_vnd: float
    diesel_base_vnd: float
    valid_until: object
    file: str
    sheet: str
    cell: str
    diesel_sheet: str
    diesel_cell: str

    @property
    def citation(self):
        return f"{self.file} / {self.sheet} / {self.cell}"


@dataclass
class TruckOption:
    haulier: str
    quoted_vnd: float
    factor: float                    # fuel adjustment factor (1.0 = no change)
    adjusted_vnd: float
    qty: int
    valid_until: object
    source: str                      # "price file" or "manual"
    detail: str
    flags: list = field(default_factory=list)
    rules: list = field(default_factory=list)

    @property
    def total_vnd(self):
        return self.adjusted_vnd * self.qty


@dataclass
class TruckingResult:
    pickup: str
    port: str
    truck: str
    options: list                    # ranked list[TruckOption]
    verified: list                   # list[(HaulierRow, ok, reason)]
    problems: list                   # list[(text, reason)]
    dropped: list                    # list[(text, reason, rule id)]
    diesel_today: object
    files: list = field(default_factory=list)


@rule("TR-05", "The truck type follows the container type")
def truck_for_container(container):
    """20GP goes on a 20ft trailer; 40GP and 40HC go on a 40ft trailer."""
    return "20ft" if container == "20GP" else "40ft"


@rule("TR-03", "Fuel-indexed price: 70% fixed, 30% follows the diesel price (made-up split)")
def fuel_factor(diesel_today, diesel_base):
    """price_today = quoted x (fixed share + fuel share x diesel_today / diesel_base)."""
    if not diesel_today or not diesel_base:
        return 1.0
    return FIXED_SHARE + FUEL_SHARE * diesel_today / diesel_base


def current_diesel(rows, as_of):
    """Latest diesel price (VND per litre) on or before the pricing date, or None."""
    known = [(date.fromisoformat(r["date"]), float(r["price_vnd"])) for r in rows
             if date.fromisoformat(r["date"]) <= as_of]
    return max(known)[1] if known else None


def to_haulier_row(raw, file_name):
    """Turn one raw JSON item into a HaulierRow. Raises ValueError when unreadable."""
    try:
        valid = raw.get("valid_until")
        truck = str(raw["truck"]).lower().replace(" ", "").replace("'", "")
        return HaulierRow(
            haulier=str(raw["haulier"]).strip(), pickup=normalise_place(raw["pickup"]),
            port=normalise_place(raw["port"]), truck=truck, price_vnd=float(raw["price_vnd"]),
            diesel_base_vnd=float(raw["diesel_base_vnd"]),
            valid_until=date.fromisoformat(valid) if valid else None,
            file=file_name, sheet=str(raw["source"]["sheet"]), cell=str(raw["source"]["cell"]).upper(),
            diesel_sheet=str(raw["diesel_source"]["sheet"]),
            diesel_cell=str(raw["diesel_source"]["cell"]).upper())
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"unreadable item ({type(e).__name__}: {e})")


@rule("TR-01", "The AI reads each haulier file following the trucking skill and cites its cells")
def read_haulier_file(llm, path, log):
    """Ask the AI about one haulier file. Returns (rows, problems)."""
    name = path.name
    try:
        raw_items = ask_for_json(llm, "trucking", "trucking-rates", OUTPUT_SPEC,
                                 f"File: {name}", grid_text(path), log, name)
    except ReplyError as e:
        return [], [(name, f"whole file unreadable after one re-ask: {e}")]
    rows, problems = [], []
    for raw in raw_items:
        try:
            rows.append(to_haulier_row(raw, name))
        except ValueError as e:
            problems.append((str(raw)[:80], str(e)))
    log.add(f"  {name}: AI returned {len(raw_items)} items, {len(rows)} readable")
    return rows, problems


@rule("TR-04", "Expired haulier quotes are dropped and listed")
def drop_expired(options, as_of, trace=None):
    kept, dropped = [], []
    for o in options:
        if o.valid_until is not None and o.valid_until < as_of:
            dropped.append((f"{o.haulier} VND {o.quoted_vnd:,.0f}", f"expired on {o.valid_until}", "TR-04"))
            hit(trace, "TR-04", o.haulier, f"quote expired on {o.valid_until}")
        else:
            kept.append(o)
    return kept, dropped


@rule("TR-07", "Identical prices in two hauliers' files are flagged as doubtful, not dropped")
def flag_duplicate_prices(options, trace=None):
    seen = {}
    for o in options:
        if o.source == "price file":
            seen.setdefault(o.quoted_vnd, []).append(o)
    for price, group in seen.items():
        if len({o.haulier for o in group}) > 1:
            for o in group:
                others = ", ".join(sorted({x.haulier for x in group} - {o.haulier}))
                o.flags.append(f"same quoted price as {others} - possible copied file, check it")
                hit(trace, "TR-07", o.haulier, f"identical price {price:,.0f} also in {others}")
    return options


@rule("TR-06", "Keep alternatives: every verified haulier stays in the list")
def rank_alternatives(options):
    """Sort by total (cheapest first). Nothing is removed: Sales Support decides."""
    return sorted(options, key=lambda o: (round(o.total_vnd), o.haulier))


def run_trucking(req, pickup, as_of, data_dir, llm, log, trace=None, manual_path=None, system=True):
    """Full trucking step: AI reads, code verifies, rules shape the options.

    system=False means the team did not do the system lookup (it declined the work item):
    only manual entries typed by staff are used.
    """
    data_dir = Path(data_dir)
    port, truck = req.pol, truck_for_container(req.container)
    pickup = normalise_place(pickup)
    hit(trace, "TR-05", "trucking", f"{req.container} -> {truck} trailer")
    log.add(f"  leg: {pickup} -> {port}, {truck} trailer, {req.qty} trip(s)")

    rows, problems, files = [], [], []
    for path in sorted((data_dir / "trucking").glob("*.xlsx")) if system else []:
        got, bad = read_haulier_file(llm, path, log)
        rows += got
        problems += bad
        files.append(f"{path.name}: {len(got)} readable items, {len(bad)} unreadable")
        hit(trace, "TR-01", path.stem, "read by the AI following the trucking skill")
    verified = [(r, *verify_haulier_row(r, data_dir / "trucking", trace)) for r in rows]
    n_ok = sum(1 for _, ok, _ in verified if ok)
    log.add(f"  verification: {n_ok} accepted, {len(verified) - n_ok + len(problems)} rejected")
    for r, ok, why in verified:
        if not ok:
            log.add(f"    REJECTED {r.haulier} {r.pickup}->{r.port} {r.truck} VND {r.price_vnd:,.0f} "
                    f"[{r.citation}]\n             why: {why}")
    for text, why in problems:
        log.add(f"    REJECTED {text}\n             why: {why}")

    diesel = current_diesel(_csv(data_dir / "diesel_price.csv"), as_of)
    options = []
    for r, ok, _ in verified:
        if ok and (r.pickup, r.port, r.truck) == (pickup, port, truck):
            f = fuel_factor(diesel, r.diesel_base_vnd)
            hit(trace, "TR-03", r.haulier, f"factor {f:.3f} (diesel {diesel:,.0f} vs base {r.diesel_base_vnd:,.0f})")
            options.append(TruckOption(r.haulier, r.price_vnd, f, round(r.price_vnd * f, -3), req.qty,
                                       r.valid_until, "price file", r.citation))
    if manual_path:
        for m in _csv(manual_path):
            if (normalise_place(m["pickup"]), normalise_place(m["port"]), m["truck"]) == (pickup, port, truck):
                options.append(TruckOption(m["haulier"], float(m["price_vnd"]), 1.0, float(m["price_vnd"]), req.qty,
                                           date.fromisoformat(m["valid_until"]) if m["valid_until"] else None,
                                           "manual", f"typed by staff: {m['note']}"))
                hit(trace, "SS-04", m["haulier"], "manual trucking price counts like any other")
    if diesel is None:
        log.add("  no diesel price for this date: prices are NOT fuel-adjusted")

    options, dropped = drop_expired(options, as_of, trace)
    for text, why, rid in dropped:
        log.add(f"  left out: {text} - {why}")
    flag_duplicate_prices(options, trace)
    options = rank_alternatives(options)
    for o in options:
        o.rules = trace.ids_for(o.haulier) if trace is not None else []
    for i, o in enumerate(options, 1):
        log.add(f"  {i}. {o.haulier:<17} {o.source:<10} quoted {o.quoted_vnd:>10,.0f} x {o.factor:.3f} "
                f"= {o.adjusted_vnd:>10,.0f} VND per trip")
    return TruckingResult(pickup, port, truck, options, verified, problems, dropped, diesel, files)


def _csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
