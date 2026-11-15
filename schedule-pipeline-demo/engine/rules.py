"""Every business rule in the pipeline has an ID, SC-01 to SC-19.

The console log, the HTML health report and the tests all use the same IDs.
You can follow one rule from its description here, to the log line where it
fired, to the test that proves it. The report ends with a table of every rule
and how many times it fired in the run.

WHY rule IDs: when a booking officer asks "why did this sailing disappear from
my list?", the answer should be a rule with a name ("SC-13: retired because the
carrier stopped listing it"), not a guess.
"""
import threading

RULES = {
    "SC-01": ("Polite pacing and retries",
              "Wait a minimum gap between two calls to the same carrier. Retry temporary errors "
              "(rate limit 429, server errors 5xx, timeouts) with a growing wait. "
              "Never retry permanent errors such as 404 or 401."),
    "SC-02": ("One carrier cannot hide another",
              "Carriers are crawled in parallel and each one in its own error box. "
              "A carrier that fails or crashes is recorded; the others still run."),
    "SC-03": ("Route errors go into the result",
              "A route that fails is written into the carrier's error list, never only into a log file."),
    "SC-04": ("Split windows at the result cap",
              "Some APIs silently return at most N results per call. If a call returns exactly N, "
              "split the date window in half and ask again, so no late sailing is lost."),
    "SC-05": ("One spelling per port",
              "Every port spelling or code ('HAIPHONG', 'Hai Phong', 'VIETNAM, HAIPHONG') becomes one "
              "UN/LOCODE. An unknown port rejects the row with a reason."),
    "SC-06": ("Clean vessel and voyage",
              "Split 'NORTHSTAR LYRA 2647N' into vessel and voyage; strip a vessel code glued to the "
              "voyage ('KSDW2645N' becomes '2645N'); upper case, single spaces."),
    "SC-07": ("Dates are parsed, never guessed",
              "Several date formats are read. Text that is not a date ('TBA') becomes empty. "
              "A row without a departure date is rejected with a reason; it never breaks the batch."),
    "SC-08": ("Cut-off has its own field",
              "Shipping-instruction (SI) and container-yard (CY) cut-offs are stored in their own "
              "fields. A cut-off is never stored as a departure or arrival date."),
    "SC-09": ("Voyage key without dates",
              "A voyage is identified by carrier + vessel + voyage + POL + POD. Dates are attributes "
              "that change, so they are never part of the key."),
    "SC-10": ("De-duplicate inside one crawl",
              "If the same voyage key appears twice in one crawl, keep the row fetched last "
              "(the freshest answer) and log the other."),
    "SC-11": ("Update in place, newest crawl wins",
              "A voyage already in the database is updated, not copied. "
              "An older crawl never overwrites data from a newer one."),
    "SC-12": ("Detect ETD changes",
              "When a voyage's departure date differs from the stored one, record old date, new date "
              "and days moved. If a booking is linked to it, flag the booking."),
    "SC-13": ("Retire, never delete",
              "A stored voyage the carrier no longer lists is marked inactive. Only on routes that "
              "succeeded and returned rows, and only inside the date window that crawl covered."),
    "SC-14": ("Booked voyages are never touched",
              "A voyage linked to a booking is never retired or deleted, even if the carrier stopped "
              "listing it. It is flagged for the booking team instead."),
    "SC-15": ("Revive on return",
              "A retired voyage that the carrier lists again becomes active again, on the same row."),
    "SC-16": ("Do not trust 'success'",
              "The job result says success when nothing crashed. The health check reads each "
              "carrier's own errors instead."),
    "SC-17": ("Zero or missing routes are failures",
              "A configured route that returned zero rows, or was never reported, is a problem, "
              "not 'no sailings'."),
    "SC-18": ("Row-count drop is silent data loss",
              "A route whose row count fell to half of yesterday's or less is flagged, even though "
              "the crawl reported success."),
    "SC-19": ("Segment export rules",
              "The daily Excel holds one cargo segment: listed carriers, export lanes to the listed "
              "countries, services that accept the cargo, and only sailings the carrier listed in its "
              "latest crawl. A carrier whose latest data is older than today is marked STALE."),
}


class RuleTrace:
    """Counts how often each rule fired and keeps a few examples for the report.

    Several carriers are crawled at the same time (threads), so a lock keeps the
    counts correct.
    """

    def __init__(self):
        self.hits = {rule_id: [] for rule_id in RULES}
        self._lock = threading.Lock()

    def hit(self, rule_id, detail):
        if rule_id not in RULES:
            raise KeyError(f"Unknown rule id {rule_id}")
        with self._lock:
            self.hits[rule_id].append(detail)

    def count(self, rule_id):
        return len(self.hits[rule_id])

    def examples(self, rule_id, n=3):
        """The first n DIFFERENT details recorded for this rule."""
        seen = []
        for detail in self.hits[rule_id]:
            if detail not in seen:
                seen.append(detail)
            if len(seen) == n:
                break
        return seen
