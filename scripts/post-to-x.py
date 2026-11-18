# -*- coding: utf-8 -*-
"""
X (Twitter) への投稿、自分の投稿に来た返信への応答、新規フォロワーへのフォローバック+お礼DM。
はてな/note/ameba と同じ方式: Chromium の永続プロファイルにログイン状態を保存し、
投稿エディタへのキー入力だけをブラウザ操作で自動化する。

投稿文はこのスクリプトでは作らない(--text / --text-file で渡された文面をそのまま使う)。
新規投稿の文面はブログ公開パイプライン側(blog-post.md)が記事タイトル・リンクから作る。
返信文・お礼DM文は、従来は Claude Code タスク(prompts/x-reply.md / prompts/x-follow-dm.md)が
作っていたが、現在は x_llm.py 経由の Gemini(opencode 無料枠)がバッチ生成する。
--auto-replies / --auto-welcome は「候補取得 → LLM生成 → 返信/スキップ or フォロバ+DM」を
1プロセスで完結させるモードで、scheduled/run-x-reply.ps1 / run-x-follow-dm.ps1 から呼ばれる。

使い方:
  python scripts/post-to-x.py --login                            初回ログイン(1回のみ、手動)
  python scripts/post-to-x.py --text-file <path>                  ドライラン(投稿ボタンは押さない)
  python scripts/post-to-x.py --text-file <path> --publish        実際に投稿する
  python scripts/post-to-x.py --check-replies                     自分の投稿への新規返信をJSONで出力
  python scripts/post-to-x.py --reply-to <id> --text-file <path> --publish   その返信に返信する
  python scripts/post-to-x.py --skip <id>                         返信せず既読扱いにする(次回出てこない)
  python scripts/post-to-x.py --check-new-followers               未フォローバックの新規フォロワーをJSONで出力
  python scripts/post-to-x.py --follow-back <handle> --publish    そのユーザーをフォローバックのみする(--publish無しはドライラン)
  python scripts/post-to-x.py --send-dm <handle> --text-file <path> --publish  そのユーザーにDMを送る
  python scripts/post-to-x.py --welcome <handle> --text-file <path> --publish  フォローバック+お礼DMを一括実行
  python scripts/post-to-x.py --auto-replies [--max 5] [--publish] 新規返信をGeminiで返信/スキップ
  python scripts/post-to-x.py --auto-welcome [--max 5] [--publish] 新規フォロワーにフォロバ+お礼DM
"""

import argparse
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

import x_llm  # 返信文/お礼DM文の生成（opencode 経由の無料モデル）

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
STATE_PATH = os.path.join(BASE, "data", "x-replies-state.json")
SECRETS_PATH = os.path.join(BASE, ".secrets", "x.env")
LOGIN_URL = "https://x.com/login"
COMPOSE_URL = "https://x.com/compose/post"
NOTIFICATIONS_URL = "https://x.com/notifications/mentions"
LOGIN_TIMEOUT = 600  # 手動ログインを待つ秒数
MAX_REPLY_CANDIDATES = 20  # 1回の --check-replies で返す新規返信の上限
MAX_FOLLOWER_CANDIDATES = 20  # 1回の --check-new-followers で返す新規フォロワーの上限
MAX_FOLLOWER_SCROLLS = 6  # フォロワーリストを読み込むためスクロールする回数

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


_JS_HIT = """el => {
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return false;
  const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return !!(e && (el === e || el.contains(e)));
}"""


def _hit_testable(el):
    try:
        return bool(el.evaluate(_JS_HIT))
    except Exception:
        return False


def _first_visible(page, selectors, timeout=8, want_enabled=False):
    """Return the visible match that a click can actually reach.

    page.wait_for_selector() returns the first DOM match even when it is a
    hidden duplicate (X keeps an inline composer behind the compose modal).
    Clicking that duplicate fails with "element intercepts pointer events"
    because the modal mask covers it, which is what broke the 2026-11-16 run.
    So prefer a match whose centre is topmost, and fall back to the last
    visible one (the modal usually comes later in the DOM).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        last_visible = None
        for sel in selectors:
            try:
                for el in page.query_selector_all(sel):
                    if not el.is_visible():
                        continue
                    if want_enabled and not el.is_enabled():
                        continue
                    last_visible = el
                    if _hit_testable(el):
                        return el
            except Exception:
                continue
        if last_visible is not None:
            return last_visible
        page.wait_for_timeout(300)
    return None


def _screenshot_on_failure(page, tag):
    try:
        d = os.path.join(BASE, "scripts", "scheduled", "logs")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"x-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.png")
        page.screenshot(path=path)
        print(f"失敗時のスクリーンショット: {path}")
    except Exception as e:
        print(f"スクリーンショットの保存に失敗: {e}")


def _submit_sent(page, box, timeout=10):
    """True when the composer cleared, the URL left /compose/post, or a
    'sent' toast appeared."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if "compose/post" not in page.url:
            return True
        toast = page.query_selector('div[data-testid="toast"]')
        if toast is not None:
            try:
                txt = toast.inner_text()
            except Exception:
                txt = ""
            if "送信しました" in txt or "was sent" in txt.lower() or "posted" in txt.lower():
                return True
        if box is not None:
            try:
                if not box.is_visible() or not box.inner_text().strip():
                    return True
            except Exception:
                return True  # detached from the DOM = composer closed
        page.wait_for_timeout(400)
    return False


def _submit(page, btn, box, tag):
    """Click the send button with fallbacks, then verify it actually sent.

    Fallbacks, in order: a normal click, a DOM click (bypasses hit-testing,
    i.e. the overlay case), and X's Ctrl+Enter shortcut.  A fallback is only
    tried when the previous one raised: if a click did happen we wait for the
    confirmation instead of clicking again, so a slow send cannot be posted
    twice.
    """
    attempts = []
    try:
        btn.click(timeout=5000)
    except Exception as exc:
        attempts.append("click: " + str(exc).splitlines()[0])
    else:
        if _submit_sent(page, box, timeout=15):
            return
        _screenshot_on_failure(page, tag)
        raise RuntimeError(
            f"{tag}ボタンは押せたが、送信されたことを確認できませんでした（時間切れ）")

    try:
        btn.evaluate("el => el.click()")
        attempts.append("DOM click")
    except Exception as exc:
        attempts.append("DOM click: " + str(exc).splitlines()[0])
    else:
        if _submit_sent(page, box, timeout=15):
            return
        _screenshot_on_failure(page, tag)
        raise RuntimeError(
            f"{tag}ボタンをDOMクリックしたが、送信されたことを確認できませんでした（時間切れ）")

    try:
        box.click(timeout=2000)
        page.keyboard.press("Control+Enter")
        attempts.append("Control+Enter")
    except Exception as exc:
        attempts.append("Control+Enter: " + str(exc).splitlines()[0])
    if _submit_sent(page, box, timeout=15):
        return
    _screenshot_on_failure(page, tag)
    raise RuntimeError(f"{tag}を送信できませんでした（{' / '.join(attempts)}）")


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


def load_dm_passcode():
    """.secrets/x.env (bashの `export KEY=VALUE` 形式、gitignore対象) から
    X_DM_PASSCODE を読む。無ければ None。"""
    if not os.path.exists(SECRETS_PATH):
        return None
    with open(SECRETS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export ") :]
            if line.startswith("X_DM_PASSCODE="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def unlock_dm_passcode(page, passcode):
    """メッセージの暗号化キーを復号するための4桁パスコード画面
    (x.com/i/chat/pin/recovery) が出ていたら自動入力する。戻り値: 解除できたか。"""
    if "pin/recovery" not in page.url:
        return True
    if not passcode:
        print(
            "DMパスコード画面が出ましたが、.secrets/x.env に X_DM_PASSCODE が設定されていません。"
        )
        return False
    inputs = page.query_selector_all("input")
    if len(inputs) < len(passcode):
        print("パスコード入力欄が見つかりません(X側のUI変更の可能性)。")
        return False
    for i, ch in enumerate(passcode):
        inputs[i].fill(ch)
        page.wait_for_timeout(200)
    page.wait_for_timeout(2000)
    if "pin/recovery" in page.url:
        print("パスコードを入力しましたが解除できませんでした(パスコードが違う可能性)。")
        return False
    print("DMパスコードを解除しました。")
    return True


def load_state():
    if not os.path.exists(STATE_PATH):
        return {"handled_ids": []}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_own_handle(page):
    page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=15000)
    link = page.wait_for_selector(
        '[data-testid="AppTabBar_Profile_Link"]', timeout=8000
    )
    href = link.get_attribute("href") or ""
    return href.strip("/").lower()


def list_new_replies(ctx, state):
    """自分の投稿に来た、まだ処理していない返信を通知ページから集める。
    実際に返信するかどうかはここでは決めない(状態は変更しない)。"""
    page = ctx.new_page()
    own_handle = get_own_handle(page)
    print(f"自分のアカウント: @{own_handle}")

    page.goto(NOTIFICATIONS_URL, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
    except Exception:
        print("通知に該当するツイートが見つかりませんでした(新着なしの可能性)。")
        return []
    page.wait_for_timeout(1500)

    handled = set(state.get("handled_ids", []))
    seen_ids = set()
    results = []
    articles = page.query_selector_all('article[data-testid="tweet"]')
    for art in articles:
        try:
            link_el = art.query_selector('a:has(time)')
            href = link_el.get_attribute("href") if link_el else None
            m = re.search(r"/status/(\d+)", href or "")
            if not m:
                continue
            tweet_id = m.group(1)
            if tweet_id in seen_ids or tweet_id in handled:
                continue
            seen_ids.add(tweet_id)

            name_el = art.query_selector('div[data-testid="User-Name"]')
            name_text = name_el.inner_text() if name_el else ""
            handle_m = re.search(r"@(\w+)", name_text)
            author = handle_m.group(1).lower() if handle_m else ""
            if author == own_handle:
                continue  # 自分自身のスレッド継続は無視

            text_el = art.query_selector('div[data-testid="tweetText"]')
            text = text_el.inner_text() if text_el else ""
            if not text:
                continue  # 本文のない通知(いいね等)はスキップ

            results.append(
                {
                    "tweet_id": tweet_id,
                    "url": f"https://x.com/i/status/{tweet_id}",
                    "author": author,
                    "text": text,
                }
            )
            if len(results) >= MAX_REPLY_CANDIDATES:
                break
        except Exception as e:
            print(f"通知1件の解析に失敗(無視して続行): {e}")
            continue
    return results


def reply_to_tweet(ctx, tweet_id, text, publish):
    page = ctx.new_page()
    url = f"https://x.com/i/status/{tweet_id}"
    print(f"返信対象のツイートを開きます: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)

    box_selectors = [
        'div[data-testid="tweetTextarea_0"]',
        'div[role="textbox"]',
    ]
    box = _first_visible(page, box_selectors)
    if box is None:
        raise RuntimeError(
            "返信テキストボックスが見つかりません(ツイートが削除済み、未ログイン、またはX側のUI変更の可能性)"
        )

    box.click()
    for i in range(0, len(text), 80):
        box.type(text[i : i + 80], delay=15)
    try:
        typed = box.inner_text().strip()
    except Exception:
        typed = text
    if not typed:
        raise RuntimeError("本文が入力されませんでした（エディタが空のまま）")

    if not publish:
        print("--publish 未指定のためドライラン: 返信ボタンは押さず、入力内容を確認用に10秒間表示します。")
        time.sleep(10)
        return {"posted": False}

    btn_selectors = [
        'button[data-testid="tweetButtonInline"]',
        'button[data-testid="tweetButton"]',
    ]
    btn = _first_visible(page, btn_selectors, want_enabled=True)
    if btn is None:
        raise RuntimeError("返信ボタンが見つからない、または無効化されたままです")

    _submit(page, btn, box, "返信")
    return {"posted": True, "url": page.url}


def list_new_followers(ctx):
    """自分をフォローしているが、まだフォローバックしていないユーザーを集める。
    「フォロー」ボタン(data-testid末尾が-follow)が出ているユーザー=未フォローバック、
    という判定はXの実際の状態そのものなので、状態ファイルは使わない(フォローバックした瞬間に
    このリストから自然に消える)。"""
    page = ctx.new_page()
    own_handle = get_own_handle(page)
    print(f"自分のアカウント: @{own_handle}")

    url = f"https://x.com/{own_handle}/followers"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_selector('[data-testid="UserCell"]', timeout=10000)
    except Exception:
        print("フォロワーリストを取得できませんでした(フォロワー0人、またはページ構造の変更の可能性)。")
        return []
    page.wait_for_timeout(1000)

    results = {}
    for _ in range(MAX_FOLLOWER_SCROLLS):
        cells = page.query_selector_all('[data-testid="UserCell"]')
        for cell in cells:
            try:
                link = cell.query_selector('a[href^="/"]')
                href = link.get_attribute("href") if link else None
                if not href:
                    continue
                handle = href.strip("/").split("/")[0].lower()
                if not handle or handle == own_handle or handle in results:
                    continue
                follow_btn = cell.query_selector('[data-testid$="-follow"]')
                if follow_btn is None:
                    continue  # ボタンが無い、または既に-unfollow(フォロー済み)
                name_el = cell.query_selector('div[dir="ltr"] span')
                name = name_el.inner_text() if name_el else handle
                results[handle] = {"handle": handle, "name": name}
            except Exception as e:
                print(f"フォロワー1件の解析に失敗(無視して続行): {e}")
                continue
        if len(results) >= MAX_FOLLOWER_CANDIDATES:
            break
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1200)
    return list(results.values())[:MAX_FOLLOWER_CANDIDATES]


def follow_back(ctx, handle, publish):
    page = ctx.new_page()
    url = f"https://x.com/{handle}"
    print(f"フォロー対象のプロフィールを開きます: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        btn = page.wait_for_selector('[data-testid$="-follow"]', timeout=10000)
    except Exception:
        # 既にフォロー済みなら -unfollow ボタンが出ている。DMだけ失敗して再実行する場合に
        # ここで例外を投げるとDMまで到達できないため、フォロー済みは成功扱いにする。
        if page.query_selector('[data-testid$="-unfollow"]'):
            print("既にフォロー済みです。")
            return {"followed": True, "already": True}
        raise RuntimeError(
            "フォローボタンが見つかりません(アカウントが存在しない、"
            "またはX側のUI変更の可能性)"
        )
    if not publish:
        print("--publish 未指定のためドライラン: フォローボタンは押しません。")
        return {"followed": False}
    btn.click()
    page.wait_for_timeout(2000)
    return {"followed": True}


def send_dm(ctx, handle, text, publish):
    page = ctx.new_page()
    url = f"https://x.com/{handle}"
    print(f"DM送信のためプロフィールを開きます: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        msg_btn = page.wait_for_selector('[data-testid="sendDMFromProfile"]', timeout=8000)
    except Exception:
        print("このユーザーにはDMを送れません(DM受信を許可していない可能性)。")
        return {"sent": False, "reason": "no_dm_button"}
    msg_btn.click()
    page.wait_for_timeout(2500)

    # 会話が新しいタブで開く場合があるため、増えていればそちらを使う。
    if len(ctx.pages) > 1:
        page = ctx.pages[-1]

    if "pin/recovery" in page.url:
        if not unlock_dm_passcode(page, load_dm_passcode()):
            return {"sent": False, "reason": "passcode_locked"}
        page.wait_for_timeout(1000)

    # DMを送れない理由はいくつかパターンがあり、それぞれ別の見た目で出る(2026-11-05実測)。
    # - モーダル(div[role="dialog"])で「認証を受けて…」: 相手がDM受信を認証済みアカウントのみに制限
    # - 「受信トレイは閉じられています / Xナンバーを使用する」: 相手がXナンバー限定にしている
    # どちらも相手側の設定であり、こちら側では解決できないので、コンポーズ欄を探す前に検出して
    # 「送れないだけ」として穏当に終わらせる(RuntimeErrorにはしない)。
    #
    # 2026-11-10実測: この会話ビューは「メッセージ」ボタンを押してから数秒遅れて表示されるため、
    # 2.5秒待ちの時点ではまだ閉じられておらず、その後に本文エリアのテキストが現れて
    # 別の textarea を掴んでしまい、入力中に要素が外れて失敗していた。コンポーズ欄と
    # 「閉じられています」の両方を、最大12秒ポーリングして同時に判定する。

    def _closed_inbox(page):
        # page.inner_text("body") はこの画面のメッセージを拾えない(実測)ため get_by_text で探す。
        return page.get_by_text("受信トレイは閉じられています", exact=False).count() > 0

    def _dismiss_closed_inbox(page):
        dismiss_btn = page.get_by_role("button", name="今はしない")
        if dismiss_btn.count() > 0:
            try:
                dismiss_btn.first.click()
            except Exception:
                pass

    box = None
    deadline = time.time() + 12
    while time.time() < deadline:
        dialog = page.query_selector('div[role="dialog"]')
        if dialog and "認証" in dialog.inner_text():
            print("このユーザーには送れません(相手がDM受信を認証済みアカウントのみに制限しています)。")
            close_btn = dialog.query_selector(
                'button:has-text("いいえ")'
            ) or dialog.query_selector('button[aria-label]')
            if close_btn:
                close_btn.click()
            return {"sent": False, "reason": "recipient_requires_verified_sender"}

        if _closed_inbox(page):
            print("このユーザーには送れません(相手がDM受信をXナンバー限定にしています)。")
            _dismiss_closed_inbox(page)
            return {"sent": False, "reason": "recipient_inbox_closed"}

        box = page.query_selector('textarea[data-testid="dm-composer-textarea"]')
        if box is not None and box.is_visible():
            break
        page.wait_for_timeout(500)

    if box is None or not box.is_visible():
        if _closed_inbox(page):
            print("このユーザーには送れません(相手がDM受信をXナンバー限定にしています)。")
            _dismiss_closed_inbox(page)
            return {"sent": False, "reason": "recipient_inbox_closed"}
        print("DM入力欄が見つかりません(DMを開始できない設定の可能性)。")
        return {"sent": False, "reason": "no_composer"}

    # ElementHandle.type は入力中に要素が再描画されると
    # "Element is not attached to the DOM" で落ちるため、一度フォーカスして
    # キーボード入力に切り替える(2026-11-10)。
    box.click()
    page.wait_for_timeout(400)
    page.keyboard.type(text, delay=20)

    if not publish:
        print("--publish 未指定のためドライラン: 送信ボタンは押さず、入力内容を確認用に10秒間表示します。")
        time.sleep(10)
        return {"sent": False}

    btn = None
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            candidate = page.query_selector('button[data-testid="dm-composer-send-button"]')
            if candidate is not None and candidate.is_visible() and candidate.is_enabled():
                btn = candidate
                break
        except Exception:
            pass
        page.wait_for_timeout(400)
    if btn is None:
        print("DM送信ボタンが見つかりません(入力が空のまま、またはX側のUI変更の可能性)。")
        return {"sent": False, "reason": "no_send_button"}
    try:
        btn.click()
    except Exception:
        # 再描画された場合は座標クリックで再試行する。
        bb = btn.bounding_box()
        if not bb:
            return {"sent": False, "reason": "send_button_detached"}
        page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
    page.wait_for_timeout(3000)
    return {"sent": True}


def post_text(ctx, text, publish):
    page = ctx.new_page()
    print(f"投稿ページにアクセス: {COMPOSE_URL}")
    page.goto(COMPOSE_URL, wait_until="domcontentloaded", timeout=30000)

    box_selectors = [
        'div[data-testid="tweetTextarea_0"]',
        'div[data-testid="tweetTextarea"]',
        'div[role="textbox"]',
    ]
    box = _first_visible(page, box_selectors)
    if box is None:
        raise RuntimeError(
            "投稿テキストボックスが見つかりません(未ログイン、またはX側のUI変更の可能性)"
        )

    box.click()
    for i in range(0, len(text), 80):
        box.type(text[i : i + 80], delay=15)
    try:
        typed = box.inner_text().strip()
    except Exception:
        typed = text
    if not typed:
        raise RuntimeError("本文が入力されませんでした（エディタが空のまま）")

    if not publish:
        print("--publish 未指定のためドライラン: 投稿ボタンは押さず、入力内容を確認用に10秒間表示します。")
        time.sleep(10)
        return {"posted": False}

    btn_selectors = [
        'button[data-testid="tweetButton"]',
        'button[data-testid="tweetButtonInline"]',
    ]
    btn = _first_visible(page, btn_selectors, want_enabled=True)
    if btn is None:
        raise RuntimeError("投稿ボタンが見つからない、または無効化されたままです")

    _submit(page, btn, box, "投稿")
    return {"posted": True, "url": page.url}


def _resolve_text(args, flag_desc):
    text = args.text
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            text = f.read().strip()
    if not text:
        print(f"Error: {flag_desc} は --text か --text-file で文面を指定してください。")
        sys.exit(1)
    weighted = x_weighted_len(text)
    if weighted > 280:
        print(
            f"Error: Xの加重文字数が280を超えています(加重{weighted} / 生の文字数{len(text)})。"
            " 全角文字は2字分、URLはt.co圧縮で23字分として数えられるため、"
            " 日本語本文は見た目の字数より早く上限に達します。本文を短くしてください。"
        )
        sys.exit(1)
    return text


def _retry_collect(label, fn, attempts=2):
    """Xのページ読み込みが時々タイムアウトするため、候補取得だけ再試行する。"""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            print(f"[!] {label}の取得失敗 ({attempt}/{attempts}): {exc}")
            if attempt == attempts:
                raise
    return []


def _lookup_keyed(mapping, key):
    """LLM出力のキーは大文字小文字が揺れることがあるため、緩やかに照合する。"""
    if key in mapping:
        return mapping[key]
    lowered = str(key).lower()
    for k, v in mapping.items():
        if str(k).lower() == lowered:
            return v
    return None


def _is_declined(declined, key):
    """x_llm が返す「スキップと判断した id の集合」を大文字小文字を無視して照合する。

    2026-11-18: x_llm.generate_* の第3戻り値は dict ではなく set になったため、
    dict 前提の _lookup_keyed() に渡すと AttributeError でジョブ全体が落ちていた。
    """
    lowered = str(key).lower()
    return any(str(k).lower() == lowered for k in declined)


def _mark_handled(tweet_id, publish):
    """返信済み/スキップを状態ファイルに記録する。ドライランでは状態を触らない。"""
    if not publish:
        return False
    state = load_state()
    if tweet_id not in state["handled_ids"]:
        state["handled_ids"].append(tweet_id)
    save_state(state)
    return True


def run_auto_replies(p, publish, max_items):
    """新規返信の取得→Gemini生成→返信/スキップを1プロセスで行う。"""
    state = load_state()
    ctx = open_browser(p)
    try:
        replies = _retry_collect("新規返信", lambda: list_new_replies(ctx, state))
    finally:
        ctx.close()

    if not replies:
        print("[i] 未処理の新規返信はありません。")
        return

    # 古い方から優先（通知一覧は新しいものが先に並ぶため末尾を取る）。
    batch = replies[-max_items:]
    print(f"[*] {len(batch)}件の返信文を生成します。")
    texts, log, declined = x_llm.generate_mention_replies([
        {"id": it["tweet_id"], "author": it["author"], "text": it["text"]}
        for it in batch
    ])
    for line in log:
        print("    " + line)
    if not texts and not declined:
        print("[!] 返信文を生成できませんでした。状態は変更せず次回に委譲します。")
        return

    posted = skipped = failed = 0
    ctx = open_browser(p)
    try:
        for it in batch:
            tweet_id = it["tweet_id"]
            if _is_declined(declined, tweet_id):
                print(f"[i] {tweet_id}: スパム/無回答と判断したためスキップします。")
                _mark_handled(tweet_id, publish)
                skipped += 1
                continue
            text = _lookup_keyed(texts, tweet_id)
            if not text:
                print(f"[!] {tweet_id}: 生成結果が無いため次回に委譲します。")
                failed += 1
                continue
            weighted = x_weighted_len(text)
            if weighted > 280:
                print(f"[!] {tweet_id}: 生成文が加重{weighted}字で上限超えのため投稿しません。")
                failed += 1
                continue
            try:
                result = reply_to_tweet(ctx, tweet_id, text, publish)
            except Exception as exc:
                print(f"[!] {tweet_id} への返信に失敗しました: {exc}")
                failed += 1
                continue
            if result.get("posted"):
                _mark_handled(tweet_id, publish)
                print(f"[✓] {tweet_id} に返信しました。")
                posted += 1
            else:
                print(f"[i] {tweet_id}: ドライランのため返信しませんでした。")
    finally:
        ctx.close()
    print(f"[done] 返信: {posted}件 / スキップ: {skipped}件 / 見送り: {failed}件")


def run_auto_welcome(p, publish, max_items):
    """新規フォロワーの取得→Gemini生成→フォロバ+お礼DMを1プロセスで行う。"""
    ctx = open_browser(p)
    try:
        followers = _retry_collect("新規フォロワー", lambda: list_new_followers(ctx))
    finally:
        ctx.close()

    if not followers:
        print("[i] 未フォローバックの新規フォロワーはありません。")
        return

    batch = followers[:max_items]
    print(f"[*] {len(batch)}人分のお礼DM文を生成します。")
    texts, log, declined = x_llm.generate_welcome_dms([
        {"handle": it["handle"], "name": it.get("name") or it["handle"]}
        for it in batch
    ])
    for line in log:
        print("    " + line)
    if not texts and not declined:
        print("[!] DM文を生成できませんでした。フォロー/DMは行わず次回に委譲します。")
        return

    welcomed = skipped = failed = 0
    ctx = open_browser(p)
    try:
        for it in batch:
            handle = it["handle"]
            if _is_declined(declined, handle):
                print(f"[i] @{handle}: スパム/ボットと判断したためスキップします。")
                skipped += 1
                continue
            text = _lookup_keyed(texts, handle)
            if not text:
                print(f"[!] @{handle}: 生成結果が無いため次回に委譲します。")
                failed += 1
                continue
            weighted = x_weighted_len(text)
            if weighted > 280:
                print(f"[!] @{handle}: 生成文が加重{weighted}字で上限超えのため送信しません。")
                failed += 1
                continue
            try:
                follow_result = follow_back(ctx, handle, publish)
                dm_result = send_dm(ctx, handle, text, publish)
            except Exception as exc:
                print(f"[!] @{handle} のフォロバ/DMに失敗しました: {exc}")
                failed += 1
                continue
            if follow_result.get("followed"):
                print(f"[✓] @{handle} をフォローバックしました。")
            if dm_result.get("sent"):
                print(f"[✓] @{handle} へのDM送信完了。")
                welcomed += 1
            elif dm_result.get("reason"):
                # 相手側のDM受信設定で送れないだけ。フォロバ自体は成立しているため成功扱い。
                print(f"[i] @{handle}: DMは送れませんでした({dm_result['reason']})。")
                welcomed += 1
            else:
                print(f"[i] @{handle}: ドライランのためDMは送信しませんでした。")
    finally:
        ctx.close()
    print(f"[done] フォロバ+DM: {welcomed}件 / スキップ: {skipped}件 / 見送り: {failed}件")


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
    parser.add_argument(
        "--check-replies",
        action="store_true",
        help="自分の投稿への新規返信(未処理分)をJSONで標準出力に出す。状態は変更しない",
    )
    parser.add_argument(
        "--reply-to",
        help="返信先ツイートのID(数値)。--text/--text-file と組み合わせて使う",
    )
    parser.add_argument(
        "--skip",
        help="指定したツイートIDを、返信せずに処理済み扱いにする(次回 --check-replies に出てこない)",
    )
    parser.add_argument(
        "--check-new-followers",
        action="store_true",
        help="自分をフォローしていてまだフォローバックしていないユーザーをJSONで標準出力に出す",
    )
    parser.add_argument(
        "--follow-back",
        help="指定したハンドルをフォローバックする(DMは送らない)",
    )
    parser.add_argument(
        "--send-dm",
        help="指定したハンドルにDMを送る。--text/--text-file と組み合わせて使う",
    )
    parser.add_argument(
        "--welcome",
        help="指定したハンドルをフォローバックし、続けてお礼のDMを送る(--follow-back + --send-dm)。"
        " --text/--text-file と組み合わせて使う",
    )
    parser.add_argument(
        "--auto-replies",
        action="store_true",
        help="新規返信を取得し、Geminiが返信文/スキップを判断して実行する(Claude Code は使わない)",
    )
    parser.add_argument(
        "--auto-welcome",
        action="store_true",
        help="新規フォロワーを取得し、Geminiがお礼DM文を作ってフォロバ+DMする(Claude Code は使わない)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=5,
        help="--auto-replies / --auto-welcome で1回に処理する最大件数(既定5)",
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

        if args.auto_replies:
            run_auto_replies(p, args.publish, max(1, args.max))
            return

        if args.auto_welcome:
            run_auto_welcome(p, args.publish, max(1, args.max))
            return

        if args.skip:
            state = load_state()
            if args.skip not in state["handled_ids"]:
                state["handled_ids"].append(args.skip)
            save_state(state)
            print(f"{args.skip} を既読(処理済み)扱いにしました。")
            return

        if args.check_replies:
            ctx = open_browser(p)
            try:
                state = load_state()
                replies = list_new_replies(ctx, state)
            finally:
                ctx.close()
            print(json.dumps(replies, ensure_ascii=False, indent=2))
            return

        if args.check_new_followers:
            ctx = open_browser(p)
            try:
                followers = list_new_followers(ctx)
            finally:
                ctx.close()
            print(json.dumps(followers, ensure_ascii=False, indent=2))
            return

        if args.welcome:
            text = _resolve_text(args, "--welcome")
            ctx = open_browser(p)
            try:
                follow_result = follow_back(ctx, args.welcome, args.publish)
                dm_result = send_dm(ctx, args.welcome, text, args.publish)
            finally:
                ctx.close()
            if follow_result.get("followed"):
                print(f"@{args.welcome} をフォローバックしました。")
            if dm_result.get("sent"):
                print(f"@{args.welcome} へのDM送信完了。")
            elif args.publish:
                print(f"@{args.welcome} へのDM送信はできませんでした({dm_result.get('reason', 'unknown')})。")
            else:
                print("ドライラン完了(DMは送信していません)。")
            return

        if args.follow_back:
            ctx = open_browser(p)
            try:
                result = follow_back(ctx, args.follow_back, args.publish)
            finally:
                ctx.close()
            if result.get("followed"):
                print(f"@{args.follow_back} をフォローバックしました。")
            elif args.publish:
                print(f"@{args.follow_back} のフォローに失敗しました。")
            else:
                print("ドライラン完了(実際にはフォローしていません)。")
            return

        if args.send_dm:
            text = _resolve_text(args, "--send-dm")
            ctx = open_browser(p)
            try:
                result = send_dm(ctx, args.send_dm, text, args.publish)
            finally:
                ctx.close()
            if result.get("sent"):
                print(f"@{args.send_dm} へのDM送信完了。")
            elif args.publish:
                print(f"@{args.send_dm} へのDM送信はできませんでした({result.get('reason', 'unknown')})。")
            else:
                print("ドライラン完了(実際には送信していません)。")
            return

        text = _resolve_text(args, "--text/--text-file")
        ctx = open_browser(p)
        try:
            if args.reply_to:
                result = reply_to_tweet(ctx, args.reply_to, text, args.publish)
            else:
                result = post_text(ctx, text, args.publish)
        finally:
            ctx.close()

    if result.get("posted"):
        if args.reply_to:
            state = load_state()
            if args.reply_to not in state["handled_ids"]:
                state["handled_ids"].append(args.reply_to)
            save_state(state)
            print(f"返信完了: {result.get('url')}")
        else:
            print(f"投稿完了: {result.get('url')}")
    else:
        print("ドライラン完了(実際には投稿していません)。")


if __name__ == "__main__":
    main()
