"""Rule MK-02: content keys and a permanent ledger, so the same idea never comes back.

WHY content keys: a social platform gives the same post a different link on
every visit (tracking tokens, rotating post ids). Comparing links would let the
same post in again every day. So:

  social post  "social:<page>:<first 100 characters, normalised>"
  video        "video:<platform id>"          (the id is stable, the link is not)
  news item    "news:<url without query, fragment or trailing slash, lower case>"

WHY a separate ledger: ideas are removed from the board once they are posted,
rejected or filtered. If the memory lived on the board, removed ideas would be
collected again tomorrow. The ledger only ever grows.

In production the ledger is its own table, read in full by every collector run.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

MIN_CONTENT_CHARS = 30           # shorter than this, the text is too generic to identify a post


def normalise_text(text, limit=100):
    return re.sub(r"\W+", " ", (text or "").strip()[:limit].lower()).strip()


def page_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def canonical_url(url):
    parts = urlsplit((url or "").strip())
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}".lower()


def social_key(page, text, link=""):
    body = normalise_text(text)
    if len(body) >= MIN_CONTENT_CHARS:
        return f"social:{page_slug(page)}:{body}"
    return f"social-link:{canonical_url(link)}"      # too little text: the link is the best we have


def video_key(platform_id):
    return f"video:{platform_id}"


def news_key(url):
    return f"news:{canonical_url(url)}"


class Ledger:
    """A set of keys that only grows. Saved as JSON so you can open it after a run."""

    def __init__(self, keys=None):
        self.keys = set(keys or [])

    def __contains__(self, key):
        return key in self.keys

    def add(self, key):
        self.keys.add(key)

    def __len__(self):
        return len(self.keys)

    def save(self, path):
        Path(path).write_text(json.dumps(sorted(self.keys), indent=1, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path):
        p = Path(path)
        return cls(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else cls()
