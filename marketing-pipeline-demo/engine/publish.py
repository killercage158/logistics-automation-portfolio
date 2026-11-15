"""Step 6: publish approved posts when their time comes (MK-12, MK-15, MK-16, MK-17).

Channels and their rules:

  facebook   the company page. Text cards are posted as text with the author comment underneath;
             news cards with their card image; photo albums with all source photos.
  instagram  NOT chosen by the editor: right after a successful Facebook post with exactly ONE
             image, the same image and caption are mirrored (MK-16). Text posts and albums are
             skipped with the reason. Ratio outside 0.8-1.91 -> pad or crop.
  oa         a messaging official account: a separate long article written from the saved
             source, created HIDDEN. The team reads it and publishes it themselves; nothing is
             broadcast to followers. A monthly quota applies: when it is used up the article
             waits and is retried every 30 minutes; the other channels carry on (MK-17).

Every channel has its own state and link (MK-15). A failed channel is retried next cycle
without re-posting the channels that already worked; a post counts as published once its
Facebook post is live (the messaging article is only a hidden draft).

MockPlatforms answers like the real platforms would, from fixtures/platforms.json (the
monthly quota, articles already used this month, planted errors). In production these are
the platforms' official APIs, called with page tokens kept outside the code.
"""
import json
from datetime import timedelta
from pathlib import Path

from engine.cards import FEED, fit_for_instagram
from engine.llm import AIDeclined, AIUnavailable, parse_json_object
from engine.writer import voice_issues

OA_RETRY = timedelta(minutes=30)


class PlatformError(Exception):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class QuotaReached(Exception):
    pass


class MockPlatforms:
    """Fake Facebook page, Instagram account and messaging account."""

    def __init__(self, fixtures_dir, state):
        cfg = json.loads((Path(fixtures_dir) / "platforms.json").read_text(encoding="utf-8"))
        self.incidents = {k: {p: list(v) for p, v in d.items()} for k, d in cfg.get("incidents", {}).items()}
        state.oa_quota, state.oa_used = cfg["oa_monthly_quota"], cfg["oa_used_this_month"]
        self.state = state
        self.next_id = 100001

    def _planted(self, platform, post_id):
        queue = self.incidents.get(platform, {}).get(post_id, [])
        return queue.pop(0) if queue else None

    def _id(self):
        self.next_id += 1
        return self.next_id - 1

    def facebook_post(self, post):
        status = self._planted("facebook", post.id)
        if status:
            raise PlatformError(int(status), "planted server error")
        return f"https://facebook.example/demo-freight-co/posts/{self._id()}"

    def facebook_comment(self, link, text):
        return f"{link}?comment={self._id()}"

    def instagram_post(self, post):
        return f"https://instagram.example/p/DEMO{self._id()}"

    def oa_create(self, post, article, status="hidden"):
        if status != "hidden":
            raise ValueError("messaging articles are always created hidden in this pipeline")
        if self.state.oa_used >= self.state.oa_quota:
            raise QuotaReached(f"monthly article quota used ({self.state.oa_used}/{self.state.oa_quota})")
        self.state.oa_used += 1
        return f"https://oa.example/articles/{self._id()}?status=hidden"


def _log(state, now, post, channel, result, detail=""):
    state.publish_log.append((now.strftime("%H:%M"), post.id, channel, result, detail))


def write_oa_article(post, idea, llm, prompts, trace):
    """A separate long article from the saved source. No refusal allowed (MK-07); voice checked once."""
    user = "Task: oa_article\n" + prompts.source_block(idea, "messaging article")
    article = parse_json_object(llm.complete(prompts.oa_system(post.source_line), user))
    if not article or not article.get("title") or not article.get("body"):
        raise AIUnavailable("article reply not usable")
    issues = voice_issues([article["title"], article["body"]], prompts.banned_phrases())
    if issues:
        trace.hit("MK-09", f"{post.id} article: uses {', '.join(issues)}, flagged")
        post.flags.append(f"article voice: uses {', '.join(issues)}")
    if post.source_line and post.source_line not in article["body"]:
        article["body"] += f"\n\n{post.source_line}"
    return article


def _facebook(post, st, platforms, state, now, log, trace):
    try:
        link = platforms.facebook_post(post)
    except PlatformError as e:
        st.update(status="failed", detail=str(e))
        _log(state, now, post, "facebook", "failed", str(e))
        trace.hit("MK-15", f"{post.id} facebook: {e}, retried next cycle, other channels unaffected")
        log.append(f"    {post.id} facebook: {e} -> this channel stays open and is retried next cycle; "
                   f"other channels are not affected [MK-15]")
        return
    st.update(status="posted", link=link, detail="")
    what = {"news card": "card image", "text card": "text", "photo album": f"{len(post.photos)} photos"}[post.fmt]
    _log(state, now, post, "facebook", "posted", link)
    log.append(f"    {post.id} facebook: posted ({what}) {link}")
    if post.comment:
        platforms.facebook_comment(link, post.comment)
        _log(state, now, post, "facebook", "author comment", "posted under the post")
        log.append(f"    {post.id} facebook: author comment posted under the post")
    _instagram(post, platforms, state, now, log, trace)


def _instagram(post, platforms, state, now, log, trace):
    ig = post.channel_state.setdefault("instagram", {"status": "pending", "link": "", "detail": ""})
    if not post.single_image:
        why = "text post, no image" if post.fmt == "text card" else f"album of {len(post.photos)} photos"
        ig.update(status="skipped", detail=f"{why}: Instagram mirror takes single-image posts only")
        _log(state, now, post, "instagram", "skipped", ig["detail"])
        trace.hit("MK-16", f"{post.id}: instagram skipped ({why})")
        log.append(f"    {post.id} instagram: skipped ({why}; mirror takes single-image posts only) [MK-16]")
        return
    w, h = (post.photos[0]["w"], post.photos[0]["h"]) if post.photos else FEED
    action, nw, nh = fit_for_instagram(w, h)
    link = platforms.instagram_post(post)
    ig.update(status="posted", link=link, detail=f"image {w}x{h}: {action}" + (f" to {nw}x{nh}" if action != "ok" else ""))
    _log(state, now, post, "instagram", "posted", link)
    trace.hit("MK-16", f"{post.id}: mirrored to instagram (ratio {w / h:.2f}, {action})")
    log.append(f"    {post.id} instagram: mirrored the same image and caption (ratio {w / h:.2f}, {action}) [MK-16]")


def _oa(post, st, idea, platforms, llm, prompts, state, now, log, trace):
    if st.get("retry_at") and now < st["retry_at"]:
        return
    try:
        if post.oa_article is None:
            post.oa_article = write_oa_article(post, idea, llm, prompts, trace)
        link = platforms.oa_create(post, post.oa_article, status="hidden")
    except QuotaReached as e:
        first = st["status"] != "waiting"
        st.update(status="waiting", detail=f"{e}; retried every 30 min", retry_at=now + OA_RETRY)
        st["tries"] = st.get("tries", 0) + 1
        if first:
            _log(state, now, post, "oa", "waiting", str(e))
            trace.hit("MK-17", f"{post.id}: {e}, waits; other channels unaffected")
            log.append(f"    {post.id} oa: {e} -> article waits, retried every 30 min; other channels are "
                       f"not affected [MK-17]")
        return
    except (AIUnavailable, AIDeclined) as e:
        st.update(status="failed", detail=f"article not written: {e}")
        log.append(f"    {post.id} oa: article not written ({e}) -> retried next cycle")
        return
    st.update(status="posted", link=link, detail="created HIDDEN: the team reviews and publishes it")
    _log(state, now, post, "oa", "created hidden", link)
    trace.hit("MK-17", f"{post.id}: article created hidden ({state.oa_used}/{state.oa_quota} this month)")
    log.append(f"    {post.id} oa: article \"{post.oa_article['title']}\" created HIDDEN (team publishes it; "
               f"quota {state.oa_used}/{state.oa_quota} this month) [MK-17]")


def publish_due(state, platforms, llm, prompts, now, log, trace):
    due = [p for p in state.posts.values() if p.status in ("approved", "published")
           and p.slot is not None and p.slot <= now
           and any(s["status"] in ("pending", "failed", "waiting") for c, s in p.channel_state.items() if c != "instagram")]
    for post in due:
        idea = state.ideas[post.idea_id]
        for channel in post.channels:
            st = post.channel_state[channel]
            if st["status"] == "posted":
                continue
            if channel == "facebook":
                _facebook(post, st, platforms, state, now, log, trace)
            elif channel == "oa":
                _oa(post, st, idea, platforms, llm, prompts, state, now, log, trace)
        live = post.channel_state.get("facebook", {}).get("status") == "posted" or (
            "facebook" not in post.channels and post.channel_state.get("oa", {}).get("status") == "posted")
        if live and post.status != "published":
            post.status = "published"
            post.note(now, "published")
            idea.reason = f"published as {post.id}"
            trace.hit("MK-12", f"{post.id}: published after Gate 2 approval")
    return len(due)
