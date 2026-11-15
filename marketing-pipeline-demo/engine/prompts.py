"""Build the AI prompts from the rule files in prompts/.

The marketing team owns the voice, so the voice lives in plain text files they can
edit without touching code:

  voice.md          brand voice and the list of banned phrases (MK-09 reads the list)
  relevance.md      what counts as relevant for a freight forwarder (MK-03)
  post_rules.md     output format for a post draft
  refuse_rule.md    the "NOT ENOUGH SOURCE" permission, added ONLY at Gate 1 (MK-07)
  comment_rules.md  the author comment under a text card
  oa_article.md     the long article for the messaging account

WHY code adds the facts: the source name and whether to credit it are decided in
code (MK-08) and handed to the AI as a fixed line to copy, instead of letting the
model guess a name or a date.

In production the same split exists: a knowledge file with the brand voice owned
by the content lead, a separate article prompt for the messaging account, and code
that injects the source facts.
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PROMPTS = HERE / "prompts"
REFUSAL_PREFIX = "NOT ENOUGH SOURCE:"


class Prompts:
    def __init__(self, folder=PROMPTS):
        self.folder = Path(folder)

    def read(self, name):
        return (self.folder / name).read_text(encoding="utf-8").strip()

    def banned_phrases(self):
        """The bullet list under '## Banned phrases' in voice.md."""
        text = self.read("voice.md")
        section = text.split("## Banned phrases", 1)[1] if "## Banned phrases" in text else ""
        section = section.split("\n## ", 1)[0]
        return [m.strip().strip('"').lower() for m in re.findall(r"^- (.+)$", section, re.M)]

    # --- system prompts ------------------------------------------------------------------------
    def relevance_system(self):
        return self.read("relevance.md")

    def post_system(self, source_line, allow_refuse):
        rule = (f"\n\nSource line: the caption must end with exactly this line:\n{source_line}"
                if source_line else "\n\nSource line: do not name the source anywhere in the caption.")
        return (self.read("voice.md") + "\n\n" + self.read("post_rules.md") + rule
                + ("\n\n" + self.read("refuse_rule.md") if allow_refuse else ""))

    def comment_system(self):
        return self.read("voice.md") + "\n\n" + self.read("comment_rules.md")

    def oa_system(self, source_line):
        return (self.read("voice.md") + "\n\n" + self.read("oa_article.md")
                + (f"\n\nEnd the article with this line:\n{source_line}" if source_line else ""))

    # --- user messages -------------------------------------------------------------------------
    @staticmethod
    def source_block(idea, fmt, feedback=""):
        lines = [f"Idea: {idea.id}", f"Format: {fmt}", f"Original title: {idea.title}",
                 f"Source type: {idea.kind}", "Source text:", idea.text]
        if feedback:
            lines += ["", f"Reviewer feedback to apply: {feedback}"]
        return "\n".join(lines)
