# -*- coding: utf-8 -*-
"""
X (Twitter) で自分がフォローしているユーザー（Following）のタイムラインを巡回し、
新しい投稿に対してシンプルで丁寧かつ爽やかな自動返信するスクリプト。

要件:
1. 同じ投稿に連続して返信しない（状態ファイル data/x-following-reply-state.json で既読・返信済みIDを管理）。
2. 返信は「シンプルで丁寧かつ爽やかに」。相手のポストの文章をそのまま引用するのは絶対に禁止。
3. 相手のポストの内容を深く理解し、「こいつわかってるな」と思わせるような洞察や感想を返す。
   必要に応じてweb検索のスニペットを踏まえて返信文を生成する。
4. 返信文はB方式（LLMが全文生成）。モデルのフォールバックチェーンは x_llm.py:
   - メイン: opencode / google/gemini-3.5-flash-lite
   - フォールバック1: opencode / opencode/longcat-2.5-free（無料）
   - フォールバック2: claude code / haiku
5. トークン節約のため、候補ツイートを1回のLLM呼び出しにまとめる（バッチ生成）。
   opencode CLI は1回あたり約8kトークンの固定オーバーヘッドがあるため、
   1件ずつ呼ぶよりバッチの方が安い。
6. 自分の返信に相手から返信が来た場合は、それを最優先で拾い、会話の文脈
   （元の投稿 → 自分の返信 → 相手の返信）をLLMに渡して続きを返す。
   プロフィールの「返信」タブを開くため、確認は一定間隔
   （X_FOLLOWUP_INTERVAL_MIN、既定30分）で行う。
7. 実行間隔は固定にせず、日中は短め（18〜45分）・深夜は長め（80〜150分）の
   ランダムにして、1日トータルで約30〜33サイクル（深夜は4回程度）にする。
   固定間隔の機械的なパターンを避けるため。`--loop` で常駐させ、
   Windowsタスクスケジューラからは1日1回起動する（run-following-reply.ps1）。
"""

import argparse
import ctypes
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_llm  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(BASE, "data", "x_user_data")
STATE_PATH = os.path.join(BASE, "data", "x-following-reply-state.json")
# blog-x-reply-task (post-to-x.py --check-replies) と既読IDを共有するための状態ファイル。
# 通知ベースの既存ジョブと同じ相手に二重返信しないため、両方向で読み書きする。
REPLIES_STATE_PATH = os.path.join(BASE, "data", "x-replies-state.json")

INIT_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)

MUTEX_NAME = "Local\\kingsworksub-blog-x-jobs"
# 他のXジョブ（特に1〜2分間隔で回る x-auto-like）が数十秒でロックを離すことが多いので、
# すぐ諦めず少し待つ。長く待っても取れない場合はサイクルをスキップして数分後に再試行する。
MUTEX_WAIT_MS = int(float(os.environ.get("X_MUTEX_WAIT_SEC", "120")) * 1000)

MAX_REPLIES_PER_DAY = int(os.environ.get("X_MAX_REPLIES_PER_DAY", "30"))
CYCLE_SLEEP_RANGE = (120, 240)

# 1サイクルでタイムラインから読みに行く投稿の数 / まとめてLLMに投げる数 / 実際に返信する数。
# 1日に何度も回すため、1サイクルで返信するのは1件だけにして時間帯に分散させる。
SCAN_LIMIT = int(os.environ.get("X_SCAN_LIMIT", "12"))
BATCH_SIZE = int(os.environ.get("X_BATCH_SIZE", "3"))
POST_PER_CYCLE = int(os.environ.get("X_POST_PER_CYCLE", "1"))

# サイクル間隔。固定45分だと機械的なので、日中は短め・深夜は長めのランダムにする
# （1日トータルで約33サイクル、うち深夜は4回程度。他のXジョブがロックを
#  持つ時間帯は自動でスキップし、数分後に再試行する）。
DAY_INTERVAL_MIN = (18, 45)      # 07:00-22:59
NIGHT_INTERVAL_MIN = (80, 150)   # 23:00-06:59
LONG_REST_PROB = 0.08            # たまに長めに間を空ける（機械的な連続実行に見せない）

# 返信に値すると判断するための最低文字数。これ未満は文脈が取れないため返信しない。
MIN_MEANINGFUL_LEN = 18
# トピック表に無い話題でも、これ以上の長さがあればLLMが文脈を掴めるとみなして通す。
MIN_UNKNOWN_TOPIC_LEN = 40

# タイムラインを下にスクロールして追加読み込みする回数の上限。
MAX_SCROLLS = int(os.environ.get("X_MAX_SCROLLS", "6"))

# 自分の返信に付いた返信（会話の続き）を優先的に拾う設定。
# プロフィールの「返信」タブを開くので、毎サイクルではなく一定間隔で確認する。
FOLLOWUP_CHECK_INTERVAL_MIN = int(os.environ.get("X_FOLLOWUP_INTERVAL_MIN", "30"))
FOLLOWUP_SCAN_REPLIES = int(os.environ.get("X_FOLLOWUP_SCAN_REPLIES", "5"))
FOLLOWUP_MAX = int(os.environ.get("X_FOLLOWUP_MAX", "3"))
FOLLOWUP_MIN_LEN = int(os.environ.get("X_FOLLOWUP_MIN_LEN", "2"))

# 宣伝・告知は会話にならないので返信対象から外す。
PROMO_PATTERN = re.compile(
    r"チケット|前売券|当日券|ご予約は|予約受付|販売開始|発売中|配信中|"
    r"リリース記念|ニューアルバム|NEW ALBUM|出演します|出演決定|"
    r"フォロー＆リポスト|プレゼントキャンペーン|"
    r"【PR】|#PR\b|#広告|プロモーション|モニター募集|アフィリエイト",
    re.I,
)
# 日付+引用符で始まるイベント告知ヘッダの検出用。
DATE_HEADER_PATTERN = re.compile(r"\d{4}[./]\d{1,2}[/.]\d{1,2}")

# 「こいつわかってるな」と思える考察を返せるトピックの一覧。
# ここに命中しない投稿は返信候補から外す(何でもに返信しない)。
#
# 将来「分类を追加したい」場合は、この TABLE に1行足すだけでなく、
# data/x-reply-topics.json に追記することでも拡張できます(コード改変不要)。
#   {
#     "topics": [
#       {"key": "anime", "keywords": ["アニメ", "作画"], "desc": "アニメ",
#        "reply": "〜"}
#     ]
#   }
# key が TABLE と同じなら上書き、違えば新規追加されます。
TOPIC_TABLE = [
    {
        "key": "dj",
        "keywords": ["dj", "stems", "ミックス", "リミックス", "remix", "クラブ", "ミキサー", "ブート"],
        "desc": "DJ・ミックス・クラブ音楽",
        "reply": "ブートやミックスの精度がその場の空気をまるごと変えるから、技量の高さには毎回脱帽します。新しい聴き方を教わるようで楽しいです。",
    },
    {
        "key": "album_review",
        "keywords": ["名盤", "最高傑作", "傑作", "ベスト盤", "名曲", "リマスタ", "年代"],
        "desc": "名盤・傑作・アルバム解説",
        "reply": "時代を越えて残る名盤って、何度聴き直しても新しい発見があるのが本当にすごいですよね。当時の空気まで思い出されて語り甲斐があります。",
    },
    {
        "key": "dev",
        "keywords": ["プログラミング", "コード", "開発", "エンジニア", "github", "api", "python", "javascript", "vscode", "linux"],
        "desc": "ソフトウェア開発・プログラミング",
        "reply": "環境構築やメンテナンスに取られる時間が想像以上に膨らむと、肝心のコアな実装が進まなくて焦りますよね。割り切りの設計が本当に重要だと痛感します。",
    },
    {
        "key": "sleep",
        "keywords": ["睡眠", "夜更かし", "生活", "眠", "起床", "寝落ち", "寝不足"],
        "desc": "睡眠・生活リズム",
        "reply": "夜の静かな時間帯って集中できる一方で、翌日のパフォーマンスに直結するからセルフコントロールの難しさをいつも痛感させられますよね。",
    },
    {
        "key": "audio",
        "keywords": ["スピーカー", "音響", "オーディオ", "イヤホン", "ヘッドホン", "レコード", "mlac", "マイク"],
        "desc": "オーディオ・音響機材",
        "reply": "素材の鳴り方や木工の精度でここまでニュアンスが変わるのかと驚かされます。空間の響きまで想像が膨らんで面白いですね。",
    },
    {
        "key": "whisky",
        "keywords": ["ウイスキー", "酒", "ハイボール", "カクテル", "焼酎", "ワイン", "蒸留"],
        "desc": "お酒・ウイスキー",
        "reply": "樽の経年変化や原酒のブレンドによって生まれる奥行きを想像しながら飲むと、一杯あたりの満足感が全然違ってきますよね。",
    },
    {
        "key": "music",
        "keywords": ["blur", "音楽", "アルバム", "ライブ", "ジャズ", "ポップ", "バンド", "楽曲"],
        "desc": "音楽全般",
        "reply": "同じ楽曲でも再生の仕方ひとつで全く違う表情になるから、何度聴いても飽きませんよね。新しいスタイルが広がるのを感じます。",
    },
    {
        "key": "movie",
        "keywords": ["映画", "ドラマ", "アニメ", "観た", "シリーズ"],
        "desc": "映画・ドラマ・アニメ",
        "reply": "映像の密度が高い作品って、一度見終わった後も余韻が長く残りますよね。何度見ても新しい発見がありそうです。",
    },
    {
        "key": "book",
        "keywords": ["本", "読書", "小説", "書評", "文庫"],
        "desc": "本・読書",
        "reply": "読み終えた後に余韻が残る本って、手元に置いて何度も開きたくなる魅力がありますよね。次に読む作品が気になります。",
    },
    {
        "key": "fashion",
        "keywords": ["ファッション", "服", "コーデ", "スニーカー", "ジャケット", "着回し"],
        "desc": "ファッション・着こなし",
        "reply": "着回しの利く提案って、いざ着てみないと想像しにくいけど実用性が高くて助かりますよね。自分なりの組み合わせも楽しめそうです。",
    },
    {
        "key": "interior",
        "keywords": ["インテリア", "部屋", "家具", "照明", "収納"],
        "desc": "インテリア・住空間",
        "reply": "空間の使い方って住み始めてから気づくこと多いですよね。見た目の気持ちよさと日々の動線の両立が一番の難どころだと感じます。",
    },
    {
        "key": "tech",
        "keywords": ["pc", "サーバー", "ネットワーク", "wifi", "スマホ", "周辺機器"],
        "desc": "PC・サーバー・周辺機器",
        "reply": "環境を整えるだけで普段のストレスがこんなに変わるのかと驚かされます。持続的に使える形を探すバランスが難しいですよね。",
    },
]

TOPICS_OVERRIDE_PATH = os.path.join(BASE, "data", "x-reply-topics.json")

def load_topics():
    """TOPIC_TABLE をベースに、data/x-reply-topics.json の上書き・追加を反映する。
    ファイル側の定義はベースより先に評価される(明示した分类を優先するため)。"""
    try:
        with open(TOPICS_OVERRIDE_PATH, encoding="utf-8") as f:
            extra = json.load(f).get("topics", [])
    except FileNotFoundError:
        extra = []
    except Exception as e:
        print(f"[!] トピック定義ファイルの読み込みに失敗: {e}")
        extra = []

    overrides = {}
    order = []
    for item in extra:
        key = item.get("key")
        if not key:
            continue
        overrides[key] = item
        order.append(key)

    topics = []
    for key in order:
        base = next((t for t in TOPIC_TABLE if t.get("key") == key), None)
        merged = dict(base) if base else {}
        merged.update(overrides[key])
        topics.append(merged)
    for t in TOPIC_TABLE:
        if t.get("key") not in overrides:
            topics.append(dict(t))
    return topics

def _match_keyword(t, kw):
    """ASCII系キーワードは単語境界で、日本語キーワードは部分一致で判定する。
    (「api」が「アプリ」等に誤ヒットするのを防ぐため)"""
    if re.fullmatch(r"[a-z0-9]+", kw):
        return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", t) is not None
    return kw in t

def pick_topic(tweet_text):
    """ツイートのトピックを判定し、キー or None を返す。"""
    t = (tweet_text or "").lower()
    for topic in load_topics():
        if any(_match_keyword(t, k) for k in topic.get("keywords", [])):
            return topic["key"]
    return None

def topic_reply(tweet_text):
    """トピックに合った定型の返信文を返す。見つからなければ None。"""
    key = pick_topic(tweet_text)
    if key is None:
        return None
    for topic in load_topics():
        if topic.get("key") == key:
            return topic.get("reply")
    return None

def topic_desc(tweet_text):
    """トピックの説明文を返す（LLMへのヒント用）。未分類なら空文字。"""
    key = pick_topic(tweet_text)
    if key is None:
        return ""
    for topic in load_topics():
        if topic.get("key") == key:
            return topic.get("desc", "")
    return ""

def is_reply_candidate(tweet_text, author, own_handle=None):
    """返信すべき投稿かどうかを判定する。返信しない方が良い場合は (False, 理由) を返す。
    トピック表に無い話題でも、本文が十分長ければLLMが文脈を掴めるので通す。"""
    text = (tweet_text or "").strip()
    if not text:
        return False, "本文が空"
    if own_handle and author and own_handle in author.lower():
        return False, "自分の投稿"
    if len(text) < MIN_MEANINGFUL_LEN:
        return False, f"文脈が取れない短い投稿({len(text)}字)"
    if re.fullmatch(r"(https?://\S+|\S*@\w[\w.]*)+", text):
        return False, "URL/メンションのみの投稿"
    # トピック表に命中しない場合は、文脈を掴める長さがあるかだけ確認する
    if pick_topic(text) is None and len(text) < MIN_UNKNOWN_TOPIC_LEN:
        return False, f"話題が読めない短文({len(text)}字)"
    # 宣伝・告知は会話にならないので返信しない
    if PROMO_PATTERN.search(text):
        return False, "宣伝・告知の投稿"
    if DATE_HEADER_PATTERN.search(text) and ("「" in text or '"' in text):
        return False, "イベント告知っぽい投稿"
    return True, ""

def quotes_source(reply, tweet_text, min_len=6):
    """返信文が投稿本文の表現をそのままなぞっていないか（引用禁止の絶対ルール）を検査する。
    空白・記号を除いた上で、min_len 文字以上の共通部分文字列があれば True。"""
    def norm(s):
        return re.sub(r"[\s\W_]+", "", (s or "").lower())
    a, b = norm(reply), norm(tweet_text)
    if not a or not b:
        return False
    if len(a) < min_len or len(b) < min_len:
        return a and a in b
    # 動的計画法で最長共通部分文字列の長さを求める
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
                    if best >= min_len:
                        return True
        prev = cur
    return False

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
        return {"replied_ids": {}, "daily_counts": {}}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def today_key():
    return datetime.date.today().isoformat()

def replies_today(state):
    return state.get("daily_counts", {}).get(today_key(), 0)

def record_reply(state, tweet_id):
    state.setdefault("replied_ids", {})[tweet_id] = datetime.datetime.now().isoformat(
        timespec="seconds"
    )
    day = today_key()
    state.setdefault("daily_counts", {})
    state["daily_counts"][day] = state["daily_counts"].get(day, 0) + 1
    save_state(state)
    # 通知ベースの x-reply ジョブも同じ相手に返信しないよう、既読を共有する
    add_replies_state_id(tweet_id)

def mark_seen(state, tweet_id):
    """LLMが返信不要と判断した等、返信しなかった投稿を記録して再評価を防ぐ。"""
    seen = state.setdefault("seen_ids", {})
    seen[tweet_id] = datetime.datetime.now().isoformat(timespec="seconds")
    if len(seen) > 800:
        # 古いものから捨ててファイルが肥大化しないようにする
        newest = sorted(seen.items(), key=lambda kv: kv[1])[-500:]
        state["seen_ids"] = dict(newest)
    save_state(state)

# x-reply ジョブの既読IDのキャッシュ（毎サイクル先頭で読み直す）
_other_handled = None

def load_replies_state_ids(refresh=False):
    global _other_handled
    if _other_handled is None or refresh:
        try:
            with open(REPLIES_STATE_PATH, encoding="utf-8") as f:
                data = json.load(f) or {}
            _other_handled = set(data.get("handled_ids", []))
        except (OSError, json.JSONDecodeError, AttributeError):
            _other_handled = set()
    return _other_handled

def add_replies_state_id(tweet_id):
    """x-reply ジョブと既読を共有し、同じ返信への二重返信を防ぐ。"""
    state = {"handled_ids": []}
    try:
        if os.path.exists(REPLIES_STATE_PATH):
            with open(REPLIES_STATE_PATH, encoding="utf-8") as f:
                state = json.load(f) or state
        ids = state.setdefault("handled_ids", [])
        if tweet_id not in ids:
            ids.append(tweet_id)
            with open(REPLIES_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        load_replies_state_ids(refresh=True)
    except (OSError, json.JSONDecodeError):
        pass

def already_handled(state, tweet_id):
    return (tweet_id in state.get("replied_ids", {})
            or tweet_id in state.get("seen_ids", {})
            or tweet_id in load_replies_state_ids())

def simple_web_search(query):
    """簡易的な検索補助。DuckDuckGoのスニペットから背景情報の要約を取得する。
    取得に失敗した、あるいは有意な情報が取れなかった場合は空文字列を返す。"""
    try:
        encoded = urllib.parse.quote(query[:40])
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        if "result__snippet" not in html:
            return ""
        # スニペット部分を抜き出し、HTMLタグを除去して要約を作る
        import re
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
        parts = []
        for s in snippets[:3]:
            text = re.sub(r"<[^>]+>", "", s)
            text = text.replace("&quot;", '"').replace("&amp;", "&").replace("&#x27;", "'").strip()
            if text:
                parts.append(text)
        if not parts:
            return ""
        return " ".join(parts)[:600]
    except Exception:
        return ""

def generate_reply_text(author, tweet_text, context_history=None):
    """単発生成のヘルパー（バッチを使わない呼び出し用）。"""
    replies, _log, _declined = x_llm.generate_replies([{
        "id": "single", "author": author, "text": tweet_text,
        "topic": topic_desc(tweet_text), "context": simple_web_search(tweet_text),
    }])
    return replies.get("single")


def kill_stale_browser():
    """前回の異常終了などで自前プロファイルを掴んだままのChromiumを掃除する。

    ミューテックスで他のXジョブとは排他しているので、ここで残骸を落としても
    並行実行中の処理を壊すことはない。
    """
    if os.name != "nt":
        return
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -like '*x_user_data*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=40)
    except (OSError, subprocess.SubprocessError):
        pass

def open_browser(p):
    kill_stale_browser()
    os.makedirs(PROFILE, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx.add_init_script(INIT_SCRIPT)
    return ctx

def _status_id(elem):
    """article 要素から、その投稿自身の status id を取り出す。"""
    try:
        time_elem = elem.locator("time").first
        if time_elem.count() > 0:
            link = time_elem.locator("xpath=ancestor::a").first
            href = link.get_attribute("href") or ""
            if "/status/" in href:
                return href.split("/status/")[1].split("/")[0]
    except Exception:
        pass
    # メディア付きの注目ツイートなど、タイムスタンプがリンクになっていない
    # レイアウトがある（2026-11-16 実機確認）。その場合はパーマリンク
    # （/handle/status/<id> で終わるリンク）から取る。
    try:
        links = elem.locator('a[href*="/status/"]')
        for i in range(min(links.count(), 8)):
            href = links.nth(i).get_attribute("href") or ""
            m = re.fullmatch(r"/[^/]+/status/(\d+)", href)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""

def _author_handle(elem):
    """article 要素から投稿者の @handle（小文字・@なし）を取り出す。"""
    try:
        link = elem.locator('[data-testid="User-Name"] a').first
        href = link.get_attribute("href") or ""
        return href.strip("/").split("/")[0].lower()
    except Exception:
        return ""

def _author_name(elem):
    try:
        return elem.locator('[data-testid="User-Name"]').first.inner_text().split("\n")[0]
    except Exception:
        return "user"

def _tweet_text(elem):
    try:
        body = elem.locator('[data-testid="tweetText"]').first
        return body.inner_text() if body.count() > 0 else ""
    except Exception:
        return ""

def _replying_to(elem):
    """「返信先: @xxx」のリンクから、返信先の handle を取り出す。

    X の DOM には投稿者自身の @handle リンクもあるため、リンクの親要素の文言が
    「返信先」「Replying to」で始まるものだけを返信先とみなす。
    """
    try:
        links = elem.locator('xpath=.//a[starts-with(@href, "/")]')
        for i in range(min(links.count(), 15)):
            link = links.nth(i)
            parent_text = link.evaluate(
                "el => (el.parentElement && el.parentElement.textContent) || ''"
            ) or ""
            parent_text = parent_text.strip()
            if parent_text.startswith("返信先") or parent_text.startswith("Replying to"):
                href = (link.get_attribute("href") or "").strip("/").split("/")[0].lower()
                if href:
                    return href
    except Exception:
        return ""
    return ""

def find_tweet_article(page, tweet_id, max_scan=40):
    """現在のページから、指定 status id の article 要素を探す。"""
    articles = page.locator('article[data-testid="tweet"]')
    for i in range(min(articles.count(), max_scan)):
        elem = articles.nth(i)
        if _status_id(elem) == tweet_id:
            return elem
    return None

def read_thread(page, our_reply_id, own_handle):
    """自分の返信のスレッドを読み、親投稿・自分の返信・それへの返信を返す。"""
    articles = page.locator('article[data-testid="tweet"]')
    total = min(articles.count(), 30)
    main_idx = -1
    for i in range(total):
        if _status_id(articles.nth(i)) == our_reply_id:
            main_idx = i
            break
    if main_idx < 0:
        return None

    parent = articles.nth(main_idx - 1) if main_idx > 0 else None
    followups = []
    for i in range(main_idx + 1, total):
        elem = articles.nth(i)
        if _author_handle(elem) == own_handle:
            continue
        reply_to = _replying_to(elem)
        if reply_to and reply_to != own_handle:
            continue
        text = _tweet_text(elem).strip()
        sid = _status_id(elem)
        if not sid or not text:
            continue
        followups.append({
            "id": sid, "author": _author_name(elem), "text": text,
            "handle": _author_handle(elem),
        })

    return {
        "our_text": _tweet_text(articles.nth(main_idx)).strip(),
        "parent_author": _author_name(parent) if parent else "",
        "parent_text": _tweet_text(parent).strip() if parent else "",
        "followups": followups,
    }

def _clean_context(text, limit=300):
    """会話文脈用にURL・ハッシュタグ・余分な空白を落として短くする（トークン節約）。"""
    t = re.sub(r"https?://\S+", "", text or "")
    t = re.sub(r"#\S+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]

def scan_my_reply_followups(page, state, own_handle, limit):
    """自分の返信に返信が来ていないか確認し、会話の続きを返信候補として返す。

    プロフィールの「返信」タブを開くため、負荷を考えて一定間隔でしか実行しない。
    見つけた候補は、元の投稿→自分の返信→相手の返信という文脈付きで返す。
    """
    if not own_handle:
        return []

    now = time.time()
    last = float(state.get("followup_checked_at") or 0)
    interval = FOLLOWUP_CHECK_INTERVAL_MIN * 60
    if now - last < interval:
        remain = int((interval - (now - last)) // 60) + 1
        print(f"[i] 返信への返信チェックは前回から{int((now - last) // 60)}分のためスキップ（次回まで約{remain}分）")
        return []
    state["followup_checked_at"] = now
    save_state(state)

    print("[*] 自分の返信に付いた返信を確認します...")
    page.goto(f"https://x.com/{own_handle}/with_replies",
              wait_until="domcontentloaded", timeout=25000)
    time.sleep(3)

    articles = page.locator('article[data-testid="tweet"]')
    total = min(articles.count(), 25)
    my_replies = []
    for i in range(total):
        elem = articles.nth(i)
        if _author_handle(elem) != own_handle:
            continue
        sid = _status_id(elem)
        if not sid:
            continue
        my_replies.append(sid)
        if len(my_replies) >= FOLLOWUP_SCAN_REPLIES:
            break
    print(f"[*] 直近の自分の返信: {len(my_replies)}件を確認")

    found = []
    for sid in my_replies:
        page.goto(f"https://x.com/i/status/{sid}",
                  wait_until="domcontentloaded", timeout=25000)
        time.sleep(2.5)
        info = read_thread(page, sid, own_handle)
        if not info:
            print(f"[-] スレッドを読めませんでした (ID: {sid})")
            continue
        for fu in info["followups"]:
            if already_handled(state, fu["id"]):
                continue
            if len(fu["text"]) < FOLLOWUP_MIN_LEN:
                mark_seen(state, fu["id"])
                continue
            context = (
                "これは自分(@{own})の返信に対して相手から届いた返信です。会話の続きとして自然に返してください。\n"
                "元の投稿(@{pa}): {pt}\n自分の返信: {ot}\n相手の返信: {ft}\n"
                "自分の返信と同じ言い回しの繰り返しは避け、相手の返信に直接応えてください。"
            ).format(
                own=own_handle, pa=info["parent_author"] or "不明",
                pt=_clean_context(info["parent_text"], 300),
                ot=_clean_context(info["our_text"], 200),
                ft=_clean_context(fu["text"], 300),
            )
            found.append({
                "id": fu["id"], "author": fu["author"], "text": fu["text"],
                "topic": topic_desc(fu["text"]), "context": context,
                "priority": True,
                "url": f"https://x.com/i/status/{fu['id']}",
            })
            print(f"[+] 会話の続き: @{fu['author']} (ID: {fu['id']})")
            if len(found) >= limit:
                return found
    return found

def _open_status_article(page, tweet_id):
    """status ページを開いて、対象ツイートの article が描画されるまで待つ。

    返信ツイートのページは先祖ツイートも並ぶため、記事の描画が遅れて
    「要素が見つからない」になることがある（実際に発生）。数回リトライする。
    """
    for attempt in range(3):
        try:
            page.goto(f"https://x.com/i/status/{tweet_id}",
                      wait_until="domcontentloaded", timeout=25000)
        except Exception:
            time.sleep(3)
            continue
        try:
            page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        except Exception:
            pass
        time.sleep(1.5)
        article = find_tweet_article(page, tweet_id)
        if article is not None:
            return article
        # 表示位置が下にある場合があるので、少しスクロールしてから再探索
        try:
            page.mouse.wheel(0, 900)
            time.sleep(1.5)
        except Exception:
            pass
        article = find_tweet_article(page, tweet_id)
        if article is not None:
            return article
        time.sleep(2)
    return None

def post_reply(page, tweet_id, reply_text):
    """指定ツイートを開いて返信を投稿する。戻り値は (成功したか, 理由)。"""
    try:
        article = _open_status_article(page, tweet_id)
        if article is None:
            return False, "対象ツイートの要素が見つからない"
        reply_btn = article.locator('[data-testid="reply"]').first
        if reply_btn.count() == 0 or not reply_btn.is_visible():
            return False, "返信ボタンが見つからない"
        reply_btn.click()
        time.sleep(2)

        # 返信ボタンを押すとモーダルが開く。背景のインライン入力欄と
        # 取り違えないよう、ダイアログ内の入力欄を優先して使う。
        dialog = page.locator('[role="dialog"]').last
        container = dialog if dialog.count() > 0 else page
        editor = container.locator('[data-testid="tweetTextarea_0"]').last
        if editor.count() == 0:
            return False, "返信の入力欄が見つからない"
        editor.fill(reply_text)
        time.sleep(1)

        send_btn = None
        for selector in ('[data-testid="tweetButton"]', '[data-testid="tweetButtonInline"]'):
            btn = container.locator(selector).last
            if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                send_btn = btn
                break
        if send_btn is None:
            return False, "送信ボタンが見つからない"
        send_btn.click()
        time.sleep(3)

        # モーダルが閉じれば投稿成功。残っていれば失敗（重複投稿の警告など）とみなす。
        if dialog.count() > 0:
            try:
                dialog.wait_for(state="detached", timeout=8000)
            except Exception:
                return False, "送信後もモーダルが閉じない（投稿できていない可能性）"
        return True, ""
    except Exception as e:
        return False, f"投稿中にエラー: {e}"

def collect_candidates(page, state, own_handle, limit):
    """タイムラインから返信候補を集める。足りなければスクロールして追加読み込みする。"""
    candidates = []
    seen_ids = set()
    processed = 0
    stagnant = 0

    for round_no in range(MAX_SCROLLS + 1):
        tweets = page.locator('article[data-testid="tweet"]')
        total = tweets.count()
        print(f"[*] タイムライン読み込み: {total}件 (スクロール {round_no}回)")
        for idx in range(processed, min(total, SCAN_LIMIT)):
            tweet = tweets.nth(idx)
            try:
                time_elem = tweet.locator('time').first
                parent_link = time_elem.locator('xpath=ancestor::a').first if time_elem.count() > 0 else None
                href = parent_link.get_attribute("href") if parent_link and parent_link.count() > 0 else ""
                if not href or "/status/" not in href:
                    continue
                tweet_id = href.split("/status/")[1].split("/")[0]
                if tweet_id in seen_ids:
                    continue
                seen_ids.add(tweet_id)
                if already_handled(state, tweet_id):
                    print(f"[-] スキップ (ID: {tweet_id}): 返信済み/評価済み")
                    continue

                user_elem = tweet.locator('[data-testid="User-Name"]').first
                author = user_elem.inner_text().split("\n")[0] if user_elem.count() > 0 else "user"
                text_elem = tweet.locator('[data-testid="tweetText"]').first
                tweet_text = text_elem.inner_text() if text_elem.count() > 0 else ""

                ok, reason = is_reply_candidate(tweet_text, author, own_handle)
                if not ok:
                    print(f"[-] スキップ @{author} (ID: {tweet_id}): {reason}")
                    continue

                candidates.append({
                    "id": tweet_id, "author": author, "text": tweet_text,
                    "topic": topic_desc(tweet_text), "context": simple_web_search(tweet_text),
                    "priority": False,
                })
                if len(candidates) >= limit:
                    break
            except Exception as e:
                print(f"[!] 候補収集中にエラー: {e}")
                continue

        processed = min(total, SCAN_LIMIT)
        if len(candidates) >= limit or processed >= SCAN_LIMIT:
            break

        # まだ候補が足りないので、タイムラインを下に送って追加読み込みさせる
        page.mouse.wheel(0, 1800)
        time.sleep(2.5)
        if tweets.count() <= total:
            stagnant += 1
            if stagnant >= 2:
                print("[i] これ以上タイムラインが伸びないため走査を打ち切ります。")
                break
        else:
            stagnant = 0

    return candidates

def run_following_reply_cycle(publish=False, ignore_lock=False):
    """1サイクル実行する。戻り値は "done" / "lock"（他ジョブ実行中）/ "cap"（本日の上限）。"""
    if ignore_lock:
        if publish:
            print("[!] --ignore-lock と --publish は同時に使えません（本番ジョブとの二重投稿を防ぐため）")
            return "done"
        print("[!] --ignore-lock: 他のXジョブが動いていても強制実行します（ドライラン専用）")
        mutex = None
    else:
        mutex = acquire_mutex()
        if not mutex:
            print("[!] 他のX自動化ジョブが実行中のため、今回のサイクルをスキップします。")
            return "lock"

    state = load_state()
    load_replies_state_ids(refresh=True)
    if replies_today(state) >= MAX_REPLIES_PER_DAY:
        print(f"[i] 本日の自動返信上限({MAX_REPLIES_PER_DAY}件)に達しました。")
        release_mutex(mutex)
        return "cap"

    print("[*] X フォロー中タイムラインの巡回と自動返信サイクルを開始します...")
    with sync_playwright() as p:
        ctx = open_browser(p)
        page = ctx.new_page()
        try:
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)

            # 自分のハンドル(自分自身の投稿は返信しない)
            own_handle = ""
            try:
                link = page.locator('[data-testid="AppTabBar_Profile_Link"]').first
                own_handle = (link.get_attribute("href") or "").strip("/").lower()
            except Exception:
                pass

            candidates = []
            # 要件: 自分の返信に返信が来ていれば、それを最優先で拾う。
            if own_handle:
                try:
                    candidates = scan_my_reply_followups(page, state, own_handle, FOLLOWUP_MAX)
                except Exception as e:
                    print(f"[!] 返信への返信チェックでエラー: {e}")

            # スレッド巡回でページが動いているので、フォロー中タイムラインに戻る
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)
            time.sleep(2.5)
            try:
                following_tab = page.locator('text="フォロー中"').first
                if following_tab.is_visible():
                    following_tab.click()
                    time.sleep(2)
            except Exception:
                pass

            remaining = max(0, BATCH_SIZE - len(candidates))
            if remaining:
                candidates += collect_candidates(page, state, own_handle, remaining)
            # 同じ投稿がフォロー中と会話の続きの両方に出ても二重返信しない
            uniq = {}
            for c in candidates:
                uniq.setdefault(c["id"], c)
            candidates = list(uniq.values())
            if not candidates:
                print("[i] 返信に値する投稿が見つからなかったため終了します。")
                return "done"

            print(f"\n[*] {len(candidates)}件をまとめてLLMに投げます（B方式・バッチ生成）")
            replies, log, declined = x_llm.generate_replies(candidates)
            for line in log:
                print("    " + line)

            if not replies and not declined:
                # 全モデル失敗時のみ、トピック別の定型文で応急処置する（Bの最終保険）
                print("[!] LLMが全滅したためトピック定型文にフォールバックします")
                for c in candidates:
                    t = topic_reply(c["text"])
                    if t:
                        replies[c["id"]] = t

            posted = 0
            for c in candidates:
                reply_text = replies.get(c["id"])
                label = "会話の続き" if c.get("priority") else (c["topic"] or "未分類")
                print(f"\n[+] @{c['author']} (ID: {c['id']}) {label}")
                print(f"    内容: {c['text'][:60].replace(chr(10), ' ')}...")
                if not reply_text:
                    if c["id"] in declined:
                        print("    [-] モデルが返信不要と判断（宣伝・文脈不明など）")
                    else:
                        print("    [-] 返信文が得られなかったためスキップ")
                    mark_seen(state, c["id"])
                    continue
                if quotes_source(reply_text, c["text"]):
                    print("    [-] 投稿本文の言い回しをなぞっているためスキップ（引用禁止）")
                    mark_seen(state, c["id"])
                    continue
                if len(reply_text) > 140:
                    print(f"    [-] 返信が長すぎるためスキップ({len(reply_text)}字)")
                    mark_seen(state, c["id"])
                    continue
                print(f"    → {reply_text}")

                if not publish:
                    continue
                if posted >= POST_PER_CYCLE:
                    print(f"    [i] このサイクルの投稿上限({POST_PER_CYCLE}件)に達しました")
                    break
                ok, err = post_reply(page, c["id"], reply_text)
                if ok:
                    record_reply(state, c["id"])
                    posted += 1
                    print(f"    [✓] 返信を投稿しました ({posted}/{POST_PER_CYCLE})")
                else:
                    print(f"    [!] 投稿に失敗: {err}")

            if not publish:
                print("\n[i] ドライランモードのため返信は送信しませんでした。")

        finally:
            ctx.close()
            kill_stale_browser()
            release_mutex(mutex)
    return "done"

class _Tee:
    """標準出力をコンソールとログファイルの両方に流す（UTF-8で書く）。"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
            except (OSError, ValueError):
                pass

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except (OSError, ValueError):
                pass


def cycle_wait_seconds(now=None):
    """次のサイクルまでの待ち時間。日中は短く、深夜は長く、毎回ランダムに散らす。"""
    now = now or datetime.datetime.now()
    if 7 <= now.hour < 23:
        minutes = random.uniform(*DAY_INTERVAL_MIN)
    else:
        minutes = random.uniform(*NIGHT_INTERVAL_MIN)
    if random.random() < LONG_REST_PROB:
        minutes *= random.uniform(1.4, 1.9)
    return minutes * 60

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="実際に返信を投稿する")
    parser.add_argument("--loop", action="store_true",
                        help="ランダム間隔で回り続ける（無人実行用。Ctrl+Cで終了）")
    parser.add_argument("--ignore-lock", action="store_true",
                        help="他のXジョブが動いていても実行する（ドライラン専用・--publishとは併用不可）")
    parser.add_argument("--log-file", default="",
                        help="指定すると標準出力をUTF-8でこのファイルにも追記する（無人実行用）")
    args = parser.parse_args()

    if args.log_file:
        os.makedirs(os.path.dirname(os.path.abspath(args.log_file)), exist_ok=True)
        # buffering=1（行バッファ）: --loop で常駐させると、プロセス終了までログが
        # 書かれない（ブロックバッファのまま）ため、1行ごとに流す。
        _log = open(args.log_file, "a", encoding="utf-8", newline="\n", buffering=1)
        sys.stdout = _Tee(sys.stdout, _log)
        sys.stderr = _Tee(sys.stderr, _log)

    if not args.loop:
        print(f"\n===== {datetime.datetime.now().isoformat(timespec='seconds')} =====")
        run_following_reply_cycle(publish=args.publish, ignore_lock=args.ignore_lock)
        sys.exit(0)

    print(f"\n===== ループ開始 {datetime.datetime.now().isoformat(timespec='seconds')} =====")
    while True:
        print(f"\n===== {datetime.datetime.now().isoformat(timespec='seconds')} =====")
        status = "done"
        try:
            status = run_following_reply_cycle(publish=args.publish, ignore_lock=args.ignore_lock)
        except KeyboardInterrupt:
            print("[i] Ctrl+C を受けたため終了します。")
            break
        except Exception as e:
            # 1サイクルの失敗でループを止めない（ブラウザの一時的な不調など）
            print(f"[!] サイクルが異常終了しました: {e}")

        if status == "lock":
            # 他のXジョブとぶつかっただけなので、間隔を空けず数分後に再挑戦する
            wait = random.uniform(3, 8) * 60
        elif status == "cap":
            # 本日の上限に達したら、翌日の0時台まで待つ
            now = datetime.datetime.now()
            nxt_day = (now + datetime.timedelta(days=1)).replace(
                hour=0, minute=random.randint(2, 9), second=0, microsecond=0
            )
            wait = max(60, (nxt_day - now).total_seconds())
        else:
            wait = cycle_wait_seconds()

        nxt = datetime.datetime.now() + datetime.timedelta(seconds=wait)
        print(f"[i] 次回は {nxt.strftime('%m/%d %H:%M')} 頃に実行します（{int(wait // 60)}分後）")
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("[i] Ctrl+C を受けたため終了します。")
            break
