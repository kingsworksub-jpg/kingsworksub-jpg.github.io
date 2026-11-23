# -*- coding: utf-8 -*-
"""
X (Twitter) でブログのテーマに近そうな投稿を検索しながらいいねする、無人・継続実行のスクリプト。

post-to-x.py と同じ永続プロファイル(data/x_user_data)でログイン状態を使うため、ブラウザの
起動中はそのプロファイルを排他的に使う。blog-x-reply-task / blog-x-follow-task
(scheduled/run-x-reply.ps1 / run-x-follow-dm.ps1 経由で post-to-x.py を呼ぶ)との競合を避けるため、
run-claude-task.ps1 が使っている
のと同じ名前付きWindowsミューテックス("Local\\kingsworksub-blog-x-jobs")を1サイクルごとに
取得・解放する。取得できなければ(他のジョブが実行中)そのサイクルはスキップする。

キーワードは category-plan.json のカテゴリから人力で選んだもの(THEMES 定数、下記参照。
カテゴリを追加・変更したら THEMES も見直すこと)。Claudeを呼ばず(コスト・レート制限の都合で
1〜2分間隔にはそぐわない)、単純な「検索結果に出た=キーワードと一致」をそのまま関連度判定として使う。
広告・スパムらしき投稿は除外する。

ペース: 1サイクル(検索1回+いいね最大1件)ごとに60〜120秒のランダムな待機。経過60分ごとに
18〜22分のランダムな休憩を挟む(ユーザー指定: 「1〜2分置きかつ1時間毎に20分くらい休憩」)。
1日の上限は MAX_LIKES_PER_DAY(スパム判定を避けるための自衛的な上限、必要なら調整可)。
2026-11-19: Xの仮ラベル(リーチ制限)を受けたため 150 → 30 に引き下げ、間隔も広げた。

使い方:
  python scripts/x-auto-like.py --once                 1サイクルだけ実行(ドライラン、テスト用)
  python scripts/x-auto-like.py --once --publish        1サイクルだけ実行(実際にいいねする)
  python scripts/x-auto-like.py --loop --publish         無人で継続実行(Ctrl+Cで終了)
"""
import argparse
import ctypes
import datetime
import json
import os
import random
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(BASE, "data", "x_user_data")
STATE_PATH = os.path.join(BASE, "data", "x-likes-state.json")

INIT_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)

MUTEX_NAME = "Local\\kingsworksub-blog-x-jobs"
MUTEX_WAIT_MS = 10000  # これだけ待っても他ジョブのロックが空かなければこのサイクルは諦める

def _load_managed_limit(key: str, default: int) -> int:
    """実効上限を返す。managed-limits.json は上下両方向に調整され得るため、
    コード既定値以下という制限は外し、hard cap でクランプする（2026-11-23）。"""
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from x_automation_config import get_limit as _get_limit
        return int(_get_limit(key, default))
    except Exception:
        pass
    try:
        import json as _json
        p = os.path.join(BASE, "data", "x-consulting", "managed-limits.json")
        obj = _json.load(open(p, encoding="utf-8"))
        val = (obj.get("limits") or {}).get(key)
        if val is None:
            return default
        ival = int(val)
        if 0 <= ival:
            return ival
    except Exception:
        pass
    return default


MAX_LIKES_PER_DAY = _load_managed_limit(
    "X_MAX_LIKES_PER_DAY",
    int(os.environ.get("X_MAX_LIKES_PER_DAY", "30")),
)

CYCLE_SLEEP_RANGE = (180, 300)      # 秒。サイクル間のランダム待機
HOURLY_BREAK_AFTER = 60 * 60        # 秒。これだけ活動したら休憩を入れる
HOURLY_BREAK_RANGE = (18 * 60, 22 * 60)  # 秒。休憩の長さ

# category-plan.json の各カテゴリから人力で選んだ検索語(2026-11-06作成)。
# 内部向けカテゴリ(lab=検証メモ, notes=個人備忘録, misc=その他)は検索語として不向きなため含めない。
THEMES = [
    "ウイスキー", "ハイボール", "カクテル", "酒器", "炭酸水", "クラフトコーラ",
    "DTM", "DAW", "音楽制作", "ミキシング",
    "ジャズ", "名盤",
    "映画", "映画レビュー",
    "読書", "文学",
    "ファッション",
    "インテリア",
    "自宅サーバー", "自作PC", "周辺機器",
    "プログラミング", "Claude Code",
    "アニメ",
    "機材レビュー", "ヘッドホン", "オーディオ",
]

# ざっくりしたスパム/広告除外用のキーワード(厳密な判定ではなく、明らかなものだけ弾く)。
SPAM_MARKERS = [
    "仮想通貨", "エアドロ", "必ず儲かる", "絶対儲かる", "副業", "出会い", "LINE@", "LINE登録",
    "相互フォロー", "フォロバ100", "レベニューシェア", "today", "無料プレゼント",
]


def acquire_mutex(timeout_ms=MUTEX_WAIT_MS):
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    WAIT_OBJECT_0 = 0
    WAIT_ABANDONED = 0x80
    result = kernel32.WaitForSingleObject(handle, timeout_ms)
    if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
        return handle
    kernel32.CloseHandle(handle)
    return None


def release_mutex(handle):
    if handle:
        ctypes.windll.kernel32.ReleaseMutex(handle)
        ctypes.windll.kernel32.CloseHandle(handle)


def load_state():
    if not os.path.exists(STATE_PATH):
        return {"liked_ids": {}, "daily_counts": {}}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def today_key():
    return datetime.date.today().isoformat()


def likes_today(state):
    return state.get("daily_counts", {}).get(today_key(), 0)


def record_like(state, tweet_id):
    state.setdefault("liked_ids", {})[tweet_id] = datetime.datetime.now().isoformat(
        timespec="seconds"
    )
    day = today_key()
    state.setdefault("daily_counts", {})
    state["daily_counts"][day] = state["daily_counts"].get(day, 0) + 1
    save_state(state)


def is_spammy(text):
    return any(marker in text for marker in SPAM_MARKERS)


def open_browser(p):
    os.makedirs(PROFILE, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx.add_init_script(INIT_SCRIPT)
    return ctx


def get_own_handle(page):
    page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=15000)
    link = page.wait_for_selector('[data-testid="AppTabBar_Profile_Link"]', timeout=8000)
    href = link.get_attribute("href") or ""
    return href.strip("/").lower()


def find_likeable_tweet(page, own_handle, state):
    """検索結果ページから、いいねできそうな最初の1件を返す(見つからなければNone)。"""
    articles = page.query_selector_all('article[data-testid="tweet"]')
    for art in articles:
        try:
            like_btn = art.query_selector('[data-testid="like"]')
            if like_btn is None:
                continue  # [data-testid="unlike"] = 既にいいね済み、またはボタン無し

            name_el = art.query_selector('div[data-testid="User-Name"]')
            if name_el is None:
                continue
            # 表示名に任意の文字("@"含む)が入りうるため、inner_text()の文字列分割では
            # ハンドルを取り違える(2026-11-06実測)。User-Name内の最初のプロフィールリンクの
            # href(="/<handle>")から取るほうが確実(list_new_followersと同じ方式)。
            handle_link = name_el.query_selector('a[href^="/"]')
            href = handle_link.get_attribute("href") if handle_link else None
            if not href:
                continue
            handle = href.strip("/").split("/")[0].lower()
            if not handle or handle == own_handle:
                continue
            name_text = name_el.inner_text()

            header_lines = art.inner_text().split("\n")[:4]
            if any("広告" in line or "Promoted" in line for line in header_lines):
                continue

            link_el = art.query_selector('a:has(time)')
            href = link_el.get_attribute("href") if link_el else None
            if not href or "/status/" not in href:
                continue
            tweet_id = href.rsplit("/status/", 1)[1].split("?")[0].split("/")[0]
            if not tweet_id.isdigit() or tweet_id in state.get("liked_ids", {}):
                continue

            text_el = art.query_selector('div[data-testid="tweetText"]')
            text = text_el.inner_text() if text_el else ""
            if is_spammy(text) or is_spammy(name_text):
                continue

            return {"tweet_id": tweet_id, "handle": handle, "text": text, "button": like_btn}
        except Exception as e:
            print(f"検索結果1件の解析に失敗(無視して続行): {e}")
            continue
    return None


def run_cycle(ctx, own_handle, state, publish):
    query = random.choice(THEMES)
    url = f"https://x.com/search?q={query}&src=typed_query&f=live"
    page = ctx.new_page()
    try:
        print(f"検索: {query}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
        except Exception:
            print("  検索結果が見つかりませんでした。")
            return
        page.wait_for_timeout(1500)

        candidate = find_likeable_tweet(page, own_handle, state)
        if candidate is None:
            print("  いいね対象なし(既にいいね済み/広告/スパムらしきものを除外した結果0件)。")
            return

        print(f"  候補: @{candidate['handle']} {candidate['text'][:40]!r}")
        if not publish:
            print("  --publish 未指定のためドライラン: いいねボタンは押しません。")
            return

        candidate["button"].click()
        page.wait_for_timeout(1500)
        record_like(state, candidate["tweet_id"])
        print(f"  いいねしました(本日 {likes_today(state)}件目)。")
    finally:
        page.close()


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="1サイクルだけ実行して終了(デフォルト)")
    mode.add_argument("--loop", action="store_true", help="無人で継続実行する(Ctrl+Cで終了)")
    parser.add_argument(
        "--publish", action="store_true", help="実際にいいねする(指定なしはドライラン)"
    )
    parser.add_argument(
        "--log-file",
        help="指定すると標準出力/標準エラーをこのファイルにUTF-8で追記する"
        "(PowerShellの *>> リダイレクトはコンソールのコードページ経由でデコードされ直されるため、"
        "UTF-8で書いた日本語が壊れる。2026-11-06実測。無人実行時はこちらを使うこと)",
    )
    args = parser.parse_args()

    if args.log_file:
        log_f = open(args.log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log_f
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        except Exception:
            pass

    loop = args.loop
    window_start = time.time()

    while True:
        # レポートが更新した実効上限を毎サイクル読み直す（再起動不要）。
        try:
            from x_automation_config import get_limit as _get_limit
            global MAX_LIKES_PER_DAY
            MAX_LIKES_PER_DAY = _get_limit("X_MAX_LIKES_PER_DAY", MAX_LIKES_PER_DAY)
        except Exception:
            pass
        state = load_state()
        if likes_today(state) >= MAX_LIKES_PER_DAY:
            print(f"本日の上限({MAX_LIKES_PER_DAY}件)に達したため、本日はこれ以上いいねしません。")
        else:
            handle = acquire_mutex()
            if handle is None:
                print("他のジョブがロックを保持中のため、このサイクルはスキップします。")
            else:
                try:
                    with sync_playwright() as p:
                        ctx = open_browser(p)
                        try:
                            own_handle = get_own_handle(ctx.new_page())
                            run_cycle(ctx, own_handle, state, args.publish)
                        finally:
                            ctx.close()
                except Exception as e:
                    print(f"このサイクルでエラー(無視して続行): {e}")
                finally:
                    release_mutex(handle)

        if not loop:
            return

        if time.time() - window_start >= HOURLY_BREAK_AFTER:
            rest = random.randint(*HOURLY_BREAK_RANGE)
            print(f"1時間分活動したので {rest // 60}分{rest % 60}秒休憩します。")
            time.sleep(rest)
            window_start = time.time()
        else:
            wait = random.randint(*CYCLE_SLEEP_RANGE)
            print(f"{wait}秒待機します。")
            time.sleep(wait)


if __name__ == "__main__":
    main()
