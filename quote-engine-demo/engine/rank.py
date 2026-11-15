"""Step 6: rank the options and explain the recommendation.

Ranking is deliberately simple and explainable: lowest ALL-IN total first
(freight + local charges). Ties go to the more trustworthy source, then to the
carrier name so the order is always the same.

The recommendation always comes with REASONS in plain words. Staff can check a
reason; they cannot check "the AI liked it".

In production, the ranking is also explainable (no black box) and feeds the
comparison PDF. Sales
still makes the final choice and sets the profit. Simplified here: one number
(total) decides; no schedule or transit-time scoring.
"""
from dataclasses import dataclass

from engine.models import SOURCE_ORDER


@dataclass
class Recommendation:
    option: object
    reasons: list


def rank_options(options):
    return sorted(options, key=lambda o: (round(o.total, 2), SOURCE_ORDER.index(o.price.source), o.carrier))


def recommend(ranked):
    """Return a Recommendation for the cheapest option, or None when there are no options."""
    if not ranked:
        return None
    best = ranked[0]
    reasons = [f"Lowest all-in total: USD {best.total:,.0f} "
               f"(freight {best.price.price_usd:,.0f} + local charges {best.local_total:,.0f})."]
    if len(ranked) > 1:
        gap = ranked[1].total - best.total
        reasons.append(f"USD {gap:,.0f} cheaper than the next option ({ranked[1].carrier}).")
    reasons.append({"contract": "Contract rate: negotiated, no portal check needed.",
                    "manual": "Typed in by staff.",
                    "portal": "Price was read live from the carrier's portal today.",
                    "price file": "Price comes from a price file: confirm with the carrier."}[best.price.source])
    if best.price.valid_until:
        reasons.append(f"Valid until {best.price.valid_until}.")
    if best.freetime:
        reasons.append(f"Free time: {best.freetime['pol_days']} days at POL, "
                       f"{best.freetime['pod_days']} days at POD.")
    for flag in best.flags:
        reasons.append(f"Check: {flag}.")
    return Recommendation(best, reasons)
