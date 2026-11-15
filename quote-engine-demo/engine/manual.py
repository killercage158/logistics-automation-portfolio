"""The manual-entry path: staff can always type a price by hand.

WHY it exists: a carrier site may be down, a lane may be missing from every file,
or a salesperson may have a price from a phone call. The customer cannot wait
for someone to fix code. A manual price goes through the SAME rules and the SAME
ranking as every other price, and is clearly labelled "manual" in the report.

Rule BK-07: a manual price is always allowed and counts like any other price.
It applies ONLY to the request it was typed for. It is never saved and reused for
later requests: if a price is needed long term, the team updates its price file.

In production, staff type a price or free text on a card or in the table, and an
AI reads text that does not follow the usual pattern.
Simplified here: a small CSV file passed with --manual.
"""
from datetime import date

from engine.models import Price
from engine.request import normalise_container, normalise_port
from engine.rules import load_csv
from engine.rulebook import hit, rule


@rule("BK-07", "Manual entry always works, joins the same ranking, applies to this request only")
def load_manual(path, req, trace=None):
    """Return manual Prices that match the request's lane and container."""
    prices = []
    for r in load_csv(path):
        lane = (normalise_port(r["pol"]), normalise_port(r["pod"]), normalise_container(r["container"]))
        if lane != (req.pol, req.pod, req.container):
            continue
        valid = date.fromisoformat(r["valid_until"]) if r["valid_until"] else None
        prices.append(Price(r["carrier"].strip(), float(r["price_usd"]), valid, "manual",
                            f"typed by staff: {r['note']}", req.cargo))
        hit(trace, "BK-07", r["carrier"].strip(), "manual price entered by staff")
    return prices
