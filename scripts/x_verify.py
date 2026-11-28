# -*- coding: utf-8 -*-
"""Phase 4: effect verification for X consulting deployments.

Reads deployment records and daily analyses, compares baseline/follow-up KPIs,
and outputs adopt/hold/rollback recommendations.

Safety:
- deterministic rules only (no LLM)
- default is recommend-only; does NOT apply rollback unless --apply-rollbacks
- rollback application uses x_deploy.rollback_deployment()
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
OUT_ROOT = BASE / "data" / "x-consulting"
ANALYSIS_DIR = OUT_ROOT / "analyses"
DEPLOY_DIR = OUT_ROOT / "deployments"
EVAL_DIR = OUT_ROOT / "evaluations"
STATE_PATH = OUT_ROOT / "state.json"
BLOG_HISTORY_DIR = BASE / "data" / "blog-consulting" / "history"
# ブログ指標は source が週次更新のものが多く、X より長い観測窓が必要。
BLOG_PROMPT_HORIZON_DAYS = 14

# KPI direction: +1 means higher is better, -1 means lower is better.
KPI_DIRECTIONS = {
    "followers": 1,
    "follow_ratio": 1,
    "avg_likes": 1,
    "avg_replies": 1,
    "avg_views": 1,
    "zero_engagement_ratio": -1,
    "link_post_ratio": -1,  # lower is generally better for engagement; treat cautiously
}

DEFAULT_HORIZON_DAYS = 7
MIN_SAMPLE_SIZE = 5


def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_dirs() -> None:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)


def parse_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=9)))
    except Exception:
        return None


def load_analyses() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not ANALYSIS_DIR.exists():
        return out
    for p in sorted(ANALYSIS_DIR.glob("*.json")):
        obj = load_json(p, {})
        if isinstance(obj, dict) and obj.get("date"):
            out[str(obj["date"])] = obj
    return out


def load_deployments() -> list[dict[str, Any]]:
    if not DEPLOY_DIR.exists():
        return []
    items = []
    for p in sorted(DEPLOY_DIR.glob("*.json")):
        if p.name.endswith("-rollback.json"):
            continue
        obj = load_json(p, {})
        if isinstance(obj, dict) and obj.get("deployment_id"):
            obj["_path"] = str(p)
            items.append(obj)
    return items


def metric_snapshot(analysis: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        return {}
    m = analysis.get("metrics") or {}
    p = m.get("profile") or {}
    a = m.get("averages") or {}
    # 相対指標は判定スコアには入れず、baseline/followup の客観的な参考値として残す。
    # （ロールバック判定の挙動を変えずに、規模に依存しない比較材料をそろえる）
    r = m.get("relative") or {}
    return {
        "followers": p.get("followers"),
        "follow_ratio": m.get("follow_ratio"),
        "avg_likes": a.get("likes"),
        "avg_replies": a.get("replies"),
        "avg_views": a.get("views"),
        "zero_engagement_ratio": m.get("zero_engagement_ratio"),
        "link_post_ratio": m.get("link_post_ratio"),
        "sample_size": m.get("sample_size"),
        "like_rate_pct": r.get("like_rate_pct"),
        "engagement_rate_pct": r.get("engagement_rate_pct"),
        "views_per_follower": r.get("views_per_follower"),
        "likes_per_100_followers": r.get("likes_per_100_followers"),
    }


def delta(before: Any, after: Any) -> float | None:
    try:
        if before is None or after is None:
            return None
        return round(float(after) - float(before), 4)
    except Exception:
        return None


def evaluate_deployment(dep: dict[str, Any], analyses: dict[str, dict[str, Any]], today: str, horizon_days: int) -> dict[str, Any]:
    dep_id = dep.get("deployment_id")
    dep_date = dep.get("date")
    dep_dt = parse_date(dep_date) if isinstance(dep_date, str) else None
    today_dt = parse_date(today)
    applied = bool(dep.get("applied"))

    eval_item: dict[str, Any] = {
        "deployment_id": dep_id,
        "date": dep_date,
        "applied": applied,
        "rolled_back_at": dep.get("rolled_back_at"),
        "changes": dep.get("changes", []),
        "horizon_days": horizon_days,
        "decision": "hold",
        "reason": [],
        "kpis": {},
    }

    if not applied:
        eval_item["decision"] = "hold"
        eval_item["reason"].append("not_applied")
        return eval_item
    if dep.get("rolled_back_at"):
        eval_item["decision"] = "hold"
        eval_item["reason"].append("already_rolled_back")
        return eval_item
    if not dep_dt or not today_dt:
        eval_item["reason"].append("invalid_date")
        return eval_item

    age_days = (today_dt - dep_dt).days
    eval_item["age_days"] = age_days
    if age_days < horizon_days:
        eval_item["decision"] = "hold"
        eval_item["reason"].append(f"insufficient_horizon:{age_days}/{horizon_days}")
        return eval_item

    # Baseline: analysis on deploy date, else nearest previous available.
    baseline_date = None
    for d in sorted(analyses.keys()):
        if d <= dep_date:
            baseline_date = d
    # Follow-up: latest analysis on/after deploy+horizon, else latest available.
    target_follow = (dep_dt + timedelta(days=horizon_days)).strftime("%Y-%m-%d")
    follow_date = None
    for d in sorted(analyses.keys()):
        if d >= target_follow:
            follow_date = d
            break
    if follow_date is None and analyses:
        follow_date = sorted(analyses.keys())[-1]

    base_snap = metric_snapshot(analyses.get(baseline_date) if baseline_date else None)
    follow_snap = metric_snapshot(analyses.get(follow_date) if follow_date else None)
    eval_item["baseline_date"] = baseline_date
    eval_item["followup_date"] = follow_date
    eval_item["baseline"] = base_snap
    eval_item["followup"] = follow_snap

    if not baseline_date or not follow_date:
        eval_item["reason"].append("missing_analysis")
        return eval_item
    if follow_date <= baseline_date:
        eval_item["reason"].append("no_followup_after_baseline")
        return eval_item

    base_sample = base_snap.get("sample_size")
    follow_sample = follow_snap.get("sample_size")
    if not isinstance(follow_sample, int) or follow_sample < MIN_SAMPLE_SIZE:
        eval_item["reason"].append("insufficient_followup_sample")
        return eval_item
    if not isinstance(base_sample, int) or base_sample < MIN_SAMPLE_SIZE:
        eval_item["reason"].append("insufficient_baseline_sample")
        return eval_item

    score = 0
    evidence = 0
    negatives = 0
    positives = 0
    kpi_details = {}
    for k, direction in KPI_DIRECTIONS.items():
        b = base_snap.get(k)
        f = follow_snap.get(k)
        d = delta(b, f)
        detail = {"before": b, "after": f, "delta": d, "direction": direction}
        if d is None:
            detail["judgement"] = "na"
            kpi_details[k] = detail
            continue
        evidence += 1
        if d == 0:
            detail["judgement"] = "flat"
        elif d * direction > 0:
            detail["judgement"] = "improved"
            score += 1
            positives += 1
        else:
            detail["judgement"] = "worsened"
            score -= 1
            negatives += 1
        kpi_details[k] = detail
    eval_item["kpis"] = kpi_details
    eval_item["score"] = score
    eval_item["evidence_count"] = evidence
    eval_item["positives"] = positives
    eval_item["negatives"] = negatives

    if evidence < 3:
        eval_item["decision"] = "hold"
        eval_item["reason"].append("insufficient_evidence")
        return eval_item

    # Conservative rules: rollback only on clear multi-signal worsening.
    if negatives >= 3 and score <= -2:
        eval_item["decision"] = "rollback"
        eval_item["reason"].append("multi_kpi_worsened")
    elif positives >= 2 and score >= 2 and negatives == 0:
        eval_item["decision"] = "adopt"
        eval_item["reason"].append("kpi_improved")
    else:
        eval_item["decision"] = "hold"
        eval_item["reason"].append("mixed_or_weak_signal")
    return eval_item


def _evaluate_prompt_group(dep: dict[str, Any], platform: str,
                           prompt_changes: list[dict[str, Any]],
                           today: str, horizon_days: int) -> dict[str, Any]:
    """1プラットフォーム分の prompt_set を、そのブログの日次ヒストリで事後評価する。"""
    item: dict[str, Any] = {
        "deployment_id": dep.get("deployment_id"),
        "scope": "blog_prompt",
        "platform": platform,
        "date": dep.get("date"),
        "applied": bool(dep.get("applied")),
        "rolled_back_at": dep.get("rolled_back_at"),
        "prompt_changes": prompt_changes,
        "horizon_days": max(int(horizon_days), BLOG_PROMPT_HORIZON_DAYS),
        "decision": "hold",
        "reason": [],
        "kpis": {},
    }
    if not item["applied"]:
        item["reason"].append("not_applied")
        return item
    if item["rolled_back_at"]:
        item["reason"].append("already_rolled_back")
        return item

    directions = BLOG_PROMPT_KPI_DIRECTIONS.get(str(platform))
    if not directions:
        item["reason"].append("unknown_prompt_platform")
        return item
    dep_dt = parse_date(str(dep.get("date") or ""))
    today_dt = parse_date(today)
    if not dep_dt or not today_dt:
        item["reason"].append("invalid_date")
        return item
    age_days = (today_dt - dep_dt).days
    item["age_days"] = age_days
    if age_days < item["horizon_days"]:
        item["reason"].append(f"insufficient_horizon:{age_days}/{item['horizon_days']}")
        return item

    raw_history = load_json(BLOG_HISTORY_DIR / f"{platform}.json", [])
    history = [h for h in raw_history if isinstance(h, dict) and h.get("date") and isinstance(h.get("values"), dict)]
    by_date = {h["date"]: h["values"] for h in history}
    baseline_date = max((d for d in by_date if d <= str(dep.get("date"))), default=None)
    target = (dep_dt + timedelta(days=item["horizon_days"])).strftime("%Y-%m-%d")
    follow_date = min((d for d in by_date if d >= target), default=None)
    if follow_date is None and by_date:
        follow_date = max(by_date)
    item["baseline_date"] = baseline_date
    item["followup_date"] = follow_date
    if not baseline_date or not follow_date or follow_date <= baseline_date:
        item["reason"].append("no_blog_followup")
        return item

    base_values, follow_values = by_date[baseline_date], by_date[follow_date]
    score = evidence = negatives = positives = 0
    for key, direction in directions.items():
        d = delta(base_values.get(key), follow_values.get(key))
        detail = {"before": base_values.get(key), "after": follow_values.get(key),
                  "delta": d, "direction": direction}
        if d is None:
            detail["judgement"] = "na"
        elif d == 0:
            detail["judgement"] = "flat"
            evidence += 1
        elif d * direction > 0:
            detail["judgement"] = "improved"
            evidence += 1
            score += 1
            positives += 1
        else:
            detail["judgement"] = "worsened"
            evidence += 1
            score -= 1
            negatives += 1
        item["kpis"][key] = detail
    item.update({"score": score, "evidence_count": evidence,
                 "positives": positives, "negatives": negatives})
    if evidence < 2:
        item["reason"].append("insufficient_evidence")
    elif negatives >= 2 and score <= -2:
        item["decision"] = "rollback"
        item["reason"].append("blog_kpi_worsened")
    elif positives >= 2 and score >= 2 and negatives == 0:
        item["decision"] = "adopt"
        item["reason"].append("blog_kpi_improved")
    else:
        item["reason"].append("mixed_or_weak_signal")
    return item


def evaluate_prompt_deployment(dep: dict[str, Any], today: str, horizon_days: int) -> dict[str, Any]:
    """prompt_set の deployment をプラットフォーム別に評価し、最も厳しい判定を返す。

    1回の deploy に複数ブログの prompt_changes が入ることがあるため、KPI の比較は
    プラットフォームごとに行い、1つでも悪化なら deployment 全体を rollback 対象にする。
    """
    changes = [c for c in (dep.get("prompt_changes") or []) if isinstance(c, dict)]
    groups: dict[str, list[dict[str, Any]]] = {}
    for ch in changes:
        platform = ch.get("platform")
        if isinstance(platform, str) and platform in BLOG_PROMPT_KPI_DIRECTIONS:
            groups.setdefault(platform, []).append(ch)
    if not groups:
        platform = dep.get("platform")
        if isinstance(platform, list):
            platform = platform[0] if platform else None
        if isinstance(platform, str) and platform in BLOG_PROMPT_KPI_DIRECTIONS:
            groups[platform] = changes
    items = [_evaluate_prompt_group(dep, p, chs, today, horizon_days)
             for p, chs in groups.items()]
    if not items:
        return _evaluate_prompt_group(dep, "", changes, today, horizon_days)
    decisions = [x.get("decision") for x in items]
    if "rollback" in decisions:
        decision = "rollback"
    elif all(d == "adopt" for d in decisions):
        decision = "adopt"
    else:
        decision = "hold"
    return {
        "deployment_id": dep.get("deployment_id"),
        "scope": "blog_prompt",
        "platform": list(groups) if len(groups) > 1 else next(iter(groups)),
        "platforms": list(groups),
        "date": dep.get("date"),
        "applied": bool(dep.get("applied")),
        "rolled_back_at": dep.get("rolled_back_at"),
        "prompt_changes": changes,
        "horizon_days": max(int(horizon_days), BLOG_PROMPT_HORIZON_DAYS),
        "decision": decision,
        "reason": [f"{x.get('platform')}:{x.get('decision')}:{'/'.join(x.get('reason') or [])}"
                   for x in items],
        "per_platform": items,
    }


BLOG_PROMPT_KPI_DIRECTIONS: dict[str, dict[str, int]] = {
    "github": {"post_pageviews": 1, "post_view_share_pct": 1, "gsc_ctr_pct": 1, "gsc_clicks": 1},
    "hatena": {"avg_body_chars": 1, "hub_ratio_pct": 1, "affiliate_coverage_pct": 1,
               "entries_last_30d": 1},
    "ameba": {"entries_last_30d": 1, "active_days_ratio_30d": 1, "affiliate_coverage_pct": 1},
    "note": {"like_rate_pct": 1, "comment_rate_pct": 1, "avg_reads_per_note": 1,
             "longform_ratio_pct": 1},
}


def compute_optimization(analyses: dict[str, dict[str, Any]], eval_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic optimization hints from recent analyses/evaluations."""
    # Model reliability from recent diagnosis attempts
    model_stats: dict[str, dict[str, int]] = {}
    recent_dates = sorted(analyses.keys())[-14:]
    for d in recent_dates:
        diag = (analyses.get(d) or {}).get("diagnosis") or {}
        for at in diag.get("_attempts", []) or []:
            m = at.get("model")
            if not isinstance(m, str) or not m:
                continue
            st = model_stats.setdefault(m, {"ok": 0, "fail": 0, "invalid_json": 0, "total": 0})
            st["total"] += 1
            if at.get("ok"):
                st["ok"] += 1
            else:
                st["fail"] += 1
                if at.get("error") == "invalid_json":
                    st["invalid_json"] += 1

    model_ranking = []
    for m, st in model_stats.items():
        total = st["total"] or 1
        rate = round(st["ok"] / total, 3)
        model_ranking.append({"model": m, **st, "success_rate": rate})
    model_ranking.sort(key=lambda x: (-x["success_rate"], -x["ok"], x["fail"], x["model"]))

    # Action priority from evaluation decisions
    hold_reasons: dict[str, int] = {}
    rollback_keys: dict[str, int] = {}
    for r in eval_results:
        for reason in r.get("reason") or []:
            hold_reasons[reason] = hold_reasons.get(reason, 0) + 1
        if r.get("decision") == "rollback":
            for ch in r.get("changes") or []:
                k = ch.get("key")
                if isinstance(k, str):
                    rollback_keys[k] = rollback_keys.get(k, 0) + 1

    priority_actions = []
    if rollback_keys:
        priority_actions.append({
            "priority": "high",
            "action": "review_rollback_candidates",
            "detail": rollback_keys,
            "reason": "rollback判定が出た変更キーを優先確認",
        })
    if hold_reasons.get("insufficient_horizon:0/7") or any(k.startswith("insufficient_horizon") for k in hold_reasons):
        priority_actions.append({
            "priority": "medium",
            "action": "wait_for_horizon",
            "detail": {k: v for k, v in hold_reasons.items() if k.startswith("insufficient_horizon")},
            "reason": "評価期間未達のdeploymentがあるため観測継続",
        })
    if not priority_actions:
        priority_actions.append({
            "priority": "low",
            "action": "continue_observation",
            "reason": "現時点で緊急のロールバック候補なし",
        })

    return {
        "model_ranking_14d": model_ranking,
        "recommended_consulting_chain_hint": [x["model"] for x in model_ranking if x["success_rate"] > 0][:4],
        "priority_actions": priority_actions,
        "note": "deterministic_hint_only; no automatic chain rewrite",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=now_jst().strftime("%Y-%m-%d"))
    ap.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS)
    ap.add_argument("--apply-rollbacks", action="store_true", help="Apply rollback for rollback decisions (explicit opt-in)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ensure_dirs()
    analyses = load_analyses()
    deployments = load_deployments()
    state = load_json(STATE_PATH, {})

    results = []
    rollbacks = []
    for dep in deployments:
        if dep.get("prompt_changes"):
            item = evaluate_prompt_deployment(dep, args.date, args.horizon_days)
        else:
            item = evaluate_deployment(dep, analyses, args.date, args.horizon_days)
        if args.apply_rollbacks and item.get("decision") == "rollback" and dep.get("applied") and not dep.get("rolled_back_at"):
            dep_id = dep.get("deployment_id")
            if args.dry_run:
                item["rollback_action"] = {"ok": True, "dry_run": True, "deployment_id": dep_id}
            else:
                try:
                    from x_deploy import rollback_deployment
                    rb = rollback_deployment(dep_id, dry_run=False, force=False)
                    item["rollback_action"] = rb
                except Exception as e:
                    item["rollback_action"] = {"ok": False, "error": str(e), "deployment_id": dep_id}
            rollbacks.append(item.get("rollback_action"))
        results.append(item)

    optimization = compute_optimization(analyses, results)
    summary = {
        "date": args.date,
        "generated_at": now_jst().isoformat(),
        "horizon_days": args.horizon_days,
        "deployments_evaluated": len(results),
        "adopt": sum(1 for r in results if r.get("decision") == "adopt"),
        "hold": sum(1 for r in results if r.get("decision") == "hold"),
        "rollback": sum(1 for r in results if r.get("decision") == "rollback"),
        "rollbacks_attempted": len(rollbacks),
        "results": results,
        "optimization": optimization,
    }

    out_path = EVAL_DIR / f"{args.date}.json"
    save_json(out_path, summary)
    state["last_verify_at"] = now_jst().isoformat()
    state["last_evaluation"] = str(out_path.relative_to(BASE)).replace("\\", "/")
    state["last_evaluation_summary"] = {
        "date": args.date,
        "adopt": summary["adopt"],
        "hold": summary["hold"],
        "rollback": summary["rollback"],
    }
    state["last_optimization"] = optimization
    save_json(STATE_PATH, state)

    print(json.dumps({
        "ok": True,
        "evaluation": str(out_path),
        "summary": {k: summary[k] for k in ["date", "deployments_evaluated", "adopt", "hold", "rollback", "rollbacks_attempted"]},
        "optimization": optimization,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
