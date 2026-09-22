"""CLI wrapper around poster.post_tweet for the recurring overseas-jazz-news
posting task. Kept as a standalone script (rather than an inline heredoc) so
Bash invocations match the pre-approved `.venv/Scripts/python.exe <script>.py`
command shape.

Usage:
    python post_jazz_tweet.py "comment text" "article url"
"""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import poster


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: post_jazz_tweet.py TEXT URL", file=sys.stderr)
        sys.exit(1)
    text, url = sys.argv[1], sys.argv[2]
    poster.post_tweet(text, url)
    print("posted")


if __name__ == "__main__":
    main()
