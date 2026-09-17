"""Orchestrator for the Hatena -> X auto-post pipeline.

Run this periodically (Task Scheduler, cron, etc.). Each run:
  1. Polls the RSS feed and records any new articles (status='detected').
  2. Scrapes the full body of 'detected' articles via Playwright.
  3. Asks Claude Code (haiku, structured output) to summarize + draft 3 tweet
     candidates + pick the best one.
  4. Posts the chosen text + article URL to X.
  5. Records the result (or the error) in SQLite at every step, so a failed
     run can be re-run later without reprocessing or double-posting.
"""

from __future__ import annotations

import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import db
import feed_check
import generate
import poster
import scraper


def process_detected(conn) -> None:
    for row in db.fetch_by_status(conn, "detected"):
        print(f"[main] scraping #{row['id']}: {row['title']}")
        try:
            body = scraper.fetch_article_body(row["url"])
            if not body:
                raise RuntimeError("scraped body was empty")
            db.mark_scraped(conn, row["id"], body)
        except Exception as e:  # noqa: BLE001 - want to record any failure and keep going
            print(f"[main] scrape failed for #{row['id']}: {e}", file=sys.stderr)
            db.mark_error(conn, row["id"], f"scrape error: {e}\n{traceback.format_exc()}")


def process_scraped(conn) -> None:
    for row in db.fetch_by_status(conn, "scraped"):
        print(f"[main] generating tweet text for #{row['id']}: {row['title']}")
        try:
            result = generate.generate(row["title"], row["body_text"])
            db.mark_generated(
                conn, row["id"], result["summary"], result["candidates"], result["chosen_index"]
            )
        except Exception as e:  # noqa: BLE001
            print(f"[main] generation failed for #{row['id']}: {e}", file=sys.stderr)
            db.mark_error(conn, row["id"], f"generation error: {e}\n{traceback.format_exc()}")


def process_generated(conn) -> None:
    for row in db.fetch_by_status(conn, "generated"):
        print(f"[main] posting #{row['id']}: {row['title']}")
        try:
            poster.post_tweet(row["chosen_text"], row["url"])
            db.mark_posted(conn, row["id"])
            print(f"[main] posted #{row['id']} (check x.com to confirm)")
        except Exception as e:  # noqa: BLE001
            print(f"[main] posting failed for #{row['id']}: {e}", file=sys.stderr)
            db.mark_error(conn, row["id"], f"post error: {e}\n{traceback.format_exc()}")


def main() -> None:
    db.init_db()

    n_new = feed_check.check_feed()
    print(f"[main] {n_new} new article(s) detected")

    with db.connect() as conn:
        process_detected(conn)
    with db.connect() as conn:
        process_scraped(conn)
    with db.connect() as conn:
        process_generated(conn)


if __name__ == "__main__":
    main()
