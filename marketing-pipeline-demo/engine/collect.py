"""Step 1: collect ideas from three kinds of sources and write the new ones to the board.

  social posts   fixtures/sources/visitN/social_posts.json   (page, text, link, reactions, photos)
  videos         fixtures/sources/visitN/videos.json         (channel, title, transcript, views)
  news feeds     fixtures/sources/visitN/*.xml               (RSS 2.0: title, link, pubDate, description)

For each item, in order:
  1. threshold (MK-01): enough reactions or views; news not older than 24 hours
  2. content key (MK-02): already in the ledger? then it is a repeat, skip it
  3. write it to the board as a new idea, and its key to the ledger

And per source (MK-18): a source that returns zero items is reported as a broken
collector. "No news today" is almost never true for a busy news site; an empty
answer usually means a changed page, an expired login or a blocked request.

In production, each source type has its own scheduled collector (a browser with
a saved login for social pages, a video tool for channels, RSS and page readers
for news). Here they read recorded files.
"""
import json
import xml.etree.ElementTree as ET
from datetime import timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from engine.ledger import news_key, social_key, video_key
from engine.models import Idea

MIN_REACTIONS = 25
MIN_VIEWS = 1000
NEWS_MAX_AGE = timedelta(hours=24)


def _add(state, kind, source, title, text, link, key, when, published=None, photos=None):
    idea = Idea(state.new_idea_id(), kind, source, title, text, link, key, published, photos or [])
    idea.note(when, f"collected from {source}")
    state.ideas[idea.id] = idea
    state.ledger.add(key)
    return idea


def collect_social(path, state, now, trace, log):
    posts = json.loads(Path(path).read_text(encoding="utf-8"))["posts"]
    new, low, repeat = [], 0, 0
    for p in posts:
        if p["reactions"] < MIN_REACTIONS:
            low += 1
            trace.hit("MK-01", f"social post on {p['page']}: {p['reactions']} reactions < {MIN_REACTIONS}")
            continue
        key = social_key(p["page"], p["text"], p["link"])
        if key in state.ledger:
            repeat += 1
            trace.hit("MK-02", f"{p['page']}: new link {p['link'][-22:]}, same content key -> repeat")
            continue
        title = p["text"].split(". ")[0][:90]
        new.append(_add(state, "social", p["page"], title, p["text"], p["link"], key, now, photos=p.get("photos")))
    log.append(f"    social posts   {len(posts)} seen -> {len(new)} new, {low} below {MIN_REACTIONS} reactions [MK-01], "
               f"{repeat} already in the ledger (link changed, content key matched) [MK-02]")
    return new, len(posts)


def collect_videos(path, state, now, trace, log):
    videos = json.loads(Path(path).read_text(encoding="utf-8"))["videos"]
    new, low, repeat = [], 0, 0
    for v in videos:
        if v["views"] < MIN_VIEWS:
            low += 1
            trace.hit("MK-01", f"video '{v['title']}': {v['views']:,} views < {MIN_VIEWS:,}")
            continue
        key = video_key(v["id"])
        if key in state.ledger:
            repeat += 1
            trace.hit("MK-02", f"video {v['id']}: already in the ledger")
            continue
        new.append(_add(state, "video", v["channel"], v["title"], v["transcript"], v["link"], key, now,
                        parsedate_to_datetime(v["uploaded"])))
    log.append(f"    videos         {len(videos)} seen -> {len(new)} new, {low} below {MIN_VIEWS:,} views [MK-01], "
               f"{repeat} already in the ledger [MK-02]")
    return new, len(videos)


def collect_feed(path, state, now, trace, log):
    channel = ET.parse(path).getroot().find("channel")
    source = channel.findtext("title")
    items = channel.findall("item")
    new, old, repeat = [], 0, 0
    for item in items:
        published = parsedate_to_datetime(item.findtext("pubDate"))
        if now - published.replace(tzinfo=None) > NEWS_MAX_AGE:
            old += 1
            trace.hit("MK-01", f"{source}: '{item.findtext('title')[:40]}...' older than 24 h")
            continue
        key = news_key(item.findtext("link"))
        if key in state.ledger:
            repeat += 1
            trace.hit("MK-02", f"{source}: same article, link with tracking parameters -> repeat")
            continue
        new.append(_add(state, "news", source, item.findtext("title"), item.findtext("description").strip(),
                        item.findtext("link"), key, now, published.replace(tzinfo=None)))
    if not items:
        trace.hit("MK-18", f"{source}: 0 items")
        log.append(f"    news           {source}: 0 items -> COLLECTOR PROBLEM: a source that returns nothing is "
                   f"treated as broken, not as 'no news today' [MK-18]")
    else:
        log.append(f"    news           {source}: {len(items)} items -> {len(new)} new, {old} older than 24 h [MK-01], "
                   f"{repeat} already in the ledger [MK-02]")
    return new, len(items), source


def collect_all(source_dir, visit, state, now, trace, log):
    """Run every collector for one visit. Returns the list of new ideas."""
    log.append(f"  COLLECT (visit {visit})")
    folder = Path(source_dir) / f"visit{visit}"
    new = []
    got, seen = collect_social(folder / "social_posts.json", state, now, trace, log)
    new += got
    state.collector_log.append((now, visit, "social posts", seen, len(got), ""))
    got, seen = collect_videos(folder / "videos.json", state, now, trace, log)
    new += got
    state.collector_log.append((now, visit, "videos", seen, len(got), ""))
    for feed in sorted(folder.glob("*.xml")):
        got, seen, name = collect_feed(feed, state, now, trace, log)
        new += got
        state.collector_log.append((now, visit, name, seen, len(got), "BROKEN? returned nothing" if seen == 0 else ""))
    log.append(f"    {len(new)} new idea(s) on the board; ledger now holds {len(state.ledger)} keys")
    return new
