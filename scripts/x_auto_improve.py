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
import hashlib
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
import x_content_guard  # noqa: E402
from x_automation_config import get_limit, get_policy  # noqa: E402

CONSULT_DIR = BASE / "data" / "x-consulting"
PROPOSAL_DIR = CONSULT_DIR / "proposals"
ANALYSIS_DIR = CONSULT_DIR / "analyses"
STATE_PATH = CONSULT_DIR / "auto-improve-state.json"

MUTEX_NAME = "Local\\kingsworksub-blog-x-jobs"
# 単体実行時は空くまで長めに待つ。ランナー経由では X_SKIP_JOB_MUTEX=1 が渡され、
# PowerShell 側が既に保持しているため Python 側の二重取得をスキップする。
MUTEX_WAIT_MS = int(float(os.environ.get("X_MUTEX_WAIT_SEC", "900")) * 1000)
SKIP_JOB_MUTEX = os.environ.get("X_SKIP_JOB_MUTEX") == "1"

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


def _focus_article(action: dict[str, Any]) -> dict[str, str]:
    """内部アクションから一般向け話題を選ぶ。アクション文そのものは渡さない。

    2026-11-23の事故では、内部の「次アクション（リンクをリプライ欄へ誘導する実験）」を
    LLMに渡した結果、アカウント運用方針をそのまま投稿してしまった。以来、
    投稿の材料は自分のブログ記事のタイトル・説明だけに限定する。
    """
    try:
        items = x_link_resolver.blog_candidates()
    except Exception:
        return {}
    items = [i for i in items if x_content_guard.is_safe(str(i.get("title") or ""), strict=True)]
    if not items:
        return {}
    seed = f"{action.get('id') or action.get('title') or ''}:{now_jst().strftime('%Y-%m-%d')}"
    idx = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(items)
    picked = items[idx]
    return {
        "title": str(picked.get("title") or ""),
        "description": str(picked.get("description") or ""),
        "tags": str(picked.get("tags") or ""),
    }


def build_prompt(action: dict[str, Any], link_policy: str, link_pct: int, retry_note: str = "") -> str:
    examples = _recent_post_examples()
    blog_titles = _blog_title_examples()
    # NOTE: 内部の「次アクション」のタイトル・理由・指標は渡さない。
    # 渡すのは一般読者向けの話題（自分の記事）だけ。
    ctx = {
        "focus_article": _focus_article(action),
        "recent_posts": examples,
        "own_blog_titles": blog_titles,
        "link_policy": link_policy,
        "link_probability_pct": link_pct,
    }
    return (
        "あなたは一般読者向けのSNS投稿を書く編集者です。自分のブログ記事のテーマから、"
        "読者が興味を持つ話題を1つ選んで新規投稿を1本作ってください。\n"
        "出力はJSONオブジェクトのみ。前後に説明文を付けない。\n\n"
        "スキーマ:\n"
        "{\n"
        '  "should_post": true,\n'
        '  "post_text": "本文",\n'
        '  "topic": "一言テーマ",\n'
        '  "keywords": ["関連語", "..."],\n'
        '  "link_decision": {"needed": true, "kind": "youtube|blog|none", "query": "検索語", "reason": "なぜこの話題に補足情報が役立つか"},\n'
        '  "placement": "reply|inline|none",\n'
        '  "reply_text": "リンクを置く最初の返信の短い導入文（URLは入れない）"\n'
        "}\n\n"
        "【絶対に書いてはいけない内容（2026-11-23の事故を受けた最重要規則）】\n"
        "- このアカウント/Botの運用方針・設計・自動化・実験・検証・改善施策\n"
        "- SNSの表示数/インプレッション/アルゴリズムをどう伸ばすかという内部戦略\n"
        "- リンクを本文に置くかリプライに置くか、投稿数や返信数の上限、ルール調整の話\n"
        "- レポート/KPI/モデル/スクリプト/プロジェクト構成の話\n"
        "- つまり「自分の運用を振り返ってテストしています」といったメタ投稿は一切禁止。\n"
        "  対象はあくまで focus_article の話題そのもの（例: 音楽、道具、文化、料理）です。\n\n"
        "制約:\n"
        "- 本文は日本語60〜120字。280 weighted を超えない。\n"
        "- ハッシュタグ禁止。絵文字は0〜1個。\n"
        "- 元ネタの言い回しをそのまま引用しない。\n"
        "- 宣伝臭を抑え、話題そのものを具体的に伝える。\n"
        "- リンクは、この話題と関連し、読者の理解に役立つと判断したときだけ needed=true。\n"
        "- kind=youtube のときは query にYouTube検索語を入れる。kind=blog のときは query に記事タイトルの手がかりを入れる。\n"
        "- link_policy が native_then_first_reply のとき、本文にURLを入れない（URLは最初の返信）。\n"
        "- link_policy が inline のときは placement=inline にし、本文にURLを1つだけ入れてよい。\n"
        "- placement=none のとき reply_text は空文字。\n"
        + (f"\n[再生成指示] 前回の出力は禁止トピックに該当しました。連絡/運用/実験の話をやめ、"
           f"focus_article の話題だけを一般読者向けに書き直してください。\n" if retry_note else "")
        + "\n入力:\n```json\n" + json.dumps(ctx, ensure_ascii=False, indent=2) + "\n```\n"
    )


def generate_plan(action: dict[str, Any], link_policy: str, link_pct: int) -> tuple[dict[str, Any] | None, list[str], str]:
    """生成後にハードガードを通す。ダメなら最大3回作り直し、全滅なら投稿しない。"""
    log: list[str] = []
    model = ""
    retry = ""
    for attempt in range(3):
        obj, part_log, model = x_llm.generate_json(
            build_prompt(action, link_policy, link_pct, retry_note=retry),
            label="投稿プラン",
        )
        log += part_log
        if not isinstance(obj, dict) or not obj.get("post_text"):
            return None, log, model
        text = _sanitize_text(str(obj.get("post_text")), link_policy, str(obj.get("placement") or "none"))
        reply = _sanitize_text(str(obj.get("reply_text") or ""), link_policy, "none")
        reasons = x_content_guard.find_unsafe_reasons(text, strict=True)
        reasons += [f"reply:{r}" for r in x_content_guard.find_unsafe_reasons(reply, strict=True)]
        if not reasons:
            return obj, log, model
        log.append(f"[!] content_guard blocked attempt {attempt+1}: {', '.join(reasons)}")
        retry = ", ".join(reasons)
    return None, log, model


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


def log_blocked(reasons: list[str], post_text: str, action: dict[str, Any] | None, model: str) -> None:
    """禁止トピックでブロックした内容を監査用に残す（本文は出さない）。"""
    entry = {
        "at": now_iso(),
        "reasons": reasons,
        "action_id": (action or {}).get("id"),
        "model": model,
        "post_text_head": (post_text or "")[:80],
    }
    path = CONSULT_DIR / "auto-improve-guard.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


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
        if any("content_guard" in line for line in llm_log):
            log_blocked(["content_guard_exhausted"], "", action, model)
            return {
                "ok": True, "skipped": "content_guard",
                "llm_log": llm_log, "action": action.get("title"),
                "note": "生成を3回試しましたが禁止トピックを含んでいたため投稿しませんでした",
            }
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

    # 最終ハードガード: ここを通らない限りブラウザを開かない。
    # プロンプトをすり抜けた内部設計・運用実験のつぶやきを必ず止める。
    final_reasons = x_content_guard.find_unsafe_reasons(body, strict=True)
    if reply_text:
        final_reasons += [f"reply:{r}" for r in x_content_guard.find_unsafe_reasons(reply_text, strict=True)]
    if final_reasons:
        final_reasons = sorted(set(final_reasons))
        log_blocked(final_reasons, body, action, model)
        blocked = {
            "ok": True,
            "skipped": "content_guard",
            "reasons": final_reasons,
            "action": action.get("title"),
            "post_text": body,
            "llm_log": llm_log,
            "note": "内部設計/運用実験と判定したため送信しませんでした",
        }
        print(json.dumps(blocked, ensure_ascii=False, indent=2))
        return blocked

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
    # ランナーが既に同じミューテックスを保持しているときは二重取得しない。
    if not args.ignore_lock and not SKIP_JOB_MUTEX:
        mutex = acquire_mutex()
        if not mutex:
            wait_sec = MUTEX_WAIT_MS / 1000
            print(json.dumps({
                "ok": True, "skipped": "lock",
                "detail": f"could not acquire x jobs mutex after {wait_sec:g}s",
            }, ensure_ascii=False))
            return 0
    try:
        res = run(publish=args.publish, ignore_lock=args.ignore_lock, force=args.force)
        return 0 if res.get("ok") else 1
    finally:
        release_mutex(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
