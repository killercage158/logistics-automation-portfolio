"""Plain data containers shared by the whole engine.

Keeping them in one file makes the rest of the code easy to read:
every other module just passes these objects along.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# Where a price can come from. The list is also the order of trust:
# a contract beats a manual entry, which beats a live portal price,
# which beats a price read from a spreadsheet.
SOURCE_ORDER = ["contract", "manual", "portal", "price file"]


@dataclass
class Price:
    """One freight price for one carrier on the requested lane."""
    carrier: str
    price_usd: float
    valid_until: Optional[date]
    source: str                      # one of SOURCE_ORDER
    detail: str                      # human-readable proof, e.g. "file / sheet / cell"
    cargo: Optional[str] = None      # "general", "charcoal" or None (= any)
    includes: tuple = ()             # fees the carrier says are already in the price (LC-04)


@dataclass
class PriceRow:
    """One price as the AI read it from a spreadsheet, before any checking."""
    carrier: str
    pol: str
    pod: str
    container: str
    cargo: Optional[str]
    price_usd: float
    valid_until: Optional[date]
    file: str
    sheet: str
    cell: str

    @property
    def citation(self):
        return f"{self.file} / {self.sheet} / {self.cell}"


@dataclass
class Charge:
    """One local charge: how much, per what, and which table it came from."""
    usd: float
    unit: str = "per_container"      # "per_container" or "per_bl" (per bill of lading)
    source: str = "general table"


@dataclass
class Option:
    """A price plus everything needed to compare it with the others."""
    price: Price
    local_charges: dict              # charge name -> Charge
    freetime: Optional[dict]         # {"pol_days", "pod_days", "guide", "notes"} or None
    flags: list = field(default_factory=list)
    rules: list = field(default_factory=list)       # rule IDs that shaped this option
    qty: int = 1                     # number of containers

    @property
    def carrier(self):
        return self.price.carrier

    @property
    def local_total(self):
        """Per-container charges are multiplied by the number of containers; per-BL charges are not."""
        return sum(c.usd * (self.qty if c.unit == "per_container" else 1)
                   for c in self.local_charges.values())

    @property
    def total(self):
        return self.price.price_usd * self.qty + self.local_total


@dataclass
class RunResult:
    """Everything the report needs to show about one run."""
    request: object
    as_of: date
    ranked: list                     # list[Option], cheapest first
    recommendation: object
    portal_outcomes: list
    contracts_used: dict
    contracts_ignored: list          # text lines
    ai_files: list                   # text lines, one per file
    verified: list                   # list[(PriceRow, ok, reason)]
    ai_problems: list                # list[(text, reason)]: items the AI returned that we could not read
    dropped: list                    # list[(Price, reason, rule id)]
    portal_minutes: float            # one try at every carrier (simulated)
    portal_total_minutes: float      # until the last retry finished (simulated)
    mode: str                        # "mock" or the live provider name
    trace: object = None             # RuleTrace: every rule hit of this run
