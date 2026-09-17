"""One-time setup helper: mark all currently-detected (pre-existing) articles
as 'skipped_baseline' so the pipeline does NOT try to tweet the entire
back-catalog the first time main.py runs.

Run this once, right after the first `feed_check.py` populates the DB with
whatever is already published, and BEFORE wiring up real X credentials /
running main.py for real. Only articles published *after* this point will
flow through scrape -> generate -> post.
"""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

import db


def seed_baseline() -> int:
    with db.connect() as conn:
        rows = db.fetch_by_status(conn, "detected")
        for row in rows:
            conn.execute(
                "UPDATE posts SET status = 'skipped_baseline' WHERE id = ?", (row["id"],)
            )
        return len(rows)


if __name__ == "__main__":
    db.init_db()
    n = seed_baseline()
    print(f"[seed_baseline] marked {n} pre-existing article(s) as skipped_baseline "
          f"(they will NOT be tweeted; only future new articles will)")
