# -*- coding: utf-8 -*-
"""X自動化ルールの一元管理。

レポート（scripts/x_consultant.py）が提案し、scripts/x_deploy.py が適用した
`data/x-consulting/managed-limits.json` を、各常駐スクリプトが読むための共通層。

設計方針（2026-11-23 ユーザー指示）:
- 「引き下げのみ」ではなく、**レポートの内容に応じて上下両方向**に調整できる。
- ただし暴走しないよう、キーごとに hard cap / min / 1回の最大変化幅(step) を持つ。
- 値が壊れている・範囲外・型違いのときは、安全にコード既定値へフォールバックする。
- 環境変数は「コード既定値」の上書きとして扱い、managed 値が無いときだけ使う。

managed-limits.json の形:
    {
      "version": 1,
      "updated_at": "...",
      "limits":   {"X_MAX_REPLIES_PER_DAY": 12, ...},
      "policies": {"X_LINK_POLICY": "native_then_first_reply"}
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
LIMITS_PATH = BASE / "data" / "x-consulting" / "managed-limits.json"

# key -> {default, cap, min, step}
# cap は「自動調整で到達してよい上限」。これを超える値は managed 側でも無視する。
LIMIT_SPECS: dict[str, dict[str, Any]] = {
    # 返信系（2ジョブ合算の実効上限）
    "X_MAX_AUTO_REPLIES_PER_DAY": {"default": 10, "cap": 20, "min": 0, "step": 2},
    "X_MAX_REPLIES_PER_DAY": {"default": 10, "cap": 20, "min": 0, "step": 2},
    # いいね系
    "X_FOLLOWUP_MAX_LIKES_PER_DAY": {"default": 3, "cap": 8, "min": 0, "step": 1},
    "X_MAX_LIKES_PER_DAY": {"default": 30, "cap": 60, "min": 0, "step": 5},
    # 新規投稿（自動改善ポスト）系
    "X_MAX_POSTS_PER_DAY": {"default": 1, "cap": 3, "min": 0, "step": 1},
    "X_MIN_HOURS_BETWEEN_POSTS": {"default": 8, "cap": 24, "min": 2, "step": 2},
    # 巡回間隔（分）。日中と深夜で別々に調整する。
    "X_DAY_INTERVAL_MIN": {"default": 18, "cap": 90, "min": 8, "step": 6},
    "X_DAY_INTERVAL_MAX": {"default": 45, "cap": 180, "min": 12, "step": 10},
    "X_NIGHT_INTERVAL_MIN": {"default": 80, "cap": 240, "min": 30, "step": 20},
    "X_NIGHT_INTERVAL_MAX": {"default": 150, "cap": 360, "min": 60, "step": 30},
    # リンクを付ける確率（LLM判断の上にかける上限）。0-70%。
    "X_LINK_PROBABILITY_PCT": {"default": 35, "cap": 70, "min": 0, "step": 10},
}

# 文字列ポリシー。レポートの証拠に応じて切り替える。
POLICY_SPECS: dict[str, dict[str, Any]] = {
    "X_LINK_POLICY": {
        "default": "native_then_first_reply",
        # native_then_first_reply: 本文はネイティブ完結、リンクは最初の返信
        # inline: 本文に直接URL
        # auto: 投稿ごとにLLMが配置を決める
        "allowed": ["native_then_first_reply", "inline", "auto"],
    },
}


def _env_default(key: str) -> int | None:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def load_managed() -> dict[str, Any]:
    try:
        obj = json.loads(LIMITS_PATH.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def clamp(key: str, value: Any) -> int | None:
    spec = LIMIT_SPECS.get(key)
    if not spec:
        return None
    try:
        ival = int(value)
    except Exception:
        return None
    return max(int(spec["min"]), min(int(spec["cap"]), ival))


def get_limit(key: str, default: int | None = None) -> int:
    """実効値を返す。managed が無効なら env → spec.default の順。"""
    spec = LIMIT_SPECS.get(key)
    base = default
    if base is None:
        env = _env_default(key)
        base = env if env is not None else (int(spec["default"]) if spec else 0)
    if spec is None:
        return int(base)
    managed = (load_managed().get("limits") or {}).get(key)
    if managed is None:
        return clamp(key, base) or int(base)
    ival = clamp(key, managed)
    return int(base) if ival is None else ival


def get_pair(prefix: str, default: tuple[int, int]) -> tuple[int, int]:
    """例: get_pair('X_DAY_INTERVAL', (18,45)) -> (min, max)。逆転時は安全側に直す。"""
    lo = get_limit(f"{prefix}_MIN", default[0])
    hi = get_limit(f"{prefix}_MAX", default[1])
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def get_policy(key: str) -> str:
    spec = POLICY_SPECS.get(key)
    if not spec:
        return ""
    managed = (load_managed().get("policies") or {}).get(key)
    if isinstance(managed, str) and managed in spec["allowed"]:
        return managed
    return str(spec["default"])


def set_limit(key: str, value: int) -> None:
    doc = load_managed()
    limits = doc.setdefault("limits", {})
    limits[key] = int(value)
    doc["version"] = doc.get("version", 1)
    LIMITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIMITS_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def set_policy(key: str, value: str) -> None:
    doc = load_managed()
    policies = doc.setdefault("policies", {})
    policies[key] = value
    doc["version"] = doc.get("version", 1)
    LIMITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIMITS_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
