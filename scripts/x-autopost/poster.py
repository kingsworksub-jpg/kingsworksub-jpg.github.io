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
CLOSE_TAB_WAIT_S = 1


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

    # Each post_tweet() call opens a fresh compose tab (subprocess.Popen above
    # forwards the URL to the already-running Edge instance rather than
    # spawning a new browser process). Left unclosed, these accumulate one
    # tab per post -- with the hourly/every-2-hours cron jobs this adds up
    # fast and eats memory. Close the tab now that the post is submitted.
    # Re-check focus first (same safety rule as above): only send Ctrl+W if
    # Edge is still confirmed focused, so a stray window never eats a
    # close-tab keystroke meant for the compose tab.
    active = gw.getActiveWindow()
    if active is not None and "Edge" in (active.title or ""):
        pyautogui.hotkey("ctrl", "w")
        time.sleep(CLOSE_TAB_WAIT_S)
    else:
        print(
            "Warning: Edge no longer confirmed focused after posting; "
            "skipping tab close to avoid sending Ctrl+W to the wrong window. "
            "The compose tab may be left open.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python poster.py <text> <url>")
        raise SystemExit(1)
    post_tweet(sys.argv[1], sys.argv[2])
    print("Posted (check x.com to confirm -- this script does not capture the tweet URL/id).")
