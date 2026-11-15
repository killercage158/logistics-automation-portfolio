"""Step 4: Gate 1 writing. An approved idea becomes a draft post, or is flagged "needs source".

For each approved idea, in this order:

  1. MK-06 source too thin? Main text under 500 characters, or visibly cut ("... See more"):
     do NOT call the AI. Flag "needs source", keep the exact text the pipeline read, and store a
     fingerprint of it. The idea runs again only when an editor changes that text.
  2. MK-08 facts by code: source name, whether to credit it, publication date -> one fixed
     "Source: ..." line the AI must copy (news and video channels are credited, social pages are not).
  3. Ask the AI for {"headline", "caption", "image_prompt"}. At Gate 1 ONLY, the AI may answer
     "NOT ENOUGH SOURCE: <reason>" instead (MK-07); that idea is flagged like step 1.
  4. MK-09 voice check: banned phrases from prompts/voice.md. Found? Ask again once, listing them.
     Still there? Keep the draft but flag it for the reviewer.
  5. MK-08 safety net: the source line is missing from the caption? Code appends it.
  6. MK-10 format rules and MK-11 card rules: news card (image card, no comment), text card
     (headline + source line, at most 120 characters, plus an author comment), photo album
     (the source's own photos).

WHY "needs source" instead of writing anyway: a thin or cut source makes the AI fill the
gaps with invented consequences and dates. Showing the editor what the pipeline read lets
them add the missing text in a minute; nothing false gets published.

WHY decide "write or refuse" only here: Gate 1 is the moment an editor can still add text.
Later steps (redo, messaging article) reuse the same saved source and must not refuse.

In production this is the Gate 1 step of the polling loop: it locks the idea row, reads the
full source, calls the writer model, renders the card and creates the draft row.
"""
import hashlib
import re

from engine.cards import COVER, render_card, shorten
from engine.llm import AIDeclined, AIUnavailable, parse_json_object
from engine.models import Post
from engine.prompts import REFUSAL_PREFIX

WRITE_MIN = 500
TEXT_CARD_MAX = 120


def main_length(text):
    return len(" ".join((text or "").split()))


def is_cut(text):
    t = (text or "").rstrip()
    return t.endswith("See more") or t.endswith("…") or t.endswith("...")


def fingerprint(text):
    return hashlib.sha1(" ".join((text or "").split()).encode("utf-8")).hexdigest()[:12]


def source_facts(idea):
    """MK-08: (credit it?, the fixed source line or '')."""
    if idea.kind == "social":
        return False, ""                      # team rule: social pages are not credited by name
    date = f", {idea.published_at:%d/%m/%Y}" if idea.published_at else ""
    return True, f"Source: {idea.source_name}{date}"


def voice_issues(texts, banned):
    found = []
    for phrase in banned:
        if any(re.search(r"\b" + re.escape(phrase) + r"\b", (t or "").lower()) for t in texts):
            found.append(phrase)
    return found


def short_caption(headline, source_line):
    """Text card caption: headline + source line, at most 120 characters (MK-10)."""
    room = TEXT_CARD_MAX - (len(source_line) + 1 if source_line else 0)
    head, _ = shorten(headline, room)
    return f"{head}\n{source_line}" if source_line else head


def ready(idea):
    """Ideas Gate 1 should (re)work this cycle."""
    if idea.status in ("approved", "error"):
        return True
    return idea.status == "needs_source" and fingerprint(idea.text) != idea.fingerprint


def _flag_needs_source(idea, why, now, log, trace, rule):
    idea.status, idea.fingerprint = "needs_source", fingerprint(idea.text)
    idea.reason = f"needs source: {why}. Add text to the idea and it runs again."
    idea.note(now, f"needs source ({why})")
    trace.hit(rule, f"{idea.id}: {why}")
    log.append(f"    {idea.id} NEEDS SOURCE: {why} -> editor sees the text the pipeline read [{rule}]")


def ask_draft(llm, prompts, idea, source_line, allow_refuse, feedback=""):
    task = "rewrite" if feedback else "draft"
    user = f"Task: {task}\n" + prompts.source_block(idea, idea.fmt, feedback)
    return llm.complete(prompts.post_system(source_line, allow_refuse), user), user


def write_one(state, idea, llm, prompts, now, log, trace):
    if idea.fingerprint and idea.status == "needs_source":
        log.append(f"    {idea.id} source text changed by an editor -> writing again [MK-06]")
        trace.hit("MK-06", f"{idea.id}: source text changed, runs again")
    length = main_length(idea.text)
    if length < WRITE_MIN or is_cut(idea.text):
        why = (f"main text {length} characters < {WRITE_MIN}" if length < WRITE_MIN
               else "the source text is visibly cut ('See more')")
        return _flag_needs_source(idea, why + ", no AI call", now, log, trace, "MK-06")

    credit, source_line = source_facts(idea)
    trace.hit("MK-08", f"{idea.id}: " + (f"credited as '{source_line}'" if credit else "social page, not credited"))
    try:
        reply, user = ask_draft(llm, prompts, idea, source_line, allow_refuse=True)
    except AIUnavailable as e:
        log.append(f"    {idea.id} AI unavailable ({e}) -> stays approved, retried next cycle")
        return None
    except AIDeclined as e:
        idea.status, idea.reason = "error", f"AI declined: {e}; retried next cycle"
        log.append(f"    {idea.id} {idea.reason}")
        return None
    if reply.strip().upper().startswith(REFUSAL_PREFIX):
        reason = reply.strip()[len(REFUSAL_PREFIX):].strip()
        return _flag_needs_source(idea, f"the AI refused: \"{reason}\"", now, log, trace, "MK-07")
    draft = parse_json_object(reply)
    if not draft or not draft.get("headline") or not draft.get("caption"):
        idea.status, idea.reason = "error", "AI reply was not a usable draft; retried next cycle"
        log.append(f"    {idea.id} {idea.reason}")
        return None

    flags = []
    banned = prompts.banned_phrases()
    issues = voice_issues([draft["headline"], draft["caption"]], banned)
    if issues:
        log.append(f"    {idea.id} voice check: uses {', '.join(repr(x) for x in issues)} -> asking once more "
                   f"with the list [MK-09]")
        trace.hit("MK-09", f"{idea.id}: banned {', '.join(issues)}, regenerated")
        retry_user = user + "\n\nYour previous draft broke the voice rules. It used: " + ", ".join(issues) + \
            ". Write it again without these phrases."
        second = parse_json_object(llm.complete(prompts.post_system(source_line, True), retry_user))
        if second and second.get("headline") and second.get("caption"):
            draft = second
        still = voice_issues([draft["headline"], draft["caption"]], banned)
        if still:
            flags.append(f"voice: still uses {', '.join(still)}")
            trace.hit("MK-09", f"{idea.id}: still uses {', '.join(still)}, flagged for the reviewer")
            log.append(f"    {idea.id} voice check failed again -> draft kept, FLAGGED for the reviewer [MK-09]")
        else:
            log.append(f"    {idea.id} voice check passed on the second try [MK-09]")
    return build_post(state, idea, draft, source_line, flags, llm, prompts, now, log, trace)


def build_post(state, idea, draft, source_line, flags, llm, prompts, now, log, trace):
    caption = draft["caption"].strip()
    if source_line and source_line not in caption:
        caption = f"{caption}\n\n{source_line}"
        trace.hit("MK-08", f"{idea.id}: source line missing in the AI caption, appended by code")
        log.append(f"    {idea.id} source line missing in the AI caption -> appended by code [MK-08]")
    headline, was_cut = shorten(draft["headline"])
    if was_cut:
        trace.hit("MK-11", f"{idea.id}: headline {len(draft['headline'])} characters -> cut to {len(headline)}")
        log.append(f"    {idea.id} headline has {len(draft['headline'])} characters > 60 -> cut at a word to "
                   f"{len(headline)} [MK-11]")
    post = Post(id="P-" + idea.id[2:], idea_id=idea.id, fmt=idea.fmt, headline=headline, caption=caption,
                source_line=source_line, flags=flags)
    if idea.fmt == "news card":
        post.card_svg = render_card(headline)
        trace.hit("MK-10", f"{post.id}: news card = image card + caption, no author comment")
        trace.hit("MK-11", f"{post.id}: feed card 1080x1080 rendered")
    elif idea.fmt == "text card":
        post.caption = short_caption(headline, source_line)
        try:
            post.comment = llm.complete(prompts.comment_system(),
                                        "Task: comment\n" + prompts.source_block(idea, idea.fmt)).strip()
        except (AIUnavailable, AIDeclined):
            post.flags.append("author comment missing: add one before approving")
        trace.hit("MK-10", f"{post.id}: text card = {len(post.caption)}-character caption + author comment")
    elif idea.fmt == "photo album":
        post.photos = list(idea.photos)
        trace.hit("MK-10", f"{post.id}: photo album = {len(post.photos)} source photos + caption")
    post.cover_svg = render_card(headline, COVER, "cover", "Article")
    post.note(now, f"draft written from {idea.id}")
    state.posts[post.id] = post
    idea.status, idea.reason = "drafted", f"draft {post.id} waiting for Gate 2"
    idea.note(now, f"draft {post.id} created")
    log.append(f"    {idea.id} -> {post.id} {idea.fmt}: \"{headline}\""
               + (f" | {len(post.photos)} photos" if post.photos else "")
               + (" | + author comment" if post.comment else "")
               + (f" | FLAGS: {'; '.join(post.flags)}" if post.flags else ""))
    return post


def gate1_sweep(state, llm, prompts, now, log, trace):
    todo = [i for i in state.ideas.values() if ready(i)]
    if not todo:
        return 0
    log.append(f"  Gate 1 writing: {len(todo)} idea(s)")
    for idea in todo:
        write_one(state, idea, llm, prompts, now, log, trace)
    return len(todo)
