# -*- coding: utf-8 -*-
"""Daily X account consulting + self-improvement rule engine.

Collects a public/profile snapshot via the existing Playwright profile, reads local
X automation state files, computes basic KPIs, optionally asks an LLM for a structured
diagnosis, and writes snapshot/analysis/report artifacts under data/x-consulting/.

2026-11-23: ユーザー指示により「読み取り専用」から、レポートに基づいて
X自動化ルールを**自動調整**するエンジンへ拡張した。実際の適用は
scripts/x_deploy.py --auto-safe が行い、このスクリプト自身は提案JSONを書くだけ。

Safety: this script does NOT post, like, follow, DM, or directly change config.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    from model_chains import X_CONSULTING_CHAIN, resolve_chain
except Exception:
    X_CONSULTING_CHAIN = [
        "google/gemini-3.5-flash-lite",
        "google/gemini-3.5-flash#high",
        "opencode/deepseek-v4.1-flash-free",
        "opencode/longcat-2.5-free",
    ]

    def resolve_chain(defaults, chain_env, primary_env=None, primary_override=None):  # type: ignore
        return list(defaults)


BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
PROFILE_DIR = DATA_DIR / "x_user_data"
OUT_ROOT = DATA_DIR / "x-consulting"
SNAP_DIR = OUT_ROOT / "snapshots"
ANALYSIS_DIR = OUT_ROOT / "analyses"
REPORT_DIR = OUT_ROOT / "reports"
PROPOSAL_DIR = OUT_ROOT / "proposals"
STATE_PATH = OUT_ROOT / "state.json"
HTML_REPORT_PATH = BASE / "xaccounting-reports.html"
TARGET_HANDLE = os.environ.get("X_TARGET_HANDLE", "100labjtvn")
MUTEX_NAME = "Local\\kingsworksub-blog-x-jobs"
OPENCODE_FALLBACK_EXE = r"C:\Users\norio\AppData\Roaming\npm\opencode.cmd"


def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))


def jst_date_str(dt: datetime | None = None) -> str:
    dt = dt or now_jst()
    return dt.strftime("%Y-%m-%d")


def ensure_dirs() -> None:
    for d in [SNAP_DIR, ANALYSIS_DIR, REPORT_DIR, PROPOSAL_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def acquire_mutex(timeout_ms: int = 15000):
    if os.name != "nt":
        return None
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    WAIT_OBJECT_0 = 0x00000000
    WAIT_ABANDONED = 0x00000080
    res = kernel32.WaitForSingleObject(handle, timeout_ms)
    if res in (WAIT_OBJECT_0, WAIT_ABANDONED):
        return handle
    kernel32.CloseHandle(handle)
    return False


def release_mutex(handle) -> None:
    if not handle or os.name != "nt":
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReleaseMutex(handle)
    kernel32.CloseHandle(handle)


def find_opencode() -> str:
    exe = shutil.which("opencode")
    if exe:
        return exe
    if os.path.exists(OPENCODE_FALLBACK_EXE):
        return OPENCODE_FALLBACK_EXE
    return ""


def run_opencode(prompt: str, model: str, timeout: int = 180) -> tuple[bool, str]:
    exe = find_opencode()
    if not exe:
        return False, "opencode CLI not found"
    scratch = tempfile.mkdtemp(prefix="x-consult-")
    cmd = [exe, "run", "--standalone", "--model", model, "--agent", "build", "--auto",
           "--archived", "--format", "json", "--title", "x-consulting"]
    env = dict(os.environ)
    env["PWD"] = scratch
    env["OLDPWD"] = scratch
    try:
        proc = subprocess.Popen(cmd, cwd=scratch, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                encoding="utf-8", errors="replace",
                                start_new_session=(os.name != "nt"))
    except OSError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        return False, f"launch failed: {exc}"
    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.communicate(timeout=10)
        except Exception:
            pass
        shutil.rmtree(scratch, ignore_errors=True)
        return False, f"timeout {timeout}s"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if proc.returncode != 0:
        tail = (stderr or "").strip().splitlines()
        return False, tail[-1] if tail else f"exit {proc.returncode}"
    # extract last text part
    by_message: dict[str, list[str]] = {}
    order: list[str] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        part = event.get("part") or {}
        if event.get("type") == "text" and isinstance(part.get("text"), str):
            mid = part.get("messageID") or "_"
            if mid not in by_message:
                by_message[mid] = []
                order.append(mid)
            by_message[mid].append(part["text"])
    text = "\n".join(by_message[order[-1]]).strip() if order else ""
    return (bool(text), text or "empty output")


def parse_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    candidates = [m.group(1)] if m else []
    # also try raw largest object
    braces = re.search(r"(\{.*\})", text, re.S)
    if braces:
        candidates.append(braces.group(1))
    candidates.append(text)
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def collect_x_snapshot(handle: str, headless: bool = True) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    url = f"https://x.com/{handle}"
    snapshot: dict[str, Any] = {
        "handle": handle,
        "url": url,
        "collected_at": now_jst().isoformat(),
        "profile_text": "",
        "posts": [],
        "errors": [],
    }
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4500)
            snapshot["profile_text"] = page.evaluate("() => document.body.innerText.slice(0, 6000)")
            posts = []
            seen = set()
            for _ in range(8):
                batch = page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('article')).map(a => {
                        const timeEl = a.querySelector('time');
                        const href = timeEl ? (timeEl.closest('a')?.getAttribute('href') || null) : null;
                        const get = (testid) => {
                            const el = a.querySelector(`[data-testid="${testid}"]`);
                            if (!el) return null;
                            return (el.getAttribute('aria-label') || el.innerText || '').trim();
                        };
                        const viewsA = a.querySelector('a[href*="/analytics"]');
                        return {
                            href,
                            time: timeEl ? timeEl.getAttribute('datetime') : null,
                            text: (a.innerText || '').slice(0, 1200),
                            reply: get('reply'),
                            retweet: get('retweet'),
                            like: get('like'),
                            views: viewsA ? (viewsA.getAttribute('aria-label') || viewsA.innerText || '').trim() : null,
                        };
                    })
                    """
                )
                for b in batch or []:
                    key = b.get("href") or (b.get("text") or "")[:120]
                    if key and key not in seen:
                        seen.add(key)
                        posts.append(b)
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(1600)
            snapshot["posts"] = posts[:40]
        except Exception as exc:
            snapshot["errors"].append(str(exc))
        finally:
            ctx.close()
    return snapshot


def parse_metric(label: str | None) -> int | None:
    if not label:
        return None
    # "73 件のいいね。いいねする" / "2,805 件の表示..."
    m = re.search(r"([0-9,]+)", label)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except Exception:
        return None


def extract_profile_numbers(profile_text: str) -> dict[str, Any]:
    nums: dict[str, Any] = {}
    m = re.search(r"([0-9,]+)\s*フォロー中", profile_text)
    if m:
        nums["following"] = int(m.group(1).replace(",", ""))
    m = re.search(r"([0-9,]+)\s*フォロワー", profile_text)
    if m:
        nums["followers"] = int(m.group(1).replace(",", ""))
    m = re.search(r"([0-9,]+)\s*件のポスト", profile_text)
    if m:
        nums["posts_total"] = int(m.group(1).replace(",", ""))
    m = re.search(r"(20\d{2})年(\d{1,2})月からXを利用しています", profile_text)
    if m:
        nums["joined"] = f"{m.group(1)}-{int(m.group(2)):02d}"
    return nums


def classify_post(text: str) -> list[str]:
    tags = []
    if "http" in text or "note.com" in text or "kingsworksub-jpg.github.io" in text:
        tags.append("link")
    if "?" in text or "？" in text:
        tags.append("question")
    if re.search(r"#\w+", text):
        tags.append("hashtag")
    if any(k in text for k in ["まとめました", "解説", "紹介", "ガイド"]):
        tags.append("promo")
    if not tags:
        tags.append("native_or_other")
    return tags


def compute_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    profile_text = snapshot.get("profile_text") or ""
    profile = extract_profile_numbers(profile_text)
    posts = snapshot.get("posts") or []
    rows = []
    for p in posts:
        text = p.get("text") or ""
        row = {
            "href": p.get("href"),
            "time": p.get("time"),
            "likes": parse_metric(p.get("like")),
            "replies": parse_metric(p.get("reply")),
            "reposts": parse_metric(p.get("retweet")),
            "views": parse_metric(p.get("views")),
            "tags": classify_post(text),
            "text_head": re.sub(r"\s+", " ", text).strip()[:140],
        }
        rows.append(row)

    def avg(key: str) -> float | None:
        vals = [r[key] for r in rows if isinstance(r.get(key), int)]
        return round(sum(vals) / len(vals), 2) if vals else None

    link_posts = [r for r in rows if "link" in r["tags"]]
    non_link_posts = [r for r in rows if "link" not in r["tags"]]
    zero_eng = [r for r in rows if (r.get("likes") or 0) == 0 and (r.get("replies") or 0) == 0 and (r.get("reposts") or 0) == 0]
    followers = profile.get("followers")
    following = profile.get("following")
    ratio = round(followers / following, 3) if isinstance(followers, int) and isinstance(following, int) and following else None

    state_signals = load_state_signals()
    metrics = {
        "profile": profile,
        "follow_ratio": ratio,
        "sample_size": len(rows),
        "averages": {
            "likes": avg("likes"),
            "replies": avg("replies"),
            "reposts": avg("reposts"),
            "views": avg("views"),
        },
        "link_post_ratio": round(len(link_posts) / len(rows), 3) if rows else None,
        "zero_engagement_ratio": round(len(zero_eng) / len(rows), 3) if rows else None,
        "link_vs_non_link_avg_views": {
            "link": avg_for(link_posts, "views"),
            "non_link": avg_for(non_link_posts, "views"),
        },
        "top_posts": sorted(rows, key=lambda r: ((r.get("likes") or 0), (r.get("views") or 0)), reverse=True)[:5],
        "state_signals": state_signals,
    }
    return metrics


def avg_for(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in rows if isinstance(r.get(key), int)]
    return round(sum(vals) / len(vals), 2) if vals else None


def load_state_signals() -> dict[str, Any]:
    signals: dict[str, Any] = {}
    likes = load_json(DATA_DIR / "x-likes-state.json", {})
    liked_ids = likes.get("liked_ids", {})
    signals["liked_ids_count"] = len(liked_ids) if isinstance(liked_ids, dict) else None

    replies = load_json(DATA_DIR / "x-replies-state.json", {})
    signals["replies_handled_count"] = len(replies.get("handled_ids", [])) if isinstance(replies.get("handled_ids"), list) else None
    signals["replies_daily_counts"] = replies.get("daily_counts", {})

    fr = load_json(DATA_DIR / "x-following-reply-state.json", {})
    replied_ids = fr.get("replied_ids", {})
    signals["following_replied_count"] = len(replied_ids) if isinstance(replied_ids, dict) else None
    signals["following_daily_counts"] = fr.get("daily_counts", {})

    unfo = load_json(DATA_DIR / "x-unfollow-candidates.json", [])
    signals["unfollow_candidates_count"] = len(unfo) if isinstance(unfo, list) else None

    log_path = DATA_DIR / "x-unfollow-log.jsonl"
    if log_path.exists():
        try:
            with log_path.open("r", encoding="utf-8") as f:
                signals["unfollow_log_lines"] = sum(1 for _ in f)
        except Exception:
            signals["unfollow_log_lines"] = None
    return signals


def build_llm_prompt(metrics: dict[str, Any], snapshot: dict[str, Any]) -> str:
    compact = {
        "profile": metrics.get("profile"),
        "follow_ratio": metrics.get("follow_ratio"),
        "sample_size": metrics.get("sample_size"),
        "averages": metrics.get("averages"),
        "link_post_ratio": metrics.get("link_post_ratio"),
        "zero_engagement_ratio": metrics.get("zero_engagement_ratio"),
        "link_vs_non_link_avg_views": metrics.get("link_vs_non_link_avg_views"),
        "top_posts": metrics.get("top_posts"),
        "state_signals": metrics.get("state_signals"),
        "recent_posts_head": [p.get("text_head") for p in metrics.get("top_posts", [])],
    }
    return (
        "あなたはX(Twitter)アカウント成長のコンサルタントです。"
        "以下の観測データをもとに、読み取り専用の診断をJSONで返してください。"
        "自動で実行してよい変更は提案に含めてもよいが、この出力自体は適用しません。"
        "必ず次のJSONキーを含めてください: "
        "summary, wins, issues, hypotheses, next_actions, guardrails, confidence。"
        "next_actions は最大5件、各要素は {title, reason, risk, metric, horizon_days}。"
        "事実と推測を分け、データ不足は明記する。日本語で簡潔に。\n\n"
        "```json\n" + json.dumps(compact, ensure_ascii=False, indent=2) + "\n```"
    )


def llm_diagnose(metrics: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    prompt = build_llm_prompt(metrics, snapshot)
    chain = resolve_chain(X_CONSULTING_CHAIN, "X_CONSULTING_MODEL_CHAIN", "X_CONSULTING_MODEL")
    attempts = []
    for model in chain:
        ok, payload = run_opencode(prompt, model=model, timeout=180)
        attempts.append({"model": model, "ok": ok, "error": None if ok else payload})
        if not ok:
            continue
        obj = parse_json_object(payload)
        if obj:
            obj["_model"] = model
            obj["_attempts"] = attempts
            return obj
        attempts[-1]["error"] = "invalid_json"
    return {"summary": "LLM診断は取得できませんでした（fail-safe）。", "_attempts": attempts, "confidence": "low"}


def render_report(date: str, metrics: dict[str, Any], diagnosis: dict[str, Any], snapshot: dict[str, Any], evaluation: dict[str, Any] | None = None) -> str:
    p = metrics.get("profile", {})
    avg = metrics.get("averages", {})
    ss = metrics.get("state_signals", {})
    lines = []
    lines.append(f"# X Consulting Daily Report ({date})")
    lines.append("")
    lines.append("## 対象")
    lines.append(f"- Handle: `@{snapshot.get('handle')}`")
    lines.append(f"- Collected at: {snapshot.get('collected_at')}")
    lines.append("")
    lines.append("## プロフィール/KPI")
    lines.append(f"- フォロワー: {p.get('followers', 'N/A')}")
    lines.append(f"- フォロー中: {p.get('following', 'N/A')}")
    lines.append(f"- フォロー/フォロワー比: {metrics.get('follow_ratio', 'N/A')}")
    lines.append(f"- 総投稿数: {p.get('posts_total', 'N/A')}")
    lines.append(f"- サンプル投稿数: {metrics.get('sample_size', 'N/A')}")
    lines.append(f"- 平均いいね: {avg.get('likes', 'N/A')}")
    lines.append(f"- 平均返信: {avg.get('replies', 'N/A')}")
    lines.append(f"- 平均RP: {avg.get('reposts', 'N/A')}")
    lines.append(f"- 平均表示: {avg.get('views', 'N/A')}")
    lines.append(f"- リンク投稿比率: {metrics.get('link_post_ratio', 'N/A')}")
    lines.append(f"- 無反応投稿比率: {metrics.get('zero_engagement_ratio', 'N/A')}")
    lines.append("")
    lines.append("## ローカル運用シグナル")
    for k in [
        "liked_ids_count", "replies_handled_count", "following_replied_count",
        "unfollow_candidates_count", "unfollow_log_lines",
    ]:
        lines.append(f"- {k}: {ss.get(k, 'N/A')}")
    lines.append("")
    lines.append("## 上位投稿（サンプル内）")
    for t in metrics.get("top_posts", [])[:5]:
        lines.append(f"- {t.get('time','')} | likes={t.get('likes')} replies={t.get('replies')} rp={t.get('reposts')} views={t.get('views')} | {t.get('text_head','')}")
    if not metrics.get("top_posts"):
        lines.append("- N/A")
    lines.append("")
    lines.append("## LLM診断（fail-safe）")
    lines.append(f"- model: {diagnosis.get('_model', 'N/A')}")
    lines.append(f"- confidence: {diagnosis.get('confidence', 'N/A')}")
    lines.append(f"- summary: {diagnosis.get('summary', 'N/A')}")
    if diagnosis.get("issues"):
        lines.append("- issues:")
        for i in diagnosis["issues"][:5]:
            lines.append(f"  - {i}")
    if diagnosis.get("next_actions"):
        lines.append("- next_actions:")
        for a in diagnosis["next_actions"][:5]:
            if isinstance(a, dict):
                lines.append(f"  - {a.get('title','')}: {a.get('reason','')} (metric={a.get('metric','')}, horizon={a.get('horizon_days','')}d, risk={a.get('risk','')})")
            else:
                lines.append(f"  - {a}")
    if diagnosis.get("_attempts"):
        lines.append("- attempts:")
        for at in diagnosis["_attempts"]:
            lines.append(f"  - {at.get('model')}: ok={at.get('ok')} err={at.get('error')}")
    lines.append("")
    lines.append("## Phase 4 効果検証（最新）")
    if isinstance(evaluation, dict):
        lines.append(f"- date: {evaluation.get('date')}")
        lines.append(f"- deployments_evaluated: {evaluation.get('deployments_evaluated')}")
        lines.append(f"- adopt: {evaluation.get('adopt')} / hold: {evaluation.get('hold')} / rollback: {evaluation.get('rollback')}")
        for r in (evaluation.get("results") or [])[:10]:
            dep = r.get("deployment_id")
            dec = r.get("decision")
            reasons = ",".join(r.get("reason") or [])
            lines.append(f"  - {dep}: {dec} ({reasons}) score={r.get('score')} evidence={r.get('evidence_count')}")
    else:
        lines.append("- N/A（まだ評価データがありません。`python scripts/x_verify.py` を実行）")
    lines.append("")
    lines.append("## 注意")
    lines.append("- Phase 1-2: 観測/分析/提案生成。Phase 3: レポートに基づくルールの自動調整。")
    lines.append("- 自動調整は `scripts/x_deploy.py --auto-safe` が allowlist / hard cap / step の範囲内で適用する。")
    lines.append("- KPI悪化時は `scripts/x_verify.py --apply-rollbacks` が自動ロールバックする。")
    lines.append("- X詳細アナリティクスが取得できない場合、観測可能な公開情報とローカル状態から推定します。")
    if snapshot.get("errors"):
        lines.append("- 収集エラー:")
        for e in snapshot["errors"]:
            lines.append(f"  - {e}")
    lines.append("")
    lines.append("## Phase 3 自動デプロイ")
    lines.append("- dry-run: `python scripts/x_deploy.py --proposal data/x-consulting/proposals/" + date + ".json --dry-run --auto-safe`")
    lines.append("- apply:   `python scripts/x_deploy.py --proposal data/x-consulting/proposals/" + date + ".json --auto-safe`")
    lines.append("- rollback:`python scripts/x_deploy.py --rollback <deployment_id>`")
    lines.append("- 注意: auto_safe=true のルール変更を、上下両方向に自動適用する（hard cap / min / step で制限）。")
    lines.append("")
    return "\n".join(lines)


def _load_managed_limits() -> dict[str, int]:
    try:
        obj = load_json(OUT_ROOT / "managed-limits.json", {})
        limits = obj.get("limits", {}) if isinstance(obj, dict) else {}
        return {k: int(v) for k, v in limits.items() if isinstance(k, str)}
    except Exception:
        return {}


def _load_managed_policies() -> dict[str, str]:
    try:
        obj = load_json(OUT_ROOT / "managed-limits.json", {})
        policies = obj.get("policies", {}) if isinstance(obj, dict) else {}
        return {k: str(v) for k, v in policies.items() if isinstance(k, str)}
    except Exception:
        return {}


def _deploy_allowlist() -> dict[str, dict[str, Any]]:
    try:
        from x_deploy import LIMIT_ALLOWLIST  # type: ignore
        return dict(LIMIT_ALLOWLIST)
    except Exception:
        return {
            "X_MAX_AUTO_REPLIES_PER_DAY": {"cap": 20, "min": 0, "default": 10, "step": 2, "type": "int"},
            "X_MAX_REPLIES_PER_DAY": {"cap": 20, "min": 0, "default": 10, "step": 2, "type": "int"},
            "X_FOLLOWUP_MAX_LIKES_PER_DAY": {"cap": 8, "min": 0, "default": 3, "step": 1, "type": "int"},
            "X_MAX_LIKES_PER_DAY": {"cap": 60, "min": 0, "default": 30, "step": 5, "type": "int"},
            "X_MAX_POSTS_PER_DAY": {"cap": 3, "min": 0, "default": 1, "step": 1, "type": "int"},
            "X_MIN_HOURS_BETWEEN_POSTS": {"cap": 24, "min": 2, "default": 8, "step": 2, "type": "int"},
            "X_DAY_INTERVAL_MIN": {"cap": 90, "min": 8, "default": 18, "step": 6, "type": "int"},
            "X_DAY_INTERVAL_MAX": {"cap": 180, "min": 12, "default": 45, "step": 10, "type": "int"},
            "X_NIGHT_INTERVAL_MIN": {"cap": 240, "min": 30, "default": 80, "step": 20, "type": "int"},
            "X_NIGHT_INTERVAL_MAX": {"cap": 360, "min": 60, "default": 150, "step": 30, "type": "int"},
            "X_LINK_PROBABILITY_PCT": {"cap": 70, "min": 0, "default": 35, "step": 10, "type": "int"},
        }


def _suggest_deploy_hints(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic, metrics-only rule changes. No LLM output used.

    2026-11-23: 「下げるだけ」から、レポートの内容に応じた上下両方向の
    自動調整へ。すべて auto_safe=True で、x_deploy.py の hard cap / step で
    暴走を防ぐ。投稿数上限・巡回間隔・リンク方針も対象。
    """
    allow = _deploy_allowlist()
    managed = _load_managed_limits()
    managed_policies = _load_managed_policies()
    sample = metrics.get("sample_size") or 0
    zero_ratio = metrics.get("zero_engagement_ratio")
    avg = metrics.get("averages") or {}
    views = avg.get("views")
    likes = avg.get("likes")
    replies = avg.get("replies")
    link_ratio = metrics.get("link_post_ratio")
    lv = metrics.get("link_vs_non_link_avg_views") or {}
    link_views = lv.get("link")
    nonlink_views = lv.get("non_link")
    hints: list[dict[str, Any]] = []

    def cur(key: str) -> int | None:
        if key in managed:
            try:
                return int(managed[key])
            except Exception:
                return None
        try:
            from x_automation_config import get_limit  # type: ignore
            return int(get_limit(key))
        except Exception:
            spec = allow.get(key) or {}
            default = spec.get("default", spec.get("cap"))
            return int(default) if isinstance(default, int) else None

    def add(key: str, target: int, rule: str, reason: str) -> None:
        spec = allow.get(key)
        if not spec:
            return
        before = cur(key)
        try:
            target_i = int(target)
        except Exception:
            return
        target_i = max(int(spec["min"]), min(int(spec["cap"]), target_i))
        step = int(spec.get("step", 1) or 1)
        if before is not None:
            if target_i > before:
                target_i = min(target_i, before + step)
            elif before - target_i > step * 2:
                target_i = before - step * 2
            if target_i == before:
                return
        hints.append({
            "type": "limit_adjust",
            "key": key,
            "value": target_i,
            "before": before,
            "direction": "raise" if before is not None and target_i > before else "lower",
            "auto_safe": True,
            "rule": rule,
            "reason": reason,
        })

    def set_policy(key: str, value: str, rule: str, reason: str) -> None:
        current = managed_policies.get(key)
        if current == value:
            return
        hints.append({
            "type": "policy_set",
            "key": key,
            "value": value,
            "before": current,
            "auto_safe": True,
            "rule": rule,
            "reason": reason,
        })

    def is_num(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    if not isinstance(sample, int) or sample < 5:
        # サンプル不足では数値を動かさない（誤学習を避ける）。
        return hints

    healthy = (
        is_num(zero_ratio) and zero_ratio <= 0.40
        and is_num(views) and views >= 150
    )
    struggling = (
        (is_num(zero_ratio) and zero_ratio >= 0.65)
        or (is_num(views) and views <= 60)
    )

    if healthy:
        reason = f"sample={sample} zero_ratio={zero_ratio} avg_views={views}"
        for key in ["X_MAX_AUTO_REPLIES_PER_DAY", "X_MAX_REPLIES_PER_DAY"]:
            before = cur(key)
            if before is not None:
                add(key, before + allow[key].get("step", 2), "R_HEALTHY_ENGAGEMENT", reason)
        before = cur("X_MAX_POSTS_PER_DAY")
        if before is not None:
            add("X_MAX_POSTS_PER_DAY", before + 1, "R_HEALTHY_ENGAGEMENT", reason)
        before = cur("X_MAX_LIKES_PER_DAY")
        if before is not None:
            add("X_MAX_LIKES_PER_DAY", before + 5, "R_HEALTHY_ENGAGEMENT", reason)
        # 反応が良いので巡回間隔を少し詰める（機会損失を減らす）。
        add("X_DAY_INTERVAL_MIN", (cur("X_DAY_INTERVAL_MIN") or 18) - 6, "R_HEALTHY_ENGAGEMENT", reason)
        add("X_DAY_INTERVAL_MAX", (cur("X_DAY_INTERVAL_MAX") or 45) - 10, "R_HEALTHY_ENGAGEMENT", reason)
    elif struggling:
        reason = f"sample={sample} zero_ratio={zero_ratio} avg_views={views}"
        for key in ["X_MAX_AUTO_REPLIES_PER_DAY", "X_MAX_REPLIES_PER_DAY"]:
            before = cur(key)
            if before is not None:
                add(key, before - allow[key].get("step", 2), "R_STRUGGLING_ENGAGEMENT", reason)
        before = cur("X_MAX_POSTS_PER_DAY")
        if before is not None:
            add("X_MAX_POSTS_PER_DAY", before - 1, "R_STRUGGLING_ENGAGEMENT", reason)
        before = cur("X_MAX_LIKES_PER_DAY")
        if before is not None:
            add("X_MAX_LIKES_PER_DAY", before - 5, "R_STRUGGLING_ENGAGEMENT", reason)
        # 動きを減らして様子を見る。
        add("X_DAY_INTERVAL_MIN", (cur("X_DAY_INTERVAL_MIN") or 18) + 6, "R_STRUGGLING_ENGAGEMENT", reason)
        add("X_DAY_INTERVAL_MAX", (cur("X_DAY_INTERVAL_MAX") or 45) + 10, "R_STRUGGLING_ENGAGEMENT", reason)
        add("X_NIGHT_INTERVAL_MIN", (cur("X_NIGHT_INTERVAL_MIN") or 80) + 20, "R_STRUGGLING_ENGAGEMENT", reason)
        add("X_NIGHT_INTERVAL_MAX", (cur("X_NIGHT_INTERVAL_MAX") or 150) + 30, "R_STRUGGLING_ENGAGEMENT", reason)

    # 返信が全く生まれないなら、フォローアップいいねの上限を下げる。
    if is_num(replies) and replies == 0:
        before = cur("X_FOLLOWUP_MAX_LIKES_PER_DAY")
        if before is not None:
            add("X_FOLLOWUP_MAX_LIKES_PER_DAY", before - 1, "R_NO_REPLIES",
                f"avg_replies={replies} sample={sample}")

    # リンク方針: 実測の「リンク vs 非リンク」表示数で切り替える。
    if is_num(link_views) and is_num(nonlink_views) and link_views > 0:
        if nonlink_views >= link_views * 2:
            set_policy(
                "X_LINK_POLICY", "native_then_first_reply", "R_LINK_NATIVE_WINS",
                f"non_link_avg_views={nonlink_views} vs link_avg_views={link_views}",
            )
            before = cur("X_LINK_PROBABILITY_PCT")
            if before is not None:
                add("X_LINK_PROBABILITY_PCT", min(before, 25), "R_LINK_NATIVE_WINS",
                    f"non_link_avg_views={nonlink_views} vs link_avg_views={link_views}")
        elif link_views >= nonlink_views * 1.3:
            set_policy(
                "X_LINK_POLICY", "inline", "R_LINK_INLINE_WINS",
                f"link_avg_views={link_views} vs non_link_avg_views={nonlink_views}",
            )
            before = cur("X_LINK_PROBABILITY_PCT")
            if before is not None:
                add("X_LINK_PROBABILITY_PCT", max(before, 55), "R_LINK_INLINE_WINS",
                    f"link_avg_views={link_views} vs non_link_avg_views={nonlink_views}")
    elif is_num(link_ratio) and link_ratio >= 0.8:
        # リンクだらけで比較データが無い場合も、まずネイティブ優先に寄せる。
        set_policy(
            "X_LINK_POLICY", "native_then_first_reply", "R_LINK_RATIO_HIGH",
            f"link_post_ratio={link_ratio}",
        )
        before = cur("X_LINK_PROBABILITY_PCT")
        if before is not None:
            add("X_LINK_PROBABILITY_PCT", min(before, 25), "R_LINK_RATIO_HIGH",
                f"link_post_ratio={link_ratio}")

    # 間隔の上下関係が壊れないように補正する。
    dmin, dmax = cur("X_DAY_INTERVAL_MIN"), cur("X_DAY_INTERVAL_MAX")
    if dmin is not None and dmax is not None and dmax <= dmin:
        add("X_DAY_INTERVAL_MAX", dmin + 10, "R_INTERVAL_SANITY", f"day {dmin}..{dmax}")
    nmin, nmax = cur("X_NIGHT_INTERVAL_MIN"), cur("X_NIGHT_INTERVAL_MAX")
    if nmin is not None and nmax is not None and nmax <= nmin:
        add("X_NIGHT_INTERVAL_MAX", nmin + 30, "R_INTERVAL_SANITY", f"night {nmin}..{nmax}")

    return hints


def build_proposal(date: str, metrics: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, Any]:
    actions = diagnosis.get("next_actions") or []
    norm_actions = []
    hints = _suggest_deploy_hints(metrics)
    hint_by_key = {h.get("key"): h for h in hints if isinstance(h, dict)}
    for i, a in enumerate(actions[:10], 1):
        base = {
            "id": f"{date}-{i:02d}",
            "title": "",
            "reason": "",
            "risk": "unknown",
            "metric": "",
            "horizon_days": 7,
            "status": "proposed",
            "requires_approval": True,
            "auto_apply": False,
        }
        if isinstance(a, dict):
            base.update({
                "title": a.get("title", ""),
                "reason": a.get("reason", ""),
                "risk": a.get("risk", "unknown"),
                "metric": a.get("metric", ""),
                "horizon_days": a.get("horizon_days", 7),
            })
        else:
            base["title"] = str(a)
        # Attach deterministic rule hints when the action text/metric references the same rule.
        text_blob = f"{base.get('title','')} {base.get('reason','')} {base.get('metric','')}".lower()
        for key, hint in hint_by_key.items():
            if (
                key.lower() in text_blob
                or ("返信" in text_blob and "reply" in key.lower())
                or ("いいね" in text_blob and "like" in key.lower())
                or ("投稿数" in text_blob and "post" in key.lower())
                or ("リンク" in text_blob and ("link" in key.lower() or "LINK_POLICY" in key))
            ):
                base["deploy"] = hint
                base["auto_apply"] = bool(hint.get("auto_safe"))
                base["requires_approval"] = not bool(hint.get("auto_safe"))
                break
        norm_actions.append(base)

    # Add unmatched rule changes as explicit, auditable actions (auto-applied if auto_safe).
    attached_keys = {a.get("deploy", {}).get("key") for a in norm_actions if isinstance(a.get("deploy"), dict)}
    for hint in hints:
        if hint.get("key") in attached_keys:
            continue
        direction = hint.get("direction")
        if hint.get("type") == "policy_set":
            title = f"自動ルール調整: {hint.get('key')} → {hint.get('value')}"
        else:
            arrow = "↑" if direction == "raise" else "↓"
            title = f"自動ルール調整: {hint.get('key')} {hint.get('before')} {arrow} {hint.get('value')}"
        norm_actions.append({
            "id": f"{date}-{len(norm_actions)+1:02d}",
            "title": title,
            "reason": hint.get("reason", ""),
            "risk": "low",
            "metric": hint.get("rule", ""),
            "horizon_days": 7,
            "status": "proposed",
            "requires_approval": not bool(hint.get("auto_safe")),
            "auto_apply": bool(hint.get("auto_safe")),
            "deploy": hint,
        })

    return {
        "date": date,
        "generated_at": now_jst().isoformat(),
        "model": diagnosis.get("_model"),
        "confidence": diagnosis.get("confidence"),
        "summary": diagnosis.get("summary"),
        "issues": diagnosis.get("issues", []),
        "guardrails": diagnosis.get("guardrails", []),
        "actions": norm_actions,
        "rule_changes": hints,
        "deploy_hints_generated": len(hints),
        "deploy_hints_rule_based": True,
        "phase": "phase3-auto-tune",
    }


def render_proposal_md(proposal: dict[str, Any]) -> str:
    lines = [f"# X Consulting Proposal ({proposal.get('date')})", ""]
    lines.append(f"- generated_at: {proposal.get('generated_at')}")
    lines.append(f"- model: {proposal.get('model')}")
    lines.append(f"- confidence: {proposal.get('confidence')}")
    lines.append(f"- phase: {proposal.get('phase')}")
    lines.append("")
    lines.append("## Summary")
    lines.append(str(proposal.get("summary", "N/A")))
    lines.append("")
    lines.append("## Issues")
    for i in proposal.get("issues", []) or ["N/A"]:
        lines.append(f"- {i}")
    lines.append("")
    lines.append("## Proposed Actions (approval required)")
    for a in proposal.get("actions", []):
        lines.append(f"- **{a.get('id')} {a.get('title')}**")
        lines.append(f"  - reason: {a.get('reason')}")
        lines.append(f"  - metric: {a.get('metric')}")
        lines.append(f"  - horizon_days: {a.get('horizon_days')}")
        lines.append(f"  - risk: {a.get('risk')}")
        lines.append(f"  - status: {a.get('status')} / requires_approval={a.get('requires_approval')} / auto_apply={a.get('auto_apply')}")
        dep = a.get("deploy")
        if isinstance(dep, dict):
            lines.append(f"  - deploy_hint: type={dep.get('type')} key={dep.get('key')} value={dep.get('value')} before={dep.get('before')} auto_safe={dep.get('auto_safe')} rule={dep.get('rule')}")
    if not proposal.get("actions"):
        lines.append("- N/A")
    lines.append("")
    lines.append("## Guardrails")
    for g in proposal.get("guardrails", []) or ["N/A"]:
        lines.append(f"- {g}")
    lines.append("")
    lines.append("## Rule Changes (auto-applied when auto_safe=true)")
    for h in proposal.get("rule_changes", []) or []:
        lines.append(
            f"- {h.get('type')} {h.get('key')}: {h.get('before')} → {h.get('value')} "
            f"(rule={h.get('rule')}, auto_safe={h.get('auto_safe')}, reason={h.get('reason')})"
        )
    if not proposal.get("rule_changes"):
        lines.append("- N/A（数値・方針の変更提案なし）")
    lines.append("")
    lines.append("## Phase 3 Auto Deploy")
    date = proposal.get("date", "YYYY-MM-DD")
    lines.append(f"- dry-run: `python scripts/x_deploy.py --proposal data/x-consulting/proposals/{date}.json --dry-run --auto-safe`")
    lines.append(f"- apply:   `python scripts/x_deploy.py --proposal data/x-consulting/proposals/{date}.json --auto-safe`")
    lines.append("- rollback:`python scripts/x_deploy.py --rollback <deployment_id>`")
    lines.append("- allowlist + hard cap / min / step の範囲内で、上下両方向に自動調整する。投稿数上限・巡回間隔・リンク方針も対象。")
    lines.append("- KPIが悪化したdeploymentは `python scripts/x_verify.py --apply-rollbacks` で自動ロールバックする。")
    lines.append("")
    lines.append("> Phase 3: レポートに基づくルールの自動調整＋自動ロールバック。")
    return "\n".join(lines)


def load_latest_evaluation() -> dict[str, Any] | None:
    p = OUT_ROOT / "evaluations"
    if not p.exists():
        return None
    files = sorted(p.glob("*.json"))
    if not files:
        return None
    obj = load_json(files[-1], None)
    return obj if isinstance(obj, dict) else None


def load_analysis_history(limit: int = 90) -> list[dict[str, Any]]:
    items = []
    for p in sorted(ANALYSIS_DIR.glob("*.json")):
        obj = load_json(p, {})
        if isinstance(obj, dict) and obj.get("date"):
            items.append(obj)
    items.sort(key=lambda x: x.get("date", ""))
    return items[-limit:]


def render_html_report(date: str, metrics: dict[str, Any], diagnosis: dict[str, Any], snapshot: dict[str, Any], evaluation: dict[str, Any] | None = None, proposal: dict[str, Any] | None = None) -> str:
    history = load_analysis_history()
    # ensure current date is present/updated
    cur = {"date": date, "metrics": metrics, "diagnosis": diagnosis}
    replaced = False
    for i, h in enumerate(history):
        if h.get("date") == date:
            history[i] = cur
            replaced = True
            break
    if not replaced:
        history.append(cur)
    history.sort(key=lambda x: x.get("date", ""))

    labels = [h.get("date") for h in history]
    followers = [((h.get("metrics") or {}).get("profile") or {}).get("followers") for h in history]
    following = [((h.get("metrics") or {}).get("profile") or {}).get("following") for h in history]
    ratios = [(h.get("metrics") or {}).get("follow_ratio") for h in history]
    avg_likes = [((h.get("metrics") or {}).get("averages") or {}).get("likes") for h in history]
    avg_replies = [((h.get("metrics") or {}).get("averages") or {}).get("replies") for h in history]
    avg_views = [((h.get("metrics") or {}).get("averages") or {}).get("views") for h in history]
    link_ratio = [(h.get("metrics") or {}).get("link_post_ratio") for h in history]
    zero_ratio = [(h.get("metrics") or {}).get("zero_engagement_ratio") for h in history]

    latest = history[-1] if history else cur
    lm = latest.get("metrics") or {}
    lp = lm.get("profile") or {}
    la = lm.get("averages") or {}
    ls = lm.get("state_signals") or {}
    ld = latest.get("diagnosis") or {}

    def esc(x: Any) -> str:
        return html.escape("" if x is None else str(x), quote=True)

    def _cell(label: str, value: Any) -> str:
        """スマホでは表を縦積みにするため、各セルにラベルを付けておく。"""
        return f"<td data-label='{esc(label)}:'>{esc(value)}</td>"

    top_posts = lm.get("top_posts") or []
    top_rows = "".join(
        "<tr>"
        + _cell("time", p.get("time", ""))
        + _cell("likes", p.get("likes"))
        + _cell("replies", p.get("replies"))
        + _cell("RP", p.get("reposts"))
        + _cell("views", p.get("views"))
        + _cell("text", p.get("text_head", ""))
        + "</tr>"
        for p in top_posts[:10]
    ) or "<tr><td colspan='6'>N/A</td></tr>"

    issues = ld.get("issues") or []
    actions = ld.get("next_actions") or []
    issues_html = "".join(f"<li>{esc(i)}</li>" for i in issues[:8]) or "<li>N/A</li>"
    actions_html = ""
    for a in actions[:8]:
        if isinstance(a, dict):
            actions_html += f"<li><b>{esc(a.get('title',''))}</b><br><span class='muted'>{esc(a.get('reason',''))}</span><br><span class='pill'>metric: {esc(a.get('metric',''))}</span> <span class='pill'>horizon: {esc(a.get('horizon_days',''))}d</span> <span class='pill'>risk: {esc(a.get('risk',''))}</span></li>"
        else:
            actions_html += f"<li>{esc(a)}</li>"
    actions_html = actions_html or "<li>N/A</li>"

    if proposal is None:
        try:
            proposal = load_json(PROPOSAL_DIR / f"{date}.json", {})
        except Exception:
            proposal = {}
    rule_changes = (proposal or {}).get("rule_changes") or []
    rule_rows = ""
    for h in rule_changes[:20]:
        arrow = "↑" if h.get("direction") == "raise" else ("↓" if h.get("direction") == "lower" else "→")
        rule_rows += (
            "<tr>"
            + _cell("rule", h.get("rule"))
            + _cell("key", h.get("key"))
            + _cell("before", h.get("before"))
            + _cell("after", f"{arrow} {h.get('value')}")
            + _cell("auto", "yes" if h.get("auto_safe") else "no")
            + _cell("reason", h.get("reason"))
            + "</tr>"
        )
    rule_html = (
        "<div class='table-wrap'><table class='responsive'><thead><tr>"
        "<th>rule</th><th>key</th><th>before</th><th>after</th><th>auto</th><th>reason</th>"
        f"</tr></thead><tbody>{rule_rows}</tbody></table></div>"
        if rule_rows else "<p class='muted'>今回の自動調整提案はありません（サンプル不足、または変化なし）。</p>"
    )

    attempts = ld.get("_attempts") or []
    attempts_html = "".join(
        f"<li>{esc(a.get('model'))}: ok={esc(a.get('ok'))} {('err='+esc(a.get('error'))) if a.get('error') else ''}</li>"
        for a in attempts
    ) or "<li>N/A</li>"

    eval_html = "<p class='muted'>N/A（まだ評価データがありません）</p>"
    if isinstance(evaluation, dict):
        rows = "".join(
            "<tr>"
            + _cell("deployment", r.get("deployment_id"))
            + _cell("decision", r.get("decision"))
            + _cell("score", r.get("score"))
            + _cell("evidence", r.get("evidence_count"))
            + _cell("reason", ",".join(r.get("reason") or []))
            + "</tr>"
            for r in (evaluation.get("results") or [])[:20]
        ) or "<tr><td colspan='5'>N/A</td></tr>"
        eval_html = (
            f"<p><b>date:</b> {esc(evaluation.get('date'))} / "
            f"<b>adopt:</b> {esc(evaluation.get('adopt'))} "
            f"<b>hold:</b> {esc(evaluation.get('hold'))} "
            f"<b>rollback:</b> {esc(evaluation.get('rollback'))}</p>"
            f"<div class='table-wrap'><table class='responsive'><thead><tr><th>deployment</th><th>decision</th><th>score</th><th>evidence</th><th>reason</th></tr></thead><tbody>{rows}</tbody></table></div>"
        )

    data_json = json.dumps({
        "labels": labels, "followers": followers, "following": following, "ratios": ratios,
        "avg_likes": avg_likes, "avg_replies": avg_replies, "avg_views": avg_views,
        "link_ratio": link_ratio, "zero_ratio": zero_ratio,
    }, ensure_ascii=False)

    report_html = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>X Accounting Reports - @{esc(snapshot.get('handle'))}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root{{--bg:#f4f7fb;--card:#fff;--text:#182230;--muted:#5b6b7f;--line:#dbe5f0;--accent:#1d9bf0;--good:#1a7f37;--warn:#b54708;}}
    *,*::before,*::after{{box-sizing:border-box}}
    html,body{{max-width:100%;overflow-x:hidden}}
    body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Kaku Gothic ProN",Meiryo,sans-serif;background:var(--bg);color:var(--text);line-height:1.65}}
    .wrap{{width:100%;max-width:1280px;margin:0 auto;padding:14px}}
    @media(min-width:768px){{.wrap{{padding:24px}}}}
    h1{{margin:0 0 6px;font-size:clamp(20px,4.5vw,28px);overflow-wrap:anywhere}}
    .sub{{color:var(--muted);margin-bottom:18px;font-size:13px;overflow-wrap:anywhere}}
    .grid{{display:grid;gap:14px;min-width:0}}
    /* min(100%, Npx) で、スマホの狭い画面では1列に崩れるようにする（従来の minmax(360px,1fr) が横スクロールの原因） */
    .kpis{{grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));margin-bottom:14px}}
    .charts{{grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));margin-bottom:14px}}
    .two{{grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr));margin-bottom:14px}}
    .card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:0 1px 2px rgba(0,0,0,.03);min-width:0;overflow-wrap:anywhere}}
    .kpi .label{{color:var(--muted);font-size:12px}} .kpi .value{{font-size:clamp(20px,5vw,28px);font-weight:700;margin-top:6px}} .kpi .delta{{font-size:12px;color:var(--muted);margin-top:4px;overflow-wrap:anywhere}}
    h2{{font-size:16px;margin:0 0 12px;overflow-wrap:anywhere}}
    .table-wrap{{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}}
    table{{width:100%;border-collapse:collapse;font-size:13px;table-layout:auto}}
    th,td{{padding:8px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left;overflow-wrap:anywhere;word-break:break-word}}
    th{{color:var(--muted);font-weight:600}}
    /* Chart.js はキャンバスに固定px幅を書き込むため、親で高さを固定して幅を100%に抑制する */
    .chart-box{{position:relative;width:100%;height:260px}}
    @media(min-width:768px){{.chart-box{{height:320px}}}}
    canvas{{max-width:100%!important;max-height:100%!important}}
    ul{{margin:0;padding-left:18px}} li{{margin:6px 0;overflow-wrap:anywhere}}
    .muted{{color:var(--muted)}}
    .pill{{display:inline-block;background:#eef6ff;color:#0b5cad;border-radius:999px;padding:2px 8px;font-size:11px;margin:2px 4px 2px 0}}
    code{{overflow-wrap:anywhere;word-break:break-all}}
    @media(max-width:640px){{
      /* 表は見出しを隠して1行1カードの縦積みにする。長文もラベル付きで折り返す */
      table.responsive thead{{display:none}}
      table.responsive,table.responsive tbody,table.responsive tr,table.responsive td{{display:block;width:100%}}
      table.responsive tr{{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;padding:4px}}
      table.responsive td{{border-bottom:1px dotted var(--line);padding:6px 8px}}
      table.responsive td:last-child{{border-bottom:0}}
      table.responsive td::before{{content:attr(data-label);display:block;color:var(--muted);font-size:11px;font-weight:600}}
      .chart-box{{height:220px}}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>X Account Consulting Report</h1>
    <div class="sub">@{esc(snapshot.get('handle'))} / 最終更新: {esc(now_jst().strftime('%Y-%m-%d %H:%M JST'))} / 対象日: {esc(date)} / レポートに基づく自動改善エコシステム（数値・投稿・リンク方針）</div>

    <div class="grid kpis">
      <div class="card kpi"><div class="label">フォロワー</div><div class="value">{esc(lp.get('followers','N/A'))}</div><div class="delta">フォロー中 {esc(lp.get('following','N/A'))}</div></div>
      <div class="card kpi"><div class="label">フォロー比率</div><div class="value">{esc(lm.get('follow_ratio','N/A'))}</div><div class="delta">followers / following</div></div>
      <div class="card kpi"><div class="label">平均表示</div><div class="value">{esc(la.get('views','N/A'))}</div><div class="delta">サンプル {esc(lm.get('sample_size','N/A'))} 件</div></div>
      <div class="card kpi"><div class="label">平均いいね</div><div class="value">{esc(la.get('likes','N/A'))}</div><div class="delta">平均返信 {esc(la.get('replies','N/A'))}</div></div>
      <div class="card kpi"><div class="label">リンク投稿比率</div><div class="value">{esc(lm.get('link_post_ratio','N/A'))}</div><div class="delta">無反応比率 {esc(lm.get('zero_engagement_ratio','N/A'))}</div></div>
      <div class="card kpi"><div class="label">運用シグナル</div><div class="value">{esc(ls.get('liked_ids_count','N/A'))}</div><div class="delta">累積いいねID数（ローカル状態）</div></div>
    </div>

    <div class="grid charts">
      <div class="card"><h2>フォロワー/フォロー中 推移</h2><div class="chart-box"><canvas id="c1"></canvas></div></div>
      <div class="card"><h2>平均エンゲージメント推移</h2><div class="chart-box"><canvas id="c2"></canvas></div></div>
      <div class="card"><h2>投稿品質比率推移</h2><div class="chart-box"><canvas id="c3"></canvas></div></div>
      <div class="card"><h2>最新運用シグナル</h2>
        <div class="table-wrap"><table class="responsive">
          <thead><tr><th>指標</th><th>値</th></tr></thead>
          <tbody>
          <tr><td>liked_ids_count</td>{_cell("値", ls.get('liked_ids_count','N/A'))}</tr>
          <tr><td>replies_handled_count</td>{_cell("値", ls.get('replies_handled_count','N/A'))}</tr>
          <tr><td>following_replied_count</td>{_cell("値", ls.get('following_replied_count','N/A'))}</tr>
          <tr><td>unfollow_candidates_count</td>{_cell("値", ls.get('unfollow_candidates_count','N/A'))}</tr>
          <tr><td>unfollow_log_lines</td>{_cell("値", ls.get('unfollow_log_lines','N/A'))}</tr>
          </tbody>
        </table></div>
      </div>
    </div>

    <div class="grid two">
      <div class="card"><h2>LLM診断サマリー</h2>
        <p><b>model:</b> {esc(ld.get('_model','N/A'))} / <b>confidence:</b> {esc(ld.get('confidence','N/A'))}</p>
        <p>{esc(ld.get('summary','N/A'))}</p>
        <h2>課題</h2><ul>{issues_html}</ul>
      </div>
      <div class="card"><h2>次アクション（LLM提案）</h2><ul>{actions_html}</ul>
        <h2>LLM試行ログ</h2><ul>{attempts_html}</ul>
      </div>
    </div>

    <div class="card" style="margin-top:16px"><h2>自動ルール調整（レポート→実運用）</h2>
      {rule_html}
      <p class="muted">allowlist / hard cap / min / step の範囲内で、KPIに応じて上下両方向に自動適用。投稿数上限・巡回間隔・リンク方針も含む。</p>
    </div>

    <div class="card"><h2>上位投稿（最新サンプル）</h2>
      <div class="table-wrap"><table class="responsive"><thead><tr><th>time</th><th>likes</th><th>replies</th><th>RP</th><th>views</th><th>text</th></tr></thead><tbody>{top_rows}</tbody></table></div>
    </div>

    <div class="card" style="margin-top:16px"><h2>Phase 4 効果検証（最新）</h2>
      {eval_html}
      <p class="muted">KPIが明確に悪化したdeploymentは、日次ランナーが <code>python scripts/x_verify.py --apply-rollbacks</code> で自動ロールバックします。</p>
    </div>

    <div class="card" style="margin-top:16px"><h2>Phase 3 自動デプロイ</h2>
      <ul>
        <li><b>dry-run:</b> <code>python scripts/x_deploy.py --proposal data/x-consulting/proposals/{esc(date)}.json --dry-run --auto-safe</code></li>
        <li><b>apply:</b> <code>python scripts/x_deploy.py --proposal data/x-consulting/proposals/{esc(date)}.json --auto-safe</code></li>
        <li><b>rollback:</b> <code>python scripts/x_deploy.py --rollback &lt;deployment_id&gt;</code></li>
        <li class="muted">allowlist かつ <code>auto_safe=true</code> のルール変更を、上下両方向に自動適用。hard cap / min / step で暴走を防ぐ。</li>
      </ul>
    </div>
  </div>
<script>
const D = {data_json};
const base = {{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},plugins:{{legend:{{position:'bottom'}}}}}};
new Chart(document.getElementById('c1'), {{type:'line',data:{{labels:D.labels,datasets:[
  {{label:'Followers',data:D.followers,borderColor:'#1d9bf0',tension:.2}},
  {{label:'Following',data:D.following,borderColor:'#f59e0b',tension:.2}},
  {{label:'Ratio',data:D.ratios,borderColor:'#10b981',tension:.2,yAxisID:'y1'}}
]}},options:{{...base,scales:{{y:{{beginAtZero:false}},y1:{{position:'right',beginAtZero:true,grid:{{drawOnChartArea:false}}}}}}}}}});
new Chart(document.getElementById('c2'), {{type:'line',data:{{labels:D.labels,datasets:[
  {{label:'Avg Views',data:D.avg_views,borderColor:'#6366f1',tension:.2}},
  {{label:'Avg Likes',data:D.avg_likes,borderColor:'#ef4444',tension:.2}},
  {{label:'Avg Replies',data:D.avg_replies,borderColor:'#14b8a6',tension:.2}}
]}},options:{{...base,scales:{{y:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('c3'), {{type:'line',data:{{labels:D.labels,datasets:[
  {{label:'Link Post Ratio',data:D.link_ratio,borderColor:'#8b5cf6',tension:.2}},
  {{label:'Zero Engagement Ratio',data:D.zero_ratio,borderColor:'#f97316',tension:.2}}
]}},options:{{...base,scales:{{y:{{beginAtZero:true,max:1}}}}}}}});
</script>
</body>
</html>"""
    return report_html


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=jst_date_str())
    ap.add_argument("--handle", default=TARGET_HANDLE)
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Phase1: no deploy; accepted for compatibility")
    args = ap.parse_args()

    ensure_dirs()
    headless = False if args.headed else True

    mutex = acquire_mutex(timeout_ms=15000)
    if mutex is False:
        print("[!] could not acquire x jobs mutex; aborting to avoid profile conflict")
        return 2

    try:
        snapshot = collect_x_snapshot(args.handle, headless=headless)
        metrics = compute_metrics(snapshot)
        diagnosis = {"summary": "LLM skipped", "confidence": "n/a"}
        if not args.skip_llm:
            diagnosis = llm_diagnose(metrics, snapshot)

        snapshot_path = SNAP_DIR / f"{args.date}.json"
        analysis_path = ANALYSIS_DIR / f"{args.date}.json"
        report_path = REPORT_DIR / f"{args.date}.md"

        save_json(snapshot_path, snapshot)
        save_json(analysis_path, {"date": args.date, "metrics": metrics, "diagnosis": diagnosis})
        evaluation = load_latest_evaluation()
        proposal = build_proposal(args.date, metrics, diagnosis)
        report = render_report(args.date, metrics, diagnosis, snapshot, evaluation=evaluation)
        report_path.write_text(report, encoding="utf-8")
        html_report = render_html_report(args.date, metrics, diagnosis, snapshot, evaluation=evaluation, proposal=proposal)
        HTML_REPORT_PATH.write_text(html_report, encoding="utf-8")

        proposal_json_path = PROPOSAL_DIR / f"{args.date}.json"
        proposal_md_path = PROPOSAL_DIR / f"{args.date}.md"
        save_json(proposal_json_path, proposal)
        proposal_md_path.write_text(render_proposal_md(proposal), encoding="utf-8")

        state = load_json(STATE_PATH, {})
        state["last_run_at"] = now_jst().isoformat()
        state["last_date"] = args.date
        state["last_report"] = str(report_path.relative_to(BASE)).replace("\\", "/")
        state["last_html_report"] = str(HTML_REPORT_PATH.relative_to(BASE)).replace("\\", "/")
        state["last_snapshot"] = str(snapshot_path.relative_to(BASE)).replace("\\", "/")
        state["last_analysis"] = str(analysis_path.relative_to(BASE)).replace("\\", "/")
        state["last_proposal_json"] = str(proposal_json_path.relative_to(BASE)).replace("\\", "/")
        state["last_proposal_md"] = str(proposal_md_path.relative_to(BASE)).replace("\\", "/")
        save_json(STATE_PATH, state)

        print(f"[ok] report: {report_path}")
        print(f"[ok] html: {HTML_REPORT_PATH}")
        print(f"[ok] proposal: {proposal_json_path}")
        print(f"[ok] snapshot: {snapshot_path}")
        print(f"[ok] analysis: {analysis_path}")
        return 0
    finally:
        release_mutex(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
