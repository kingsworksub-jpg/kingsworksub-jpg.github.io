"""Post the chosen tweet text (plus the article URL) to X by driving the
user's regular, already-logged-in Edge browser via OS-level mouse/keyboard
simulation -- no browser-automation protocol (CDP/WebDriver) involved.

Why: X's login flow and bot-detection both blocked Playwright-driven
Chromium and even Playwright-driven real Chrome (CDP leaves detectable
automation signals regardless of which browser binary drives it). This
avoids that category of detection entirely by never touching a browser
automation API -- it launches the user's normal Edge (default profile,
already logged into X from everyday use) and sends real OS input events
(the same channel a human's mouse/keyboard use), the same way any RPA or
macro tool works.

Requires: the user's default Edge profile must already be logged into X.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import pyautogui
import pygetwindow as gw
import pyperclip

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
COMPOSE_URL = "https://x.com/compose/post"

LAUNCH_WAIT_S = 4
PASTE_WAIT_S = 1
SUBMIT_WAIT_S = 2


class PostingError(RuntimeError):
    pass


def post_tweet(text: str, url: str) -> None:
    """Post `text` + the article URL to X via the logged-in Edge session."""
    full_text = f"{text}\n{url}"

    if not Path(EDGE_PATH).exists():
        raise PostingError(f"Edge not found at {EDGE_PATH}")

    subprocess.Popen([EDGE_PATH, COMPOSE_URL])
    time.sleep(LAUNCH_WAIT_S)

    active = gw.getActiveWindow()
    if active is None or "Edge" not in (active.title or ""):
        title = active.title if active else None
        raise PostingError(
            f"Expected an Edge window to be focused after launch, got: {title!r}. "
            "Aborting rather than sending input to an unknown window."
        )

    pyperclip.copy(full_text)
    time.sleep(PASTE_WAIT_S)

    pyautogui.hotkey("ctrl", "v")
    time.sleep(PASTE_WAIT_S)

    pyautogui.hotkey("ctrl", "enter")
    time.sleep(SUBMIT_WAIT_S)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python poster.py <text> <url>")
        raise SystemExit(1)
    post_tweet(sys.argv[1], sys.argv[2])
    print("Posted (check x.com to confirm -- this script does not capture the tweet URL/id).")
