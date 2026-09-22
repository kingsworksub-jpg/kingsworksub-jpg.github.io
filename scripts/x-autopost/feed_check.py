"""Poll the Hatena RSS feed and register any new entries in the DB."""

from __future__ import annotations

import sys

import feedparser

import db

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

FEED_URL = "https://kinbro.hatenablog.com/rss"


def check_feed() -> int:
    """Fetch the feed and insert any not-yet-seen items as 'detected'. Returns count inserted."""
    parsed = feedparser.parse(FEED_URL)
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"Failed to parse feed {FEED_URL}: {parsed.bozo_exception}")

    inserted = 0
    with db.connect() as conn:
        for entry in parsed.entries:
            guid = entry.get("id") or entry.get("link")
            url = entry.get("link")
            title = entry.get("title", "")
            if not guid or not url:
                continue
            if db.insert_detected(conn, guid, url, title):
                inserted += 1
                print(f"[feed_check] new article detected: {title} ({url})")
    return inserted


if __name__ == "__main__":
    db.init_db()
    n = check_feed()
    print(f"[feed_check] {n} new article(s) detected")
