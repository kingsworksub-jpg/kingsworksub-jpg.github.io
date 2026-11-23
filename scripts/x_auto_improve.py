# -*- coding: utf-8 -*-
"""X自己改善エコシステムの実行器。

日次レポート（data/x-consulting/proposals/<date>.json）の next_actions から
1件を選び、LLMで投稿文を生成し、必要なら関連リンクを解決して、
「本文はネイティブ完結・リンクは最初の返信」を基本に投稿する。

2026-11-23 ユーザー指示:
- 次アクションを待たずに自動実行する（完全自動の自己改善）。
- リンクはキュー/RSSではなく、投稿内容・文脈に関連し、インプレッション改善に
  寄与するとLLMが判断したときだけ貼る。
- 「本文ネイティブ＋リンクは最初の返信」は基本方針。レポートが「本文直置きが
  有利」と判断した場合は managed-limits.json の X_LINK_POLICY が inline に変わり、
  このスクリプトもそれに従う。

安全策:
- 1日の投稿数上限（X_MAX_POSTS_PER_DAY、既定1）
- 投稿間隔の最低時間（X_MIN_HOURS_BETWEEN_POSTS、既定8時間）
- 他Xジョブとの共有ミューテックス
- 同じアクションの短期連続実行を避ける（既定7日）
- --publish を付けない限りドライラン（投稿しない）
"""
from __future__ import annotations

import argparse
import ctypes
import datetime
import importlib.util
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import x_llm  # noqa: E402
import x_link_resolver  # noqa: E402
from x_automation_config import get_limit, get_policy  # noqa: E402

CONSULT_DIR = BASE / "data" / "x-consulting"
PROPOSAL_DIR = CONSULT_DIR / "proposals"
ANALYSIS_DIR = CONSULT_DIR / "analyses"
STATE_PATH = CONSULT_DIR / "auto-improve-state.json"

MUTEX_NAME = "Local\\kingsworksub-blog-x-jobs"
MUTEX_WAIT_MS = int(float(os.environ.get("X_MUTEX_WAIT_SEC", "120")) * 1000)

ACTION_REPEAT_DAYS = int(os.environ.get("X_ACTION_REPEAT_DAYS", "7"))

CONTENT_HINTS = [
    "投稿", "ポスト", "ツイート", "テキスト", "文章", "コンテンツ", "記事",
    "リンク", "ツリー", "画像", "メディア", "動画", "対話", "リプライ", "返信",
    "世界観", "こだわり", "ノウハウ", "プロフィール", "導線", "紹介", "発信",
]


def now_jst() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))


def now_iso() -> str:
    return now_jst().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Mutex (shared with the other X jobs)
# ---------------------------------------------------------------------------

def acquire_mutex(timeout_ms: int = MUTEX_WAIT_MS):
    if os.name != "nt":
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    result = kernel32.WaitForSingleObject(handle, timeout_ms)
    if result in (0x0, 0x80):
        return handle
    kernel32.CloseHandle(handle)
    return None


def release_mutex(handle) -> None:
    if os.name != "nt" or not handle:
        return
    ctypes.windll.kernel32.ReleaseMutex(handle)
    ctypes.windll.kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# State / caps
# ---------------------------------------------------------------------------

def load_state() -> dict[str, Any]:
    state = load_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("version", 1)
    state.setdefault("daily_counts", {})
    state.setdefault("history", [])
    state.setdefault("executed_actions", {})
    return state


def posts_today(state: dict[str, Any], date: str) -> int:
    try:
        return int((state.get("daily_counts") or {}).get(date, 0))
    except Exception:
        return 0


def hours_since_last_post(state: dict[str, Any]) -> float | None:
    last = state.get("last_post_at")
    if not last:
        return None
    try:
        dt = datetime.datetime.fromisoformat(last)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
        return (now_jst() - dt).total_seconds() / 3600.0
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Action selection
# ---------------------------------------------------------------------------

def latest_proposal() -> dict[str, Any] | None:
    files = sorted(PROPOSAL_DIR.glob("*.json"))
    if not files:
        return None
    obj = load_json(files[-1], None)
    return obj if isinstance(obj, dict) else None


def _is_content_action(a: dict[str, Any]) -> bool:
    if isinstance(a.get("deploy"), dict):
        return False  # ルール変更は x_deploy.py の担当
    blob = f"{a.get('title','')} {a.get('reason','')} {a.get('metric','')}".lower()
    return any(h.lower() in blob for h in CONTENT_HINTS)


def select_action(proposal: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any] | None:
    actions = []
    if isinstance(proposal, dict):
        actions = [a for a in (proposal.get("actions") or []) if isinstance(a, dict)]
    if not actions:
        # fallback: latest LLM diagnosis
        files = sorted(ANALYSIS_DIR.glob("*.json"))
        if files:
            obj = load_json(files[-1], {})
            actions = [a for a in ((obj.get("diagnosis") or {}).get("next_actions") or []) if isinstance(a, dict)]
    if not actions:
        return None

    content = [a for a in actions if _is_content_action(a)]
    pool = content or actions
    executed = state.get("executed_actions") or {}
    today = now_jst().date()

    def last_executed_days(a: dict[str, Any]) -> int:
        aid = str(a.get("id") or a.get("title") or "")
        raw = executed.get(aid)
        if not raw:
            return 10**6
        try:
            d = datetime.date.fromisoformat(str(raw))
            return (today - d).days
        except Exception:
            return 10**6

    # 優先: まだ実行していないもの → 実行から日が経っているもの
    pool.sort(key=lambda a: (-last_executed_days(a), str(a.get("id") or "")))
    for a in pool:
        if last_executed_days(a) >= ACTION_REPEAT_DAYS:
            return a
    return pool[0] if pool else None


# ---------------------------------------------------------------------------
# LLM post generation
# ---------------------------------------------------------------------------

def _weighted_len(text: str) -> int:
    total = 0
    for ch in text:
        cp = ord(ch)
        wide = (
            0x1100 <= cp <= 0x115F
            or 0x2E80 <= cp <= 0xA4CF
            or 0xAC00 <= cp <= 0xD7A3
            or 0xF900 <= cp <= 0xFAFF
            or 0xFE30 <= cp <= 0xFE6F
            or 0xFF00 <= cp <= 0xFF60
            or 0xFFE0 <= cp <= 0xFFE6
            or 0x1F300 <= cp <= 0x1FAFF
            or 0x20000 <= cp <= 0x3FFFD
        )
        total += 2 if wide else 1
    return total


def _sanitize_text(text: str, link_policy: str, placement: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"#\S+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # 絵文字は最大1個
    emojis = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text)
    if len(emojis) > 1:
        for e in emojis[1:]:
            text = text.replace(e, "", 1)
    # 280 weighted を超えないように、句点で切る
    while _weighted_len(text) > 270 and len(text) > 20:
        cut = max(text.rfind("。"), text.rfind("！"), text.rfind("？"), text.rfind("\n"))
        if cut < 10:
            cut = len(text) - 2
        text = text[:cut].rstrip()
    return text


def _recent_post_examples(limit: int = 5) -> list[str]:
    files = sorted(ANALYSIS_DIR.glob("*.json"))
    if not files:
        return []
    obj = load_json(files[-1], {})
    metrics = obj.get("metrics") or {}
    return [str(p.get("text_head") or "") for p in (metrics.get("top_posts") or [])[:limit] if p.get("text_head")]


def _blog_title_examples(limit: int = 20) -> list[str]:
    try:
        items = x_link_resolver.blog_candidates()
    except Exception:
        return []
    return [str(x.get("title") or "") for x in items[:limit] if x.get("title")]


def build_prompt(action: dict[str, Any], link_policy: str, link_pct: int) -> str:
    examples = _recent_post_examples()
    blog_titles = _blog_title_examples()
    ctx = {
        "action": {
            "title": action.get("title"),
            "reason": action.get("reason"),
            "metric": action.get("metric"),
            "horizon_days": action.get("horizon_days"),
        },
        "recent_posts": examples,
        "own_blog_titles": blog_titles,
        "link_policy": link_policy,
        "link_probability_pct": link_pct,
    }
    return (
        "あなたはX(Twitter)運用の編集者です。以下の「次アクション」を実行する新規投稿を1本作ってください。\n"
        "出力はJSONオブジェクトのみ。前後に説明文を付けない。\n\n"
        "スキーマ:\n"
        "{\n"
        '  "should_post": true,\n'
        '  "post_text": "本文",\n'
        '  "topic": "一言テーマ",\n'
        '  "keywords": ["関連語", "..."],\n'
        '  "link_decision": {"needed": true, "kind": "youtube|blog|none", "query": "検索語", "reason": "なぜリンクが表示改善に効くか"},\n'
        '  "placement": "reply|inline|none",\n'
        '  "reply_text": "リンクを置く最初の返信の短い導入文（URLは入れない）"\n'
        "}\n\n"
        "制約:\n"
        "- 本文は日本語60〜120字。280 weighted を超えない。\n"
        "- ハッシュタグ禁止。絵文字は0〜1個。\n"
        "- 元ネタの言い回しをそのまま引用しない。\n"
        "- 本文は読者の興味を引く具体的な内容にする。宣伝臭を抑える。\n"
        "- リンクは、この投稿内容と関連し、インプレッション改善に寄与すると判断したときだけ needed=true。\n"
        "  関連が弱い・宣伝臭が出る・リンクなしでも成立するなら needed=false。\n"
        "- kind=youtube のときは query にYouTube検索語を入れる。kind=blog のときは query に自分の記事タイトルの手がかりを入れる。\n"
        "- link_policy が native_then_first_reply のとき、本文にURLを入れない（URLは最初の返信）。\n"
        "- link_policy が inline のときは placement=inline にし、本文にURLを1つだけ入れてよい。\n"
        "- placement=none のとき reply_text は空文字。\n\n"
        "入力:\n"
        "```json\n" + json.dumps(ctx, ensure_ascii=False, indent=2) + "\n```\n"
    )


def generate_plan(action: dict[str, Any], link_policy: str, link_pct: int) -> tuple[dict[str, Any] | None, list[str], str]:
    prompt = build_prompt(action, link_policy, link_pct)
    obj, log, model = x_llm.generate_json(prompt, label="投稿プラン")
    return obj, log, model


# ---------------------------------------------------------------------------
# Posting (reuse post-to-x.py)
# ---------------------------------------------------------------------------

def _load_post_module():
    path = Path(__file__).resolve().parent / "post-to-x.py"
    spec = importlib.util.spec_from_file_location("post_to_x", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def record(state: dict[str, Any], entry: dict[str, Any], published: bool) -> None:
    date = now_jst().strftime("%Y-%m-%d")
    state.setdefault("history", []).append(entry)
    state["history"] = state["history"][-200:]
    if published:
        counts = state.setdefault("daily_counts", {})
        counts[date] = int(counts.get(date, 0)) + 1
        state["last_post_at"] = now_iso()
        aid = str(entry.get("action_id") or "")
        if aid:
            state.setdefault("executed_actions", {})[aid] = date
    save_json(STATE_PATH, state)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(publish: bool, ignore_lock: bool, force: bool) -> dict[str, Any]:
    link_policy = get_policy("X_LINK_POLICY")
    link_pct = get_limit("X_LINK_PROBABILITY_PCT", 35)
    max_posts = get_limit("X_MAX_POSTS_PER_DAY", 1)
    min_hours = get_limit("X_MIN_HOURS_BETWEEN_POSTS", 8)

    state = load_state()
    today = now_jst().strftime("%Y-%m-%d")
    used = posts_today(state, today)
    since = hours_since_last_post(state)

    if not force:
        if used >= max_posts:
            return {"ok": True, "skipped": "daily_cap", "used": used, "cap": max_posts}
        if since is not None and since < min_hours:
            return {
                "ok": True, "skipped": "min_interval",
                "hours_since_last_post": round(since, 2), "min_hours": min_hours,
            }

    proposal = latest_proposal()
    action = select_action(proposal, state)
    if not action:
        return {"ok": False, "skipped": "no_action", "error": "no actionable content in proposal"}

    plan, llm_log, model = generate_plan(action, link_policy, link_pct)
    if not isinstance(plan, dict) or not plan.get("post_text"):
        return {"ok": False, "skipped": "llm_failed", "llm_log": llm_log, "action": action.get("title")}

    if plan.get("should_post") is False:
        return {"ok": True, "skipped": "llm_declined", "llm_log": llm_log, "action": action.get("title")}

    keywords = [str(k) for k in (plan.get("keywords") or []) if isinstance(k, str) and k.strip()]
    post_text = _sanitize_text(str(plan.get("post_text")), link_policy, str(plan.get("placement") or "none"))

    # リンク確率ゲート（LLM判断の上にかける上限）
    decision = plan.get("link_decision") if isinstance(plan.get("link_decision"), dict) else {}
    if decision.get("needed") and link_pct > 0:
        if random.randint(1, 100) > link_pct:
            decision = {"needed": False, "kind": "none", "reason": "probability_gate"}
    elif link_pct <= 0:
        decision = {"needed": False, "kind": "none", "reason": "probability_zero"}

    link = None
    if decision.get("needed"):
        try:
            link = x_link_resolver.resolve_link(decision, post_text, keywords)
        except Exception as e:
            link = None
            llm_log.append(f"[!] link resolve failed: {e}")

    placement = str(plan.get("placement") or "none")
    if link is None:
        placement = "none"
    if link_policy == "inline":
        placement = "inline"
    elif link_policy == "native_then_first_reply" and link is not None and placement == "inline":
        placement = "reply"

    body = post_text
    reply_text = _sanitize_text(str(plan.get("reply_text") or ""), link_policy, "none")
    if link is not None and placement == "inline":
        urls = re.findall(r"https?://\S+", body)
        if urls:
            body = body.replace(urls[0], link["url"])
        elif _weighted_len(body) + _weighted_len(link["url"]) + 1 <= 280:
            body = f"{body}\n{link['url']}"
        else:
            placement = "reply"
    if link is not None and placement == "reply" and not reply_text:
        reply_text = "参考までに、こちらのリンクも置いておきます。"

    result: dict[str, Any] = {
        "ok": True,
        "date": today,
        "model": model,
        "action_id": action.get("id"),
        "action_title": action.get("title"),
        "post_text": body,
        "topic": plan.get("topic"),
        "keywords": keywords,
        "link_policy": link_policy,
        "link_probability_pct": link_pct,
        "link": link,
        "placement": placement,
        "reply_text": reply_text if link is not None and placement == "reply" else "",
        "llm_log": llm_log,
        "dry_run": not publish,
    }

    if not publish:
        result["posted"] = False
        result["note"] = "dry-run: --publish で実際に投稿します"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    pt = _load_post_module()
    from playwright.sync_api import sync_playwright

    post_result: dict[str, Any] = {}
    reply_result: dict[str, Any] | None = None
    with sync_playwright() as p:
        ctx = pt.open_browser(p)
        try:
            post_result = pt.post_text(ctx, body, True)
            status_id = str(post_result.get("status_id") or "")
            if link is not None and placement == "reply" and status_id:
                reply_body = f"{reply_text}\n{link['url']}".strip()
                if _weighted_len(reply_body) > 280:
                    reply_body = link["url"]
                reply_result = pt.reply_to_tweet(ctx, status_id, reply_body, True)
        finally:
            ctx.close()

    result["posted"] = bool(post_result.get("posted"))
    result["status_id"] = post_result.get("status_id")
    result["url"] = post_result.get("url")
    result["reply"] = reply_result

    entry = {
        "at": now_iso(),
        "action_id": action.get("id"),
        "action_title": action.get("title"),
        "post_text": body,
        "status_id": post_result.get("status_id"),
        "url": post_result.get("url"),
        "reply_text": result["reply_text"],
        "reply_status_id": (reply_result or {}).get("status_id"),
        "link": link,
        "placement": placement,
        "model": model,
        "result": "posted" if result["posted"] else "failed",
    }
    record(state, entry, result["posted"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="実際に投稿する（未指定はドライラン）")
    ap.add_argument("--once", action="store_true", help="1回だけ実行（互換用）")
    ap.add_argument("--ignore-lock", action="store_true", help="他Xジョブのロックを無視（ドライラン専用）")
    ap.add_argument("--force", action="store_true", help="日次上限・最低間隔を無視（テスト用）")
    ap.add_argument("--log-file", default="", help="標準出力をUTF-8で追記するログファイル")
    args = ap.parse_args()

    if args.log_file:
        os.makedirs(os.path.dirname(os.path.abspath(args.log_file)), exist_ok=True)
        log = open(args.log_file, "a", encoding="utf-8", newline="\n", buffering=1)
        sys.stdout = log
        sys.stderr = log

    if args.ignore_lock and args.publish:
        print("[!] --ignore-lock と --publish は同時に使えません")
        return 2

    mutex = None
    if not args.ignore_lock:
        mutex = acquire_mutex()
        if not mutex:
            print(json.dumps({"ok": True, "skipped": "lock"}, ensure_ascii=False))
            return 0
    try:
        res = run(publish=args.publish, ignore_lock=args.ignore_lock, force=args.force)
        return 0 if res.get("ok") else 1
    finally:
        release_mutex(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
