"""Step 3: check carrier portals ONE AFTER ANOTHER, inside a shared time budget, with automatic retries.

THE FAKE PART
  Real carrier websites cannot be shipped in a public demo, so each "portal" here
  is a small fake with a deterministic script: it always behaves the same way for
  the same lane. That lets the tests prove the runner handles every situation:
  a normal price, a login problem, a site that is down, a portal that hangs,
  "no price".

THE REAL PART (this is what the demo teaches)
  - Carriers are checked one after another inside ONE run. Verified facts about
    the real system: the carriers share one browser profile that is guarded by a
    lock, carriers rate-limit repeated requests, and a per-run time budget bounds
    the total time. (Likely, not verified: this is also why they are not run in
    parallel.)
  - The budget belongs to the RUN, not to each carrier:
        budget = min(30, 2 + 8.5 x number of carriers in that run)   minutes
    If the budget runs out, the whole run is stopped. The carrier that was being
    checked and every carrier not reached yet are marked TEMPORARY (timeout).
  - Two kinds of outcome are treated differently:
        TEMPORARY  (site down, login problem, timeout) -> try again later
        PERMANENT  ("no price for this lane", "cargo not accepted") -> this IS the
                    answer. We never retry it.
  - A retry is a NEW run that contains only the carriers that failed temporarily,
    with its own budget worked out from how many carriers it contains. Retry 1
    starts 10 minutes after the previous run, retry 2 starts 25 minutes after
    that. A carrier that still fails after the second retry is reported as
    "gave up", never hidden.
  - We only ASK FOR A PRICE. The fake portals have no way to book anything, and a
    test checks that (rule: price check only, never booking).

In production: the run budget is min(30, 2 + 8.5 x n) minutes, the whole pricing
run is stopped when it is used up, and a new run is scheduled for only the
temporarily failed carriers after 10 and then 25 minutes. One script per carrier
portal does the actual price check, called one after another in a loop.
Timing seen in the production logs: 1 carrier about 1.5 minutes, all 6 about 9-14 minutes.
Simplified here: simulated minutes (no real waiting unless --slow), fake prices.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from engine.models import Price
from engine.rulebook import hit, rule

PORTAL_ORDER = ["Bluewave Lines", "Northstar Shipping", "Pacific Arrow",
                "Redsea Express", "Jade Ocean", "Kestrel Line"]

BUDGET_BASE_MIN = 2.0           # production: min(30, 2 + 8.5 * n) minutes per run
BUDGET_PER_CARRIER_MIN = 8.5
BUDGET_CAP_MIN = 30.0
RETRY_DELAYS_MIN = [10, 25]     # production: retries after 10 and 25 min -> at most 3 runs


def run_budget(n_carriers):
    """Shared time budget (minutes) of ONE run that checks `n_carriers` carriers."""
    return min(BUDGET_CAP_MIN, BUDGET_BASE_MIN + BUDGET_PER_CARRIER_MIN * n_carriers)


def budget_text(n_carriers):
    raw = BUDGET_BASE_MIN + BUDGET_PER_CARRIER_MIN * n_carriers
    note = f", capped at {BUDGET_CAP_MIN:g}" if raw > BUDGET_CAP_MIN else ""
    return f"shared budget {run_budget(n_carriers):.1f} min ({BUDGET_BASE_MIN:g} + {BUDGET_PER_CARRIER_MIN:g} x {n_carriers}{note})"


# --- a fake price list: the "live" prices the fake portals show ---------------------------
LANE_BASE_40GP = {                       # USD for a 40GP, before carrier and cargo adjustments
    ("Hai Phong", "Singapore"): 600,
    ("Ho Chi Minh", "Busan"): 900,
    ("Hai Phong", "Busan"): 820,
    ("Da Nang", "Busan"): 850,
    ("Hai Phong", "Los Angeles"): 3300,
    ("Ho Chi Minh", "Rotterdam"): 4700,
}
CARRIER_FACTOR = {"Bluewave Lines": 0.97, "Northstar Shipping": 1.02, "Pacific Arrow": 1.00,
                  "Redsea Express": 1.05, "Jade Ocean": 0.99, "Kestrel Line": 0.93}
CONTAINER_FACTOR = {"20GP": 0.62, "40GP": 1.0, "40HC": 1.05}
CHARCOAL_FACTOR = 1.15                   # charcoal is priced higher than general cargo


# Some carriers state that a fee is already included in their quoted price.
INCLUDED_FEES = {"Redsea Express": ("DOC",)}


@rule("BK-01", "Price check only: nothing is ever booked")
def assert_price_check_only(portal):
    """A portal adapter may only ASK for a price. Refuse any adapter that could book.

    Why: a price check is harmless; a booking creates an obligation. Keeping the
    adapters unable to book makes the promise "we never book" a fact, not a habit.
    """
    verbs = ("book", "confirm", "submit", "reserve")
    bad = [n for n in dir(portal) if not n.startswith("_") and any(v in n.lower() for v in verbs)]
    if bad:
        raise RuntimeError(f"portal adapter must not expose booking actions: {bad}")


@dataclass
class PortalReply:
    kind: str                    # "ok" | "temporary" | "no_price"
    minutes: float               # how long the (simulated) check took
    message: str = ""
    price_usd: float = 0.0
    includes: tuple = ()         # fees the carrier says are already inside the price (rule LC-04)


# --- scripted behaviour of each fake carrier ---------------------------------------------
# A scenario answers: "what happens on try number `attempt` for this request?"
# It returns (kind, minutes, message).

def _always_ok(minutes):
    return lambda req, attempt: ("ok", minutes, "")


def _northstar(req, attempt):
    if req.cargo == "charcoal":
        return ("no_price", 0.5, "cargo type not accepted")          # permanent answer
    if attempt == 1:
        return ("temporary", 0.4, "login problem")                   # fixes itself later
    return ("ok", 1.7, "")


def _pacific_arrow(req, attempt):
    if req.cargo == "general":
        return ("temporary", 0.6, "site down, HTTP 503")             # still down in every run
    if attempt == 1:
        return ("ok", 45.0, "")           # the portal HANGS: it would answer after 45 min, far over the budget
    return ("ok", 3.1, "")                # in the retry run it answers normally


def _redsea(req, attempt):
    if (req.pol, req.pod) == ("Hai Phong", "Singapore"):
        return ("no_price", 0.9, "no direct service on this lane")  # permanent answer
    return ("ok", 1.3, "")


SCENARIOS = {
    "Bluewave Lines": _always_ok(1.4),
    "Northstar Shipping": _northstar,
    "Pacific Arrow": _pacific_arrow,
    "Redsea Express": _redsea,
    "Jade Ocean": _always_ok(1.5),
    "Kestrel Line": _always_ok(1.6),
}


class FakePortal:
    """Pretends to be one carrier website. Its ONLY action is check_price()."""

    def __init__(self, name):
        self.name = name

    def check_price(self, req, attempt):
        kind, minutes, message = SCENARIOS[self.name](req, attempt)
        if kind != "ok":
            return PortalReply(kind, minutes, message)
        base = LANE_BASE_40GP.get((req.pol, req.pod))
        if base is None:
            return PortalReply("no_price", minutes, "lane not served")
        price = base * CARRIER_FACTOR[self.name] * CONTAINER_FACTOR[req.container]
        if req.cargo == "charcoal":
            price *= CHARCOAL_FACTOR
        return PortalReply("ok", minutes, "", round(price / 5) * 5,           # multiple of 5
                           INCLUDED_FEES.get(self.name, ()))


def make_portals():
    return {name: FakePortal(name) for name in PORTAL_ORDER}


# --- the runner --------------------------------------------------------------------------
@dataclass
class PortalOutcome:
    carrier: str
    status: str = "pending"      # "price" | "no_price" | "gave_up" | "contract"
    price: Price = None
    message: str = ""
    minutes: float = 0.0         # total simulated minutes spent on this carrier
    attempts: list = field(default_factory=list)     # one text line per run the carrier took part in


@rule("BK-08", "Temporary failures are retried in new runs; 'no price' is final")
def run_portals(req, carriers, portals, log, as_of, sleep=lambda minutes: None, trace=None):
    """Check `carriers`, then retry the temporary failures in new runs.

    Returns (outcomes, first_pass_minutes, total_minutes).
      first_pass_minutes: how long the first run took. Compare it with the real
                          system (1 carrier about 1.5 min, all 6 about 9-14 min).
      total_minutes:      simulated clock when the last run finished. It includes
                          the 10 and 25 minute waits before the retry runs.

    How it works:
      1. Run 1 checks every carrier, one after another, inside a shared budget.
      2. Carriers with a TEMPORARY result (including timeouts) are collected.
      3. If there are any and retries are left, wait 10 (then 25) minutes and
         start a new run with only those carriers and a new, smaller budget.
      4. After the last retry, carriers that still fail are marked "gave up".
    """
    for carrier in carriers:
        assert_price_check_only(portals[carrier])            # BK-01
        hit(trace, "BK-01", carrier, "adapter can only check prices")
    outcomes = {c: PortalOutcome(c) for c in carriers}
    pending, run_no, clock, first_pass = list(carriers), 1, 0.0, 0.0

    while pending:
        budget = run_budget(len(pending))
        label = "first pass" if run_no == 1 else f"retry {run_no - 1}"
        n = len(pending)
        log.add(f"  {label}: {n} carrier{'' if n == 1 else 's'}, {budget_text(n)}")
        used, failed = _one_run(req, pending, run_no, budget, portals, outcomes, log, as_of, sleep, trace)
        clock += used
        if run_no == 1:
            first_pass = round(clock, 1)
        if not failed:
            break
        if run_no > len(RETRY_DELAYS_MIN):               # no retries left
            for c in failed:
                outcomes[c].status = "gave_up"
                hit(trace, "BK-08", c, f"gave up after {run_no} runs")
                log.add(f"  {c:<19} gave up after {run_no} runs ({outcomes[c].message})")
            break
        delay = RETRY_DELAYS_MIN[run_no - 1]
        log.add(f"  -- retry {run_no} is a NEW run, only for: {', '.join(failed)}; starts in {delay} min --")
        clock += delay
        pending, run_no = failed, run_no + 1
    return list(outcomes.values()), first_pass, round(clock, 1)


def _one_run(req, carriers, run_no, budget, portals, outcomes, log, as_of, sleep, trace=None):
    """One run: carriers one after another inside ONE shared budget.

    Returns (minutes_used, carriers_that_failed_temporarily).
    If the budget runs out, the whole run is stopped: the carrier in progress and
    every carrier not reached yet count as temporary failures (timeout).
    """
    elapsed, failed, stopped = 0.0, [], False
    for carrier in carriers:
        out = outcomes[carrier]
        if stopped:                                       # run already killed: never reached
            out.message = "timeout: run budget used up before this carrier was reached"
            hit(trace, "BK-08", carrier, "not reached, retried in the next run")
            out.attempts.append(f"run {run_no}: TEMPORARY ({out.message})")
            log.add(f"  {carrier:<19} not reached  TEMPORARY ({out.message}) -> goes to the next retry run")
            failed.append(carrier)
            continue

        reply = portals[carrier].check_price(req, run_no)
        spent = reply.minutes
        if elapsed + spent > budget:                      # this check outlives the shared budget
            spent, stopped = budget - elapsed, True
            reply = PortalReply("temporary", spent,
                                f"timeout: needed {reply.minutes:g} min, run budget used up")
        sleep(spent)
        elapsed += spent
        out.minutes += spent

        if reply.kind == "ok":
            out.status, out.message = "price", ""
            out.price = Price(carrier, reply.price_usd, as_of + timedelta(days=14), "portal",
                              f"live portal check, run {run_no}", req.cargo, reply.includes)
            text = f"OK  USD {reply.price_usd:,.0f}"
        elif reply.kind == "no_price":                    # permanent: an answer, not an error
            out.status, out.message = "no_price", reply.message
            hit(trace, "BK-08", carrier, f"'{reply.message}' is a final answer, no retry")
            if "cargo" in reply.message:
                hit(trace, "BK-06", carrier, "portal does not accept this cargo type")
            text = f"NO PRICE ({reply.message}) - accepted as the answer, no retry"
        else:                                             # temporary: try again in a later run
            out.message = reply.message
            failed.append(carrier)
            hit(trace, "BK-08", carrier, f"temporary failure in run {run_no}: {reply.message}")
            text = f"TEMPORARY ({reply.message})"
            if stopped:
                text += " -> RUN STOPPED, carriers after this one are not checked"
        out.attempts.append(f"run {run_no}: {text} [{spent:.1f} min]")
        log.add(f"  {carrier:<19} {text}  ({spent:.1f} min; {elapsed:.1f} of {budget:.1f} min used)")
    return elapsed, failed
