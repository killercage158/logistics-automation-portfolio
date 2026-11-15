"""Every business rule in the pipeline has an ID, MK-01 to MK-18.

The console log, the HTML board and the tests all use the same IDs. You can
follow one rule from its description here, to the log line where it fired, to
the test that proves it. The board ends with a table of every rule and how many
times it fired in the run.

WHY rule IDs: when an editor asks "why did this idea never become a post?", the
answer is a named rule ("MK-06: the source was too thin, add text and it runs
again"), not a guess.
"""

RULES = {
    "MK-01": ("Collect thresholds",
              "Videos need at least 1,000 views and social posts at least 25 reactions. News older than "
              "24 hours is skipped. Below the bar = not written to the board."),
    "MK-02": ("Content keys and a permanent ledger",
              "Social links change on every visit, so a social post is keyed by page + its first 100 "
              "characters; a video by its platform id; a news item by its URL without tracking parameters. "
              "Every key written to the board goes into a ledger that is never emptied."),
    "MK-03": ("AI relevance filter with reasons",
              "The AI marks each new idea relevant or off-topic with a reason, in batches. An unusable reply "
              "is asked once more, then the batch is split in half. One idea that still gets no verdict is "
              "kept for a human to judge."),
    "MK-04": ("AI outage: mark nothing",
              "If the AI is unavailable, no idea is marked either way; the filter runs again next cycle."),
    "MK-05": ("Gate 1: the editor approves ideas",
              "Only ideas an editor approved are written. A rejected idea leaves the board, and its key stays "
              "in the ledger so it does not come back."),
    "MK-06": ("Source too thin: flag, do not write",
              "If the main source text is under 500 characters, or visibly cut ('... See more'), the AI is "
              "not called. The idea is flagged 'needs source' with the text the pipeline read. It runs again "
              "only when an editor changes that text."),
    "MK-07": ("The AI may refuse only at Gate 1",
              "At Gate 1 the AI may answer 'NOT ENOUGH SOURCE: <reason>'; the idea is flagged like MK-06. "
              "Redo and messaging articles reuse the same source and are never allowed to refuse."),
    "MK-08": ("Facts come from code",
              "Code decides the source name, whether to credit it (news and video channels yes, social "
              "pages no) and the publication date. If the AI drops the source line, code adds it."),
    "MK-09": ("Voice rules are checked",
              "Banned phrases from prompts/voice.md are searched in every draft. A draft that uses one is "
              "regenerated once with the list of problems; if it still fails it is flagged for the reviewer."),
    "MK-10": ("Format rules",
              "News card: image card + caption, no author comment. Text card: short caption (headline + "
              "source line, at most 120 characters) + an author comment. Photo album: the source's own photos."),
    "MK-11": ("Card rules",
              "Headline at most 60 characters and 3 lines; the largest font that fits is used. Feed card "
              "1080x1080; messaging cover 1280x720."),
    "MK-12": ("Gate 2: nothing is published without approval",
              "A draft is published only after an editor approves it. A rejected draft is never posted."),
    "MK-13": ("Redo from the saved source",
              "An editor's redo feedback rewrites the part it is about (caption, image or both, guessed from "
              "the words) from the saved source text. The request is used once; the draft returns to review."),
    "MK-14": ("Scheduling and golden hours",
              "Publish now, at a fixed time, or in a golden hour (07, 12, 18, 21): the nearest free slot "
              "today, else 07:00 tomorrow. One post per slot."),
    "MK-15": ("Each channel succeeds or fails on its own",
              "Every channel has its own done flag and link. A failed channel is retried next cycle without "
              "re-posting the channels that worked."),
    "MK-16": ("Instagram mirrors single-image posts only",
              "After a Facebook post with exactly one image, the same image and caption go to Instagram. "
              "Text posts and albums are skipped. Images outside ratio 0.8 to 1.91 are padded (tall) or "
              "cropped (wide)."),
    "MK-17": ("Messaging articles: hidden, with a monthly quota",
              "The messaging account gets a separate long article, created HIDDEN; the team publishes it "
              "themselves. Nothing is broadcast. When the monthly quota is used up, the article waits and is "
              "retried later; other channels are not affected."),
    "MK-18": ("A silent source is a broken collector",
              "A source that returns zero items is reported as a collector problem, not as 'no news today'."),
}


class RuleTrace:
    """Counts how often each rule fired and keeps a few different examples for the board."""

    def __init__(self):
        self.hits = {rule_id: [] for rule_id in RULES}

    def hit(self, rule_id, detail):
        if rule_id not in RULES:
            raise KeyError(f"Unknown rule id {rule_id}")
        self.hits[rule_id].append(detail)

    def count(self, rule_id):
        return len(self.hits[rule_id])

    def examples(self, rule_id, n=3):
        seen = []
        for detail in self.hits[rule_id]:
            if detail not in seen:
                seen.append(detail)
            if len(seen) == n:
                break
        return seen
