"""Step 7: the HTML board. Every idea's status, every post with its card, the publish log.

What an editor needs to see at the end of the day, on one page:

  1. every draft and post: card, caption, author comment, schedule, each channel's state
     and link, and any flag the reviewer must look at
  2. every idea collected today: status, why it has that status, and what happens next
     (filtered out with the AI's reason, rejected, needs source, waiting for Gate 1 ...)
  3. the publish log: each channel attempt with its result
  4. the collectors: items per source per visit; a source that returned nothing is red (MK-18)
  5. the rule trace: every rule ID and how often it fired

WHY one page: the team's real interface is a table with a status column. This board is the
same idea with nothing to install. Cards are embedded inline so the file can be mailed or opened anywhere.
"""
import base64
from html import escape

from engine.cards import photo_placeholder
from engine.rules import RULES

STYLE = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px auto;max-width:1180px;color:#1d2433;padding:0 16px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 10px;border-bottom:2px solid #dde3ee;padding-bottom:4px}
.sub{color:#5b6475;font-size:13px} table{border-collapse:collapse;width:100%;font-size:13px}
th{background:#eef2f8;text-align:left} th,td{border:1px solid #dde3ee;padding:5px 8px;vertical-align:top}
.tiles{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}
.tile{flex:1;min-width:105px;background:#f6f8fb;border:1px solid #dde3ee;border-radius:6px;padding:8px 12px}
.tile .n{font-size:20px;font-weight:600} .tile .l{font-size:12px;color:#5b6475}
.posts{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.post{border:1px solid #dde3ee;border-radius:8px;padding:10px;background:#fff}
.post img.card{width:100%;border-radius:4px;display:block} .album{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px}
.album img{width:100%;border-radius:3px} .textcard{background:#b3261e;color:#fff;border-radius:4px;padding:26px 14px;
font-weight:700;font-size:15px;white-space:pre-wrap;min-height:90px}
.cap{white-space:pre-wrap;font-size:12.5px;margin:8px 0;color:#2b3445;max-height:150px;overflow:hidden}
.comment{white-space:pre-wrap;font-size:12px;background:#f6f8fb;border-left:3px solid #9fb3cc;padding:4px 8px;margin:6px 0}
.ch{font-size:12px;margin:3px 0} .flagtxt{color:#a55a00;font-size:12px}
.badge{display:inline-block;border-radius:10px;padding:1px 8px;font-size:11px;color:#fff;font-weight:600}
.published,.posted,.drafted{background:#1c7a3b} .approved,.pending{background:#1f6fb5} .in_review{background:#5b6475}
.redo,.waiting,.needs_source,.failed{background:#c25e00} .rejected,.filtered{background:#8a8f99}
.new,.skipped{background:#9aa3b2} .error{background:#b3261e} .createdhidden{background:#6a3fb5}
tr.bad td{background:#fdeeee} .rule{font-family:Consolas,monospace;font-size:12px;color:#3d4b66;white-space:nowrap}
.foot{margin-top:28px;color:#5b6475;font-size:12px}
"""


def badge(status):
    css = status.replace(" ", "")
    return f"<span class='badge {escape(css)}'>{escape(status.replace('_', ' '))}</span>"


def svg_img(svg, css=""):
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"<img class='{css}' src='data:image/svg+xml;base64,{data}' alt='card'>"


def tile(n, label):
    return f"<div class='tile'><div class='n'>{n}</div><div class='l'>{escape(label)}</div></div>"


def table(headers, rows, classes=None):
    if not rows:
        return "<p class='sub'>None.</p>"
    out = "<table><tr>" + "".join(f"<th>{escape(h)}</th>" for h in headers) + "</tr>"
    for i, r in enumerate(rows):
        cls = f" class='{classes[i]}'" if classes and classes[i] else ""
        out += f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
    return out + "</table>"


def post_card(post):
    if post.card_svg:
        visual = svg_img(post.card_svg, "card")
    elif post.photos:
        n = len(post.photos)
        visual = "<div class='album'>" + "".join(svg_img(photo_placeholder(i + 1, n)) for i in range(n)) + "</div>"
    else:
        visual = f"<div class='textcard'>{escape(post.caption)}</div>"
    when = f" | slot {post.slot:%H:%M}" if post.slot else ""
    chans = ""
    for ch, st in post.channel_state.items():
        link = f" <a href='{escape(st['link'])}'>link</a>" if st.get("link") else ""
        label = "created hidden" if ch == "oa" and st["status"] == "posted" else st["status"]
        chans += (f"<div class='ch'><b>{escape(ch)}</b> {badge(label)}{link}"
                  + (f" <span class='sub'>{escape(st['detail'])}</span>" if st.get("detail") else "") + "</div>")
    flags = "".join(f"<div class='flagtxt'>&#9888; {escape(f)}</div>" for f in post.flags)
    comment = f"<div class='comment'>{escape(post.comment)}</div>" if post.comment else ""
    return (f"<div class='post'>{visual}<div style='margin-top:6px'><b>{escape(post.id)}</b> {badge(post.status)} "
            f"<span class='sub'>{escape(post.fmt)}{when}</span></div><div class='cap'>{escape(post.caption)}</div>"
            f"{comment}{chans}{flags}</div>")


def render(day):
    state, trace = day.state, day.trace
    ideas = list(state.ideas.values())
    count = lambda s: sum(1 for i in ideas if i.status == s)
    posts = list(state.posts.values())
    out = [f"<h1>Content pipeline board: {day.day:%a %d %b %Y}</h1>",
           f"<div class='sub'>AI mode: {escape(day.mode)} | {len(state.ledger)} keys in the ledger | messaging "
           f"articles this month: {state.oa_used}/{state.oa_quota}. All sources, pages and posts are fictional.</div>",
           "<div class='tiles'>" + tile(len(ideas), "ideas collected") + tile(count("filtered"), "off-topic (AI)")
           + tile(count("rejected"), "rejected at Gate 1") + tile(count("needs_source"), "need source text")
           + tile(count("pending"), "waiting for Gate 1") + tile(len(posts), "drafts written")
           + tile(sum(1 for p in posts if p.status == "published"), "published")
           + tile(sum(1 for p in posts for c, s in p.channel_state.items() if s["status"] == "waiting"), "channels waiting")
           + "</div>"]

    out.append("<h2>1. Drafts and posts</h2><div class='posts'>" + "".join(post_card(p) for p in posts) + "</div>")

    out.append("<h2>2. Every idea collected today</h2>")
    rows, classes = [], []
    for i in ideas:
        last = "<br>".join(f"{escape(t)} {escape(x)}" for t, x in i.history[-3:])
        rows.append([f"<b>{escape(i.id)}</b>", f"{escape(i.kind)}<br><span class='sub'>{escape(i.source_name)}</span>",
                     escape(i.title), badge(i.status), escape(i.reason) or "-", f"<span class='sub'>{last}</span>"])
        classes.append("bad" if i.status in ("needs_source", "error") else "")
    out.append(table(["Idea", "Source", "Title", "Status", "Why / next step", "Latest events"], rows, classes))

    out.append("<h2>3. Publish log</h2>")
    out.append(table(["Time", "Post", "Channel", "Result", "Link / detail"],
                     [[t, p, c, badge(r) if r != "author comment" else escape(r),
                       f"<a href='{escape(d)}'>{escape(d)}</a>" if d.startswith("http") else escape(d)]
                      for t, p, c, r, d in state.publish_log]))

    out.append("<h2>4. Collectors</h2>")
    out.append(table(["Time", "Visit", "Source", "Items seen", "New ideas", "Note"],
                     [[f"{t:%H:%M}", v, escape(s), n, new, f"<b>{escape(note)}</b> <span class='rule'>MK-18</span>"
                       if note else ""] for t, v, s, n, new, note in state.collector_log],
                     ["bad" if note else "" for *_, note in state.collector_log]))

    out.append("<h2>5. Rule trace</h2>")
    out.append(table(["Rule", "Name", "Fired", "Examples"],
                     [[f"<span class='rule'>{rid}</span>", f"<b>{escape(name)}</b><br><span class='sub'>{escape(desc)}</span>",
                       trace.count(rid), "<br>".join(escape(x) for x in trace.examples(rid)) or "-"]
                      for rid, (name, desc) in RULES.items()]))
    out.append("<div class='foot'>Generated by marketing-pipeline-demo. Nothing was posted anywhere: platforms are "
               "simulated, and all sources, pages and texts are invented.</div>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Content board</title>"
            f"<style>{STYLE}</style></head><body>{''.join(out)}</body></html>")
