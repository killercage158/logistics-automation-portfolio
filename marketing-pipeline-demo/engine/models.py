"""Plain data containers: an Idea, a Post (the draft made from it) and the whole State of the day.

An idea moves through these statuses (the "board" shows each one):

  new           collected, waiting for the AI relevance filter
  pending       relevant, waiting for an editor (Gate 1)
  filtered      the AI judged it off-topic (with a reason)
  rejected      an editor said no at Gate 1
  needs_source  approved, but the source is too thin or the AI refused: an editor must add text
  drafted       a Post exists for it

A post moves through:

  in_review -> (redo -> in_review) -> approved -> published
  in_review -> rejected

Each post channel has its own state (pending, posted, failed, waiting, skipped)
so one channel can fail and retry without touching the others (rule MK-15).

In production these are rows in a team table: one table for ideas, one for
posts, with a human status field and a separate machine status field.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Idea:
    id: str                       # I-01, I-02 ... in collection order
    kind: str                     # social, video, news
    source_name: str              # page, channel or news site, exactly as the source names itself
    title: str
    text: str                     # the source text the pipeline read (an editor may replace it)
    link: str
    key: str                      # content key used by the ledger (MK-02)
    published_at: Optional[datetime] = None
    photos: list = field(default_factory=list)      # [{"w":..., "h":...}] original photos of a social post
    status: str = "new"
    reason: str = ""              # why it has this status, in plain words
    fmt: str = ""                 # news card, text card, photo album (chosen by the editor at Gate 1)
    fingerprint: str = ""         # needs_source: hash of the text when flagged (MK-06)
    history: list = field(default_factory=list)     # (time, text)

    def note(self, when, text):
        self.history.append((when.strftime("%H:%M"), text))


@dataclass
class Post:
    id: str                       # P-01 is the post made from idea I-01
    idea_id: str
    fmt: str
    headline: str
    caption: str
    comment: str = ""             # author comment (text cards only, MK-10)
    card_svg: str = ""            # rendered feed card (news cards)
    cover_svg: str = ""           # rendered 1280x720 cover for the messaging article
    photos: list = field(default_factory=list)
    source_line: str = ""
    status: str = "in_review"
    channels: list = field(default_factory=list)    # chosen at Gate 2: facebook, oa
    schedule: str = ""            # now, golden, or HH:MM
    slot: Optional[datetime] = None
    channel_state: dict = field(default_factory=dict)   # channel -> {"status", "link", "detail", "retry_at"}
    flags: list = field(default_factory=list)       # problems the reviewer should see (MK-09)
    feedback: str = ""
    oa_article: Optional[dict] = None               # generated once, reused on retries
    history: list = field(default_factory=list)

    def note(self, when, text):
        self.history.append((when.strftime("%H:%M"), text))

    @property
    def single_image(self):
        return bool(self.card_svg) or len(self.photos) == 1


@dataclass
class State:
    ideas: dict = field(default_factory=dict)       # id -> Idea
    posts: dict = field(default_factory=dict)       # id -> Post
    ledger: object = None                           # engine.ledger.Ledger
    publish_log: list = field(default_factory=list)  # (time, post id, channel, result, detail)
    collector_log: list = field(default_factory=list)  # (time, visit, source, seen, new, note)
    taken_slots: set = field(default_factory=set)   # golden-hour slots already given to a post
    next_number: int = 1
    oa_used: int = 0
    oa_quota: int = 3

    def new_idea_id(self):
        idea_id = f"I-{self.next_number:02d}"
        self.next_number += 1
        return idea_id
