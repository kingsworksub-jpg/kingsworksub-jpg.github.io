"""Post the chosen tweet text (plus the article URL) to X via API v2 (tweepy).

Requires OAuth 1.0a User Context credentials with Read+Write permission,
generated in the X Developer Portal: API Key/Secret + Access Token/Secret
(NOT just a Bearer token -- app-only auth cannot post on a user's behalf).
"""

from __future__ import annotations

import os
import sys

import tweepy
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".secrets", "x-api.env")


def _client() -> tweepy.Client:
    load_dotenv(_ENV_PATH)
    required = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing X API credentials in {_ENV_PATH}: {', '.join(missing)}. "
            "See scripts/x-autopost/README.md for how to obtain them."
        )
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def post_tweet(text: str, url: str) -> str:
    """Post `text` + the article URL to X. Returns the new tweet's id as a string."""
    client = _client()
    full_text = f"{text}\n{url}"
    response = client.create_tweet(text=full_text)
    return str(response.data["id"])


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python poster.py <text> <url>")
        raise SystemExit(1)
    tweet_id = post_tweet(sys.argv[1], sys.argv[2])
    print(f"Posted: https://x.com/i/web/status/{tweet_id}")
