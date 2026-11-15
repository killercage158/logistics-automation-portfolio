"""Rule MK-13: the redo flow, when an editor asks for changes instead of approving.

The editor writes feedback ("make the caption shorter and drop the question"). The pipeline:
  1. guesses the scope from the words: image words (image, photo, background, colour...) vs
     text words (caption, headline, shorter, tone...); a tie means "both";
  2. rewrites that part from the SAVED source text (no new scrape, so the facts do not change),
     with the feedback added to the prompt. The AI is not allowed to refuse here (MK-07);
  3. keeps the source line rule (MK-08) and the format rules (MK-10), re-renders the card if
     the image is in scope;
  4. uses the request once and returns the draft to review.

WHY guess the scope with keywords and not ask the AI: it is free, instant and predictable,
and editors can always say "caption" or "image" explicitly.

In production the editor picks "Redo" in the draft's review dropdown and writes feedback
in a text field; a scope field is optional and the same keyword guess fills it.
"""
from engine.cards import render_card, shorten
from engine.llm import AIDeclined, AIUnavailable, parse_json_object
from engine.writer import ask_draft, short_caption, voice_issues

IMAGE_WORDS = ("image", "picture", "photo", "background", "colour", "color", "card design", "visual")
TEXT_WORDS = ("caption", "text", "headline", "wording", "tone", "shorter", "longer", "sentence", "question", "word")


def infer_scope(feedback):
    f = (feedback or "").lower()
    image = sum(w in f for w in IMAGE_WORDS)
    text = sum(w in f for w in TEXT_WORDS)
    return "image" if image > text else "caption" if text > image else "both"


def redo_one(post, idea, llm, prompts, now, log, trace):
    scope = infer_scope(post.feedback)
    log.append(f"    {post.id} redo, scope '{scope}' (guessed from the feedback words) [MK-13]")
    if scope in ("caption", "both"):
        try:
            reply, _ = ask_draft(llm, prompts, idea, post.source_line, allow_refuse=False, feedback=post.feedback)
        except (AIUnavailable, AIDeclined) as e:
            log.append(f"    {post.id} AI unavailable ({e}) -> redo retried next cycle")
            return False
        draft = parse_json_object(reply)
        if not draft or not draft.get("headline") or not draft.get("caption"):
            log.append(f"    {post.id} rewrite not usable -> redo retried next cycle")
            return False
        post.headline, _ = shorten(draft["headline"])
        caption = draft["caption"].strip()
        if post.source_line and post.source_line not in caption:
            caption = f"{caption}\n\n{post.source_line}"
        post.caption = short_caption(post.headline, post.source_line) if post.fmt == "text card" else caption
        issues = voice_issues([post.headline, post.caption], prompts.banned_phrases())
        if issues:
            post.flags.append(f"voice: uses {', '.join(issues)}")
    if scope in ("image", "both") and post.fmt == "news card":
        post.card_svg = render_card(post.headline)
    trace.hit("MK-13", f"{post.id}: rewritten ({scope}) from the saved source, back to review")
    post.note(now, f"rewritten ({scope}) from the saved source")
    log.append(f"    {post.id} rewritten from the saved source (no new scrape, no refusal allowed): "
               f"\"{post.headline}\" -> back to review")
    post.status, post.feedback = "in_review", ""
    return True


def redo_sweep(state, llm, prompts, now, log, trace):
    todo = [p for p in state.posts.values() if p.status == "redo"]
    for post in todo:
        redo_one(post, state.ideas[post.idea_id], llm, prompts, now, log, trace)
    return len(todo)
