"""SQLite state store for the Hatena -> X auto-post pipeline.

Each RSS item moves through: detected -> scraped -> generated -> posted
(or -> error at any step, recorded with error_message for manual retry).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "posts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guid          TEXT UNIQUE NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    detected_at   TEXT NOT NULL,
    body_text     TEXT,
    summary       TEXT,
    candidate_1   TEXT,
    candidate_2   TEXT,
    candidate_3   TEXT,
    chosen_index  INTEGER,
    chosen_text   TEXT,
    status        TEXT NOT NULL DEFAULT 'detected',
    tweet_id      TEXT,
    posted_at     TEXT,
    error_message TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def insert_detected(conn: sqlite3.Connection, guid: str, url: str, title: str) -> bool:
    """Insert a newly-seen RSS item. Returns True if inserted, False if it already existed."""
    try:
        conn.execute(
            "INSERT INTO posts (guid, url, title, detected_at, status) VALUES (?, ?, ?, ?, 'detected')",
            (guid, url, title, _now()),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def fetch_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM posts WHERE status = ? ORDER BY id", (status,)).fetchall()


def mark_scraped(conn: sqlite3.Connection, post_id: int, body_text: str) -> None:
    conn.execute(
        "UPDATE posts SET body_text = ?, status = 'scraped' WHERE id = ?",
        (body_text, post_id),
    )


def mark_generated(
    conn: sqlite3.Connection,
    post_id: int,
    summary: str,
    candidates: list[str],
    chosen_index: int,
) -> None:
    conn.execute(
        """UPDATE posts
           SET summary = ?, candidate_1 = ?, candidate_2 = ?, candidate_3 = ?,
               chosen_index = ?, chosen_text = ?, status = 'generated'
           WHERE id = ?""",
        (summary, candidates[0], candidates[1], candidates[2], chosen_index,
         candidates[chosen_index], post_id),
    )


def mark_posted(conn: sqlite3.Connection, post_id: int, tweet_id: str | None = None) -> None:
    # tweet_id is best-effort: browser-automation posting (poster.py) can't
    # reliably capture the resulting tweet's id/URL the way an API response
    # would, so this is usually None. Left in the schema in case a future
    # version of poster.py starts scraping the permalink after posting.
    conn.execute(
        "UPDATE posts SET tweet_id = ?, posted_at = ?, status = 'posted' WHERE id = ?",
        (tweet_id, _now(), post_id),
    )


def mark_error(conn: sqlite3.Connection, post_id: int, message: str) -> None:
    conn.execute(
        "UPDATE posts SET status = 'error', error_message = ? WHERE id = ?",
        (message, post_id),
    )


def is_known_guid(conn: sqlite3.Connection, guid: str) -> bool:
    row = conn.execute("SELECT 1 FROM posts WHERE guid = ?", (guid,)).fetchone()
    return row is not None
