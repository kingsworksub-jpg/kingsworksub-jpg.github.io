# -*- coding: utf-8 -*-
"""
X (Twitter) への投稿。はてな/note/ameba と同じ方式: Chromium の永続プロファイルに
ログイン状態を保存し、投稿エディタへのキー入力だけをブラウザ操作で自動化する。

投稿文はこのスクリプトでは作らない(--text / --text-file で渡された文面をそのまま使う)。
ブログ公開パイプライン側(blog-post.md)が記事タイトル・リンクから文面を作って渡す。

使い方:
  python scripts/post-to-x.py --login                          初回ログイン(1回のみ、手動)
  python scripts/post-to-x.py --text-file <path>                ドライラン(投稿ボタンは押さない)
  python scripts/post-to-x.py --text-file <path> --publish      実際に投稿する
"""

import argparse
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

_URL_RE = re.compile(r"https?://\S+")


def x_weighted_len(text):
    """Xの実際の280字カウント方式を再現する。全角(CJK等)は2、半角は1として数え、
    URLはt.co圧縮により実際の長さに関わらず常に23字分として数える。"""
    text = _URL_RE.sub("x" * 23, text)
    total = 0
    for ch in text:
        cp = ord(ch)
        wide = (
            0x1100 <= cp <= 0x115F
            or 0x2E80 <= cp <= 0xA4CF
            or 0xAC00 <= cp <= 0xD7A3
            or 0xF900 <= cp <= 0xFAFF
            or 0xFF00 <= cp <= 0xFF60
            or 0xFFE0 <= cp <= 0xFFE6
            or 0x1F300 <= cp <= 0x1FAFF
            or 0x20000 <= cp <= 0x3FFFD
        )
        total += 2 if wide else 1
    return total

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(BASE, "data", "x_user_data")
LOGIN_URL = "https://x.com/login"
COMPOSE_URL = "https://x.com/compose/post"
LOGIN_TIMEOUT = 600  # 手動ログインを待つ秒数

INIT_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)


def open_browser(p):
    os.makedirs(PROFILE, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx.add_init_script(INIT_SCRIPT)
    return ctx


def is_logged_in(page):
    try:
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_selector(
            '[data-testid="SideNav_AccountSwitcher_Button"]', timeout=8000
        )
        return True
    except Exception:
        return False


def do_login(p):
    ctx = open_browser(p)
    page = ctx.new_page()
    checker = ctx.new_page()
    print("X のログインページを開きます。表示されたウィンドウで手動でログインしてください。")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"login page err: {e}")
    page.bring_to_front()

    start = time.time()
    ok = False
    while time.time() - start < LOGIN_TIMEOUT:
        time.sleep(5)
        if is_logged_in(checker):
            ok = True
            break
        print(f"  ... ログイン待機中 ({int(time.time() - start)}s)")
    if not ok:
        print("TIMEOUT: ログインを検知できませんでした。")
        ctx.close()
        sys.exit(1)
    print("ログイン完了。プロファイルを保存しました。以後 --text-file で投稿できます。")
    ctx.close()


def post_text(ctx, text, publish):
    page = ctx.new_page()
    print(f"投稿ページにアクセス: {COMPOSE_URL}")
    page.goto(COMPOSE_URL, wait_until="domcontentloaded", timeout=30000)

    box_selectors = [
        'div[data-testid="tweetTextarea_0"]',
        'div[data-testid="tweetTextarea"]',
        'div[role="textbox"]',
    ]
    box = None
    for sel in box_selectors:
        try:
            box = page.wait_for_selector(sel, timeout=8000)
            if box:
                break
        except Exception:
            continue
    if box is None:
        raise RuntimeError(
            "投稿テキストボックスが見つかりません(未ログイン、またはX側のUI変更の可能性)"
        )

    box.click()
    for i in range(0, len(text), 80):
        box.type(text[i : i + 80], delay=15)

    if not publish:
        print("--publish 未指定のためドライラン: 投稿ボタンは押さず、入力内容を確認用に10秒間表示します。")
        time.sleep(10)
        return {"posted": False}

    btn_selectors = [
        'button[data-testid="tweetButton"]',
        'button[data-testid="tweetButtonInline"]',
    ]
    btn = None
    for sel in btn_selectors:
        try:
            candidate = page.wait_for_selector(sel, timeout=8000)
            if candidate and candidate.is_enabled():
                btn = candidate
                break
        except Exception:
            continue
    if btn is None:
        raise RuntimeError("投稿ボタンが見つからない、または無効化されたままです")

    btn.click()
    page.wait_for_timeout(4000)
    return {"posted": True, "url": page.url}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", action="store_true", help="初回ログインのみ")
    parser.add_argument("--text", help="投稿する文面")
    parser.add_argument("--text-file", help="投稿する文面が書かれたファイル")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="実際に投稿ボタンを押す(指定なしはドライラン)",
    )
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    with sync_playwright() as p:
        if args.login:
            do_login(p)
            return

        text = args.text
        if args.text_file:
            with open(args.text_file, encoding="utf-8") as f:
                text = f.read().strip()
        if not text:
            print("Error: --text か --text-file のいずれかで投稿文を指定してください。")
            sys.exit(1)
        weighted = x_weighted_len(text)
        if weighted > 280:
            print(
                f"Error: Xの加重文字数が280を超えています(加重{weighted} / 生の文字数{len(text)})。"
                " 全角文字は2字分、URLはt.co圧縮で23字分として数えられるため、"
                " 日本語本文は見た目の字数より早く上限に達します。本文を短くしてください。"
            )
            sys.exit(1)

        ctx = open_browser(p)
        try:
            result = post_text(ctx, text, args.publish)
        finally:
            ctx.close()

    if result.get("posted"):
        print(f"投稿完了: {result.get('url')}")
    else:
        print("ドライラン完了(実際には投稿していません)。")


if __name__ == "__main__":
    main()
