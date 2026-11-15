"""Fake carrier websites that answer from recorded files.

Each crawl day has a folder fixtures/dayN/ with one sub-folder per carrier.
A request for a path (for example "VNHPH-KRPUS") returns the matching file.

  missing file              -> HTTP 404 (a permanent error: wrong route or port name)
  fixtures/dayN/incidents.json lists PLANTED trouble per carrier and path:
      {"pacific_arrow": {"*": ["503", "503", "503"]}}
  means every path of Pacific Arrow answers 503 three times before the real file.
  "timeout" means the answer never came (costs 30 simulated seconds).

CappedApi imitates an API that filters by date window and silently returns only
the first N sailings (the latest ones are dropped, with no warning and no "next
page"). The crawl must notice and split the window (rule SC-04).

WHY recorded files: the demo runs offline, gives the same result every time,
and the trouble is planted on purpose so you can watch each rule react.
In production, these are real carrier APIs and websites.
"""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

TIMEOUT_SECONDS = 30.0


@dataclass
class Response:
    status: int                  # 200, 404, 429, 503 ... or 0 for "no answer" (timeout)
    body: str
    seconds: float               # how long the call took (simulated)

    @property
    def is_timeout(self):
        return self.status == 0


class RecordedSite:
    """One carrier's website for one crawl day."""

    def __init__(self, day_dir, slug, ext, latency_s=0.8):
        self.folder = Path(day_dir) / slug
        self.slug = slug
        self.ext = ext
        self.latency_s = latency_s
        incidents_file = Path(day_dir) / "incidents.json"
        planted = json.loads(incidents_file.read_text(encoding="utf-8")) if incidents_file.exists() else {}
        self.incidents = planted.get(slug, {})
        self._queues = {}            # path -> remaining planted answers for that path

    def _next_incident(self, path):
        """Pop the next planted answer for this path, if any ('*' applies to every path)."""
        if path not in self._queues:
            self._queues[path] = list(self.incidents.get(path, self.incidents.get("*", [])))
        queue = self._queues[path]
        return queue.pop(0) if queue else None

    def get(self, path, params=None):
        incident = self._next_incident(path)
        if incident == "timeout":
            return Response(0, "", TIMEOUT_SECONDS)
        if incident is not None:
            return Response(int(incident), f"planted HTTP {incident}", self.latency_s)
        file = self.folder / f"{path}.{self.ext}"
        if not file.exists():
            return Response(404, "not found", self.latency_s)
        return Response(200, self.answer(file, params), self.latency_s)

    def answer(self, file, params):
        return file.read_text(encoding="utf-8")


class CappedApi(RecordedSite):
    """A JSON API: the file holds the carrier's whole list; the API filters and CAPS it."""

    def __init__(self, day_dir, slug, cap, latency_s=0.8):
        super().__init__(day_dir, slug, "json", latency_s)
        self.cap = cap

    def answer(self, file, params):
        sailings = json.loads(file.read_text(encoding="utf-8"))["sailings"]
        lo, hi = date.fromisoformat(params["from"]), date.fromisoformat(params["to"])
        hits = [s for s in sailings if lo <= date.fromisoformat(s["legs"][0]["etd"]) <= hi]
        hits.sort(key=lambda s: s["legs"][0]["etd"])
        hits = hits[:self.cap]                 # the silent cap: latest departures simply vanish
        return json.dumps({"results": hits, "returned": len(hits)})
