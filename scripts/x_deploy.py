# -*- coding: utf-8 -*-
"""Phase 3: bounded auto-deploy for the X self-improvement ecosystem.

Applies ONLY allowlisted, low-risk rule changes. Supported:
- limit_adjust / limit_tighten on known daily/rate/interval limits
  (data/x-consulting/managed-limits.json)
- policy_set on string policies such as X_LINK_POLICY

2026-11-23: ユーザー指示で「引き下げのみ」から、レポートに基づく
**上下両方向の自動調整**へ拡張した。ただしキーごとの hard cap / min /
1回の最大変化幅(step) を超える変更は拒否する。投稿数上限も対象。

Safety:
- allowlist only
- hard cap / min / step enforced (raises are bounded, never above cap)
- daily change limit + per-key cooldown
- diff/audit log in data/x-consulting/deployments/
- rollback support (limits and policies)
- dry-run supported
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
OUT_ROOT = BASE / "data" / "x-consulting"
DEPLOY_DIR = OUT_ROOT / "deployments"
STATE_PATH = OUT_ROOT / "state.json"
LIMITS_PATH = OUT_ROOT / "managed-limits.json"
PROPOSALS_DIR = OUT_ROOT / "proposals"

try:
    from x_automation_config import LIMIT_SPECS, POLICY_SPECS
except Exception:  # pragma: no cover - scripts dir is normally on sys.path
    LIMIT_SPECS = {}
    POLICY_SPECS = {}

# Hard caps: auto-deploy may only set value within [min, cap].
# 後方互換のため名前は LIMIT_ALLOWLIST のまま残す。
LIMIT_ALLOWLIST = LIMIT_SPECS or {
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

MAX_DEPLOYS_PER_DAY = 5
COOLDOWN_HOURS = 24


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
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)


def load_limits() -> dict[str, Any]:
    data = load_json(LIMITS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("limits", {})
    data.setdefault("policies", {})
    return data


def deployments_today(state: dict[str, Any], date: str) -> int:
    log = state.get("deploy_log", [])
    return sum(1 for x in log if x.get("date") == date and x.get("status") == "applied")


def in_cooldown(state: dict[str, Any], key: str, now: datetime) -> bool:
    cds = state.get("cooldowns", {})
    until = cds.get(key)
    if not until:
        return False
    try:
        dt = datetime.fromisoformat(until)
        return now < dt
    except Exception:
        return False


def validate_limit_change(key: str, value: Any, current: Any, allow_raise: bool = False) -> tuple[bool, str, int | None]:
    spec = LIMIT_ALLOWLIST.get(key)
    if not spec:
        return False, "not_allowlisted", None
    try:
        ival = int(value)
    except Exception:
        return False, "not_int", None
    if ival < spec["min"] or ival > spec["cap"]:
        return False, f"out_of_range({spec['min']}..{spec['cap']})", None
    step = int(spec.get("step", 1) or 1)
    if current is not None:
        try:
            cur = int(current)
            if ival > cur:
                if not allow_raise:
                    return False, "not_tightening", None
                if ival - cur > step:
                    return False, f"step_too_large(max +{step})", None
            elif cur - ival > max(step * 2, 1):
                # 下げ幅は上げ幅の2倍まで（急な全停止はレポートの強い悪化シグナル時のみ）
                return False, f"step_too_large(max -{max(step * 2, 1)})", None
        except Exception:
            pass
    return True, "ok", ival


def apply_actions(actions: list[dict[str, Any]], dry_run: bool, auto_safe: bool) -> dict[str, Any]:
    ensure_dirs()
    state = load_json(STATE_PATH, {})
    limits_doc = load_limits()
    limits = limits_doc.get("limits", {})
    policies = limits_doc.get("policies", {})
    now = now_jst()
    date = now.strftime("%Y-%m-%d")
    dep_id = now.strftime("%Y%m%d-%H%M%S")
    changes = []
    policy_changes = []
    errors = []

    if deployments_today(state, date) >= MAX_DEPLOYS_PER_DAY:
        return {"ok": False, "error": "daily_deploy_limit_reached", "deployment_id": dep_id, "changes": [], "errors": []}

    for a in actions:
        atype = a.get("type")
        key = a.get("key")
        value = a.get("value")
        if auto_safe and not a.get("auto_safe", False):
            continue

        if atype in ("limit_tighten", "limit_adjust"):
            if in_cooldown(state, f"limit:{key}", now):
                errors.append({"action": a, "error": "cooldown"})
                continue
            before = limits.get(key)
            allow_raise = atype == "limit_adjust" or bool(a.get("allow_raise"))
            ok, reason, ival = validate_limit_change(key, value, before, allow_raise=allow_raise)
            if not ok:
                errors.append({"action": a, "error": reason, "before": before})
                continue
            change = {"type": atype, "key": key, "before": before, "after": ival}
            changes.append(change)
            if not dry_run:
                limits[key] = ival
                cds = state.setdefault("cooldowns", {})
                cds[f"limit:{key}"] = (now + timedelta(hours=COOLDOWN_HOURS)).isoformat()
            continue

        if atype == "policy_set":
            spec = POLICY_SPECS.get(key)
            if not spec:
                errors.append({"action": a, "error": "policy_not_allowlisted"})
                continue
            if value not in spec["allowed"]:
                errors.append({"action": a, "error": "policy_value_not_allowed", "value": value})
                continue
            if in_cooldown(state, f"policy:{key}", now):
                errors.append({"action": a, "error": "cooldown"})
                continue
            before = policies.get(key)
            if before == value:
                continue
            change = {"type": atype, "key": key, "before": before, "after": value}
            policy_changes.append(change)
            if not dry_run:
                policies[key] = value
                cds = state.setdefault("cooldowns", {})
                cds[f"policy:{key}"] = (now + timedelta(hours=COOLDOWN_HOURS)).isoformat()
            continue

        errors.append({"action": a, "error": "unsupported_action_type"})

    result = {
        "ok": True,
        "deployment_id": dep_id,
        "date": date,
        "dry_run": dry_run,
        "auto_safe": auto_safe,
        "changes": changes,
        "policy_changes": policy_changes,
        "errors": errors,
        "applied": ((len(changes) + len(policy_changes)) > 0 and not dry_run),
        "restart_required": bool(changes or policy_changes),
    }

    if (changes or policy_changes) and not dry_run:
        limits_doc["limits"] = limits
        limits_doc["policies"] = policies
        limits_doc["updated_at"] = now.isoformat()
        save_json(LIMITS_PATH, limits_doc)
        log = state.setdefault("deploy_log", [])
        log.append({
            "deployment_id": dep_id,
            "date": date,
            "status": "applied",
            "changes": changes,
            "policy_changes": policy_changes,
        })
        state["last_deploy_at"] = now.isoformat()
        save_json(STATE_PATH, state)

    save_json(DEPLOY_DIR / f"{dep_id}.json", result)
    return result


def rollback_deployment(dep_id: str, dry_run: bool, force: bool = False) -> dict[str, Any]:
    ensure_dirs()
    dep_path = DEPLOY_DIR / f"{dep_id}.json"
    dep = load_json(dep_path, None)
    if not isinstance(dep, dict):
        return {"ok": False, "error": "deployment_not_found"}
    if not dep.get("applied"):
        return {"ok": False, "error": "deployment_not_applied"}
    if dep.get("rolled_back_at") and not force:
        return {
            "ok": False,
            "error": "already_rolled_back",
            "deployment_id": dep_id,
            "rolled_back_at": dep.get("rolled_back_at"),
        }

    limits_doc = load_limits()
    limits = limits_doc.get("limits", {})
    policies = limits_doc.get("policies", {})
    state = load_json(STATE_PATH, {})
    reverted = []
    policy_reverted = []
    cooldowns_cleared = []
    for ch in dep.get("changes", []):
        key = ch.get("key")
        before = ch.get("before")
        if key not in LIMIT_ALLOWLIST:
            continue
        current = limits.get(key)
        # 2A/2B-safe: only revert keys still at deployed "after" value unless force.
        after = ch.get("after")
        if not force and current != after:
            continue
        if before is None:
            if key in limits and not dry_run:
                del limits[key]
        else:
            if not dry_run:
                limits[key] = before
        reverted.append({"key": key, "from": current, "to": before, "expected_after": after})
        cd_key = f"limit:{key}"
        if cd_key in (state.get("cooldowns") or {}):
            cooldowns_cleared.append(cd_key)

    for ch in dep.get("policy_changes", []) or []:
        key = ch.get("key")
        before = ch.get("before")
        after = ch.get("after")
        if key not in POLICY_SPECS:
            continue
        current = policies.get(key)
        if not force and current != after:
            continue
        if not dry_run:
            if before is None:
                policies.pop(key, None)
            else:
                policies[key] = before
        policy_reverted.append({"key": key, "from": current, "to": before, "expected_after": after})
        cd_key = f"policy:{key}"
        if cd_key in (state.get("cooldowns") or {}):
            cooldowns_cleared.append(cd_key)

    now = now_jst()
    if not dry_run and (reverted or policy_reverted or cooldowns_cleared):
        limits_doc["limits"] = limits
        limits_doc["policies"] = policies
        limits_doc["updated_at"] = now.isoformat()
        limits_doc["rolled_back_from"] = dep_id
        save_json(LIMITS_PATH, limits_doc)
        cds = state.setdefault("cooldowns", {})
        for cd_key in cooldowns_cleared:
            cds.pop(cd_key, None)
        log = state.setdefault("deploy_log", [])
        log.append({
            "deployment_id": dep_id,
            "date": now.strftime("%Y-%m-%d"),
            "status": "rolled_back",
            "changes": reverted,
            "policy_changes": policy_reverted,
            "cooldowns_cleared": cooldowns_cleared,
            "forced": force,
        })
        state["last_rollback_at"] = now.isoformat()
        save_json(STATE_PATH, state)
        dep["rolled_back_at"] = now.isoformat()
        dep["rollback_status"] = "rolled_back"
        dep["cooldowns_cleared"] = cooldowns_cleared
        save_json(dep_path, dep)

    out = {
        "ok": True,
        "deployment_id": dep_id,
        "dry_run": dry_run,
        "forced": force,
        "reverted": reverted,
        "policy_reverted": policy_reverted,
        "cooldowns_cleared": cooldowns_cleared,
        "already_rolled_back": bool(dep.get("rolled_back_at")) and not reverted and not policy_reverted and not dry_run,
    }
    save_json(DEPLOY_DIR / f"{dep_id}-rollback.json", out)
    return out


def load_actions_from_proposal(path: Path) -> list[dict[str, Any]]:
    obj = load_json(path, {})
    out: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        # 1) top-level rule_changes (2026-11-23+)
        for x in obj.get("rule_changes") or []:
            if isinstance(x, dict):
                out.append(x)
        # 2) per-action deploy hints
        for a in obj.get("actions") or []:
            dep = a.get("deploy") if isinstance(a, dict) else None
            if isinstance(dep, dict):
                out.append(dep)
        # 3) explicit deploy_actions
        for x in obj.get("deploy_actions") or []:
            if isinstance(x, dict):
                out.append(x)
        # de-duplicate by (type,key,value)
        seen = set()
        uniq = []
        for x in out:
            sig = (x.get("type"), x.get("key"), x.get("value"))
            if sig in seen:
                continue
            seen.add(sig)
            uniq.append(x)
        return uniq
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", help="Proposal JSON path; reads rule_changes and actions[].deploy")
    ap.add_argument("--actions-file", help="JSON file containing deploy actions list")
    ap.add_argument("--rollback", help="Deployment ID to rollback")
    ap.add_argument("--force", action="store_true", help="Force rollback even if already rolled back / state mismatch checks")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--auto-safe", action="store_true", help="Apply only actions marked auto_safe=true")
    args = ap.parse_args()

    ensure_dirs()
    if args.rollback:
        res = rollback_deployment(args.rollback, args.dry_run, force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    actions: list[dict[str, Any]] = []
    if args.actions_file:
        actions = load_actions_from_proposal(Path(args.actions_file))
        if not actions:
            raw = load_json(Path(args.actions_file), [])
            if isinstance(raw, list):
                actions = [x for x in raw if isinstance(x, dict)]
    elif args.proposal:
        actions = load_actions_from_proposal(Path(args.proposal))
    else:
        print(json.dumps({"ok": False, "error": "no_input"}, ensure_ascii=False))
        return 1

    res = apply_actions(actions, dry_run=args.dry_run, auto_safe=args.auto_safe)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
