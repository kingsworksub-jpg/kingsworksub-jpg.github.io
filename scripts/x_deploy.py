# -*- coding: utf-8 -*-
"""Phase 3: bounded auto-deploy for the X self-improvement ecosystem.

Applies ONLY allowlisted, low-risk rule changes. Supported:
- limit_adjust / limit_tighten on known daily/rate/interval limits
  (data/x-consulting/managed-limits.json)
- policy_set on string policies such as X_LINK_POLICY
- prompt_set on allowlisted blog-generation prompt knobs
  (data/blog-consulting/managed-prompts.json -> scripts/oc_generate.py)

2026-11-23: ユーザー指示で「引き下げのみ」から、レポートに基づく
**上下両方向の自動調整**へ拡張した。ただしキーごとの hard cap / min /
1回の最大変化幅(step) を超える変更は拒否する。投稿数上限も対象。

2026-11-28: ユーザー指示で、自動調整対象を運用パラメータだけでなく
**ブログ記事生成LLMへのプロンプト**にも拡張。LLMにプロンプト本文の自由記述は
させず、blog_prompt_config.py の allowlist ノブだけを step 付きで切り替える。
プロンプトはプラットフォーム別に保持し、記事の canonical_platform の値だけを
生成時に使う（1ブログの指標が全ブログを書き換えないようにする）。

Safety:
- allowlist only
- hard cap / min / step enforced (raises are bounded, never above cap)
- daily change limit + per-key cooldown
- diff/audit log in data/x-consulting/deployments/
- rollback support (limits, policies and prompt knobs)
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
PROMPTS_PATH = BASE / "data" / "blog-consulting" / "managed-prompts.json"

try:
    from x_automation_config import LIMIT_SPECS, POLICY_SPECS
except Exception:  # pragma: no cover - scripts dir is normally on sys.path
    LIMIT_SPECS = {}
    POLICY_SPECS = {}

try:
    from blog_prompt_config import (
        PROMPT_PLATFORMS, PROMPT_SPECS, normalize_platform,
        validate_value as validate_prompt_value,
    )
except Exception:  # pragma: no cover
    PROMPT_PLATFORMS = ("github", "hatena", "ameba", "note")
    PROMPT_SPECS = {}

    def normalize_platform(platform):  # type: ignore
        value = str(platform or "").strip().lower()
        return value if value in PROMPT_PLATFORMS else ""

    def validate_prompt_value(key, value, current=None):  # type: ignore
        return False, "prompt_config_unavailable", None

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


def load_prompts() -> dict[str, Any]:
    data = load_json(PROMPTS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    prompts = data.get("prompts")
    if not isinstance(prompts, dict):
        prompts = {}
    # version 1 のフラット形式を全プラットフォーム共通の初期値として昇格させる。
    if any(key in PROMPT_SPECS for key in prompts):
        flat = {k: v for k, v in prompts.items() if k in PROMPT_SPECS}
        prompts = {p: dict(flat) for p in PROMPT_PLATFORMS}
        data["version"] = 2
    for platform in PROMPT_PLATFORMS:
        if not isinstance(prompts.get(platform), dict):
            prompts[platform] = {}
    data["version"] = data.get("version", 2)
    data["prompts"] = prompts
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
    prompts_doc = load_prompts()
    prompts = prompts_doc.get("prompts", {})
    now = now_jst()
    date = now.strftime("%Y-%m-%d")
    dep_id = now.strftime("%Y%m%d-%H%M%S")
    # 同じ秒に複数回デプロイすると deployment ログが上書きされるため、衝突時だけ微秒を付ける。
    if (DEPLOY_DIR / f"{dep_id}.json").exists():
        dep_id = now.strftime("%Y%m%d-%H%M%S-%f")
    changes = []
    policy_changes = []
    prompt_changes = []
    errors = []
    platforms: list[str] = []

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

        if atype == "prompt_set":
            # ブログ記事生成LLMへのプロンプト指示を、allowlist ノブだけ切り替える。
            # 値はプラットフォーム別に保持し、cooldown も platform+key 単位で持つ。
            platform = normalize_platform(a.get("platform"))
            if not platform:
                errors.append({"action": a, "error": "prompt_platform_not_allowlisted"})
                continue
            if platform not in platforms:
                platforms.append(platform)
            spec = PROMPT_SPECS.get(key)
            if not spec:
                errors.append({"action": a, "error": "prompt_key_not_allowlisted"})
                continue
            pentry = prompts.setdefault(platform, {})
            before = pentry.get(key, spec.get("default"))
            value = a.get("value")
            ok, reason, pval = validate_prompt_value(key, value, before)
            if not ok:
                errors.append({"action": a, "error": reason, "before": before})
                continue
            if before == pval:
                # 同じ値の再適用は no-op として扱い、cooldown エラーも出さない。
                continue
            cd_key = f"prompt:{platform}:{key}"
            if in_cooldown(state, cd_key, now):
                errors.append({"action": a, "error": "cooldown"})
                continue
            change = {
                "type": atype, "key": key, "before": before, "after": pval,
                "platform": platform, "rule": a.get("rule"), "reason": a.get("reason"),
            }
            prompt_changes.append(change)
            if not dry_run:
                pentry[key] = pval
                cds = state.setdefault("cooldowns", {})
                cds[cd_key] = (now + timedelta(hours=COOLDOWN_HOURS)).isoformat()
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
        "prompt_changes": prompt_changes,
        "platform": platforms[0] if len(platforms) == 1 else (platforms or None),
        "errors": errors,
        "applied": ((len(changes) + len(policy_changes) + len(prompt_changes)) > 0 and not dry_run),
        "restart_required": bool(changes or policy_changes or prompt_changes),
    }

    if result["applied"]:
        if changes or policy_changes:
            limits_doc["limits"] = limits
            limits_doc["policies"] = policies
            limits_doc["updated_at"] = now.isoformat()
            save_json(LIMITS_PATH, limits_doc)
        if prompt_changes:
            prompts_doc["prompts"] = prompts
            prompts_doc["updated_at"] = now.isoformat()
            prompts_doc["last_deployment_id"] = dep_id
            save_json(PROMPTS_PATH, prompts_doc)
        log = state.setdefault("deploy_log", [])
        log.append({
            "deployment_id": dep_id,
            "date": date,
            "status": "applied",
            "changes": changes,
            "policy_changes": policy_changes,
            "prompt_changes": prompt_changes,
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
    prompts_doc = load_prompts()
    prompts = prompts_doc.get("prompts", {})
    state = load_json(STATE_PATH, {})
    reverted = []
    policy_reverted = []
    prompt_reverted = []
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

    for ch in dep.get("prompt_changes", []) or []:
        key = ch.get("key")
        before = ch.get("before")
        after = ch.get("after")
        platform = normalize_platform(ch.get("platform"))
        if key not in PROMPT_SPECS or not platform:
            continue
        pentry = prompts.setdefault(platform, {})
        current = pentry.get(key, (PROMPT_SPECS[key] or {}).get("default"))
        if not force and current != after:
            continue
        if not dry_run:
            if before is None:
                pentry.pop(key, None)
            else:
                pentry[key] = before
        prompt_reverted.append({
            "key": key, "platform": platform, "from": current,
            "to": before, "expected_after": after,
        })
        cd_key = f"prompt:{platform}:{key}"
        if cd_key in (state.get("cooldowns") or {}):
            cooldowns_cleared.append(cd_key)

    now = now_jst()
    if not dry_run and (reverted or policy_reverted or prompt_reverted or cooldowns_cleared):
        if reverted or policy_reverted:
            limits_doc["limits"] = limits
            limits_doc["policies"] = policies
            limits_doc["updated_at"] = now.isoformat()
            limits_doc["rolled_back_from"] = dep_id
            save_json(LIMITS_PATH, limits_doc)
        if prompt_reverted:
            prompts_doc["prompts"] = prompts
            prompts_doc["updated_at"] = now.isoformat()
            prompts_doc["rolled_back_from"] = dep_id
            save_json(PROMPTS_PATH, prompts_doc)
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
            "prompt_changes": prompt_reverted,
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
        "prompt_reverted": prompt_reverted,
        "cooldowns_cleared": cooldowns_cleared,
        "already_rolled_back": bool(dep.get("rolled_back_at")) and not reverted and not policy_reverted and not prompt_reverted and not dry_run,
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
        # 3) blog consulting proposals: prompt_set hints from the daily report
        for x in obj.get("prompt_changes") or []:
            if isinstance(x, dict):
                out.append(x)
        # 4) explicit deploy_actions
        for x in obj.get("deploy_actions") or []:
            if isinstance(x, dict):
                out.append(x)
        # de-duplicate by (type,key,value,platform): 同一ノブでもプラットフォーム別に残す。
        seen = set()
        uniq = []
        for x in out:
            sig = (x.get("type"), x.get("key"), x.get("value"), x.get("platform"))
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
    ap.add_argument("--proposal", action="append", default=[],
                    help="Proposal JSON path (repeatable); reads rule_changes, prompt_changes and actions[].deploy")
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
        for proposal_path in args.proposal:
            actions.extend(load_actions_from_proposal(Path(proposal_path)))
        # 同一キーの自動調整は先に現れた提案を優先（4ブログ分をまとめて適用するため）。
        seen = set()
        unique = []
        for act in actions:
            sig = (act.get("type"), act.get("key"), act.get("value"))
            if sig in seen:
                continue
            seen.add(sig)
            unique.append(act)
        actions = unique
    else:
        print(json.dumps({"ok": False, "error": "no_input"}, ensure_ascii=False))
        return 1

    res = apply_actions(actions, dry_run=args.dry_run, auto_safe=args.auto_safe)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
