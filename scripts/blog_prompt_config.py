# -*- coding: utf-8 -*-
"""ブログ記事生成プロンプトの自動調整を一元管理する。

X の自動ルール調整（レポート -> x_deploy -> 実運用 -> x_verify）と同じ基盤で、
ブログ記事生成 LLM（scripts/oc_generate.py）へ渡すプロンプトも安全に調整するための
設定層。LLM がプロンプト本文を自由に書き換えることはせず、blocker の少ない
「許可されたノブ」だけを before/after 付きで切り替える。

永続化先:
    data/blog-consulting/managed-prompts.json

    {
      "version": 2,
      "updated_at": "...",
      "prompts": {
        "github": {"BLOG_MIN_BODY_CHARS": 5500, "BLOG_CTA_LEVEL": "standard"},
        "hatena": {"BLOG_CTA_LEVEL": "strong"},
        "ameba":  {},
        "note":   {"BLOG_DEPTH_STYLE": "comparison"}
      }
    }

設計方針:
- プロンプトはプラットフォームごとに分け、記事の canonical_platform の値だけを
  生成時に使う。1ブログの指標が全ブログのプロンプトを書き換えないようにする。
- allowlist のみ。未定義キー / 範囲外 / 型違いは無視してコード既定値へ戻す。
- int は min/cap/step、enum は許可値と1段ずつの遷移だけを許す。
- 既定値のときはプロンプトに追加行を出さない（既存 RULES をそのまま使う）。
- 追加指示は既存ルールより優先させない（末尾に明示的に書く）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
PROMPTS_PATH = BASE / "data" / "blog-consulting" / "managed-prompts.json"
PROMPT_PLATFORMS = ("github", "hatena", "ameba", "note")

# key -> spec。auto-deploy の allowlist とプロンプト生成の両方で使う。
PROMPT_SPECS: dict[str, dict[str, Any]] = {
    "BLOG_MIN_BODY_CHARS": {
        "type": "int",
        "default": 5000,
        "min": 3500,          # oc_generate.MIN_BODY を下回らない
        "cap": 6500,
        "step": 500,
        "directive": "本文は {value} 字以上を目安にする。ブリーフの target_chars が大きい場合は target_chars を優先し、同じ話の引き延ばしではなく情報量で厚みを出す。",
    },
    "BLOG_HEADING_MIN": {
        "type": "int",
        "default": 7,
        "min": 7,
        "cap": 9,
        "step": 1,
        "directive": "`##` 見出しは {value} 個以上にする（既存の 7〜9 個の範囲を超えない）。",
    },
    "BLOG_CTA_LEVEL": {
        "type": "enum",
        "default": "standard",
        "allowed": ["soft", "standard", "strong"],  # 1段ずつしか動かない
        "directives": {
            "soft": "CTA は冒頭とまとめ前の2か所に留める。ただし figure 直後・商品解説直後のテキストリンクと消耗品リンクなど、既存の必須リンクは残す。",
            "standard": "",  # 既定: 追加指示なし
            "strong": "CVR を優先し、冒頭CTA・各商品の解説直後のテキストリンク・まとめ前の不安解消を必ず入れる。価格注記は1回だけ。",
        },
    },
    "BLOG_DEPTH_STYLE": {
        "type": "enum",
        "default": "standard",
        "allowed": ["standard", "comparison", "practical"],
        "directives": {
            "standard": "",  # 既定: 追加指示なし
            "comparison": "各主要見出しに比較表を1つ入れ、数値の差を明示する。比較表が作れない章では具体的な手順を書く。",
            "practical": "各主要見出しに「よくある失敗と回避策」を短く1つ入れ、読者が当日試せる手順を明示する。",
        },
    },
}

PROMPT_TUNING_HEADER = "## 自動調整された生成指示（{platform} / レポート反映）"


def normalize_platform(platform: Any) -> str:
    value = str(platform or "").strip().lower()
    return value if value in PROMPT_PLATFORMS else ""


def load_managed() -> dict[str, Any]:
    try:
        obj = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        obj = {}
    if not isinstance(obj, dict):
        obj = {}
    prompts = obj.get("prompts")
    if not isinstance(prompts, dict):
        prompts = {}
    # version 1 のフラット形式を読み込んだら、全プラットフォームへ同じ値を昇格させる。
    if any(key in PROMPT_SPECS for key in prompts):
        flat = {k: v for k, v in prompts.items() if k in PROMPT_SPECS}
        prompts = {p: dict(flat) for p in PROMPT_PLATFORMS}
        obj["version"] = 2
    obj["prompts"] = prompts
    return obj


def platform_prompts(managed: dict[str, Any] | None = None,
                     platform: Any = None) -> dict[str, Any]:
    doc = managed if managed is not None else load_managed()
    name = normalize_platform(platform)
    if not name:
        return {}
    entry = (doc.get("prompts") or {}).get(name)
    return dict(entry) if isinstance(entry, dict) else {}


def get_rule(key: str, platform: Any) -> Any:
    """指定プラットフォームの実効値を返す。壊れた値はコード既定値へフォールバック。"""
    spec = PROMPT_SPECS.get(key)
    if not spec:
        return ""
    raw = platform_prompts(platform=platform).get(key)
    ok, _reason, value = validate_value(key, raw)
    return value if ok else spec["default"]


def get_all_rules(platform: Any) -> dict[str, Any]:
    return {key: get_rule(key, platform) for key in PROMPT_SPECS}


def validate_value(key: str, value: Any, current: Any = None) -> tuple[bool, str, Any]:
    """x_deploy から呼ばれる検証。戻り値は (ok, reason, normalized)。"""
    spec = PROMPT_SPECS.get(key)
    if not spec:
        return False, "prompt_key_not_allowlisted", None
    kind = spec.get("type")
    if kind == "int":
        try:
            ival = int(value)
        except Exception:
            return False, "prompt_value_not_int", None
        if ival < int(spec["min"]) or ival > int(spec["cap"]):
            return False, f"prompt_out_of_range({spec['min']}..{spec['cap']})", None
        step = int(spec.get("step", 1) or 1)
        if current is not None:
            try:
                cur = int(current)
                if ival > cur + step:
                    return False, f"prompt_step_too_large(max +{step})", None
                if cur - ival > step * 2:
                    return False, f"prompt_step_too_large(max -{step * 2})", None
            except Exception:
                pass
        return True, "ok", ival
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["allowed"]:
            return False, "prompt_value_not_allowed", None
        if current is not None and current in spec["allowed"] and current != value:
            # 1段だけ動かす（例: standard -> strong は可、soft -> strong は不可）
            allowed = list(spec["allowed"])
            if abs(allowed.index(value) - allowed.index(current)) > 1:
                return False, "prompt_step_too_large(max 1 enum step)", None
        return True, "ok", value
    return False, "prompt_unsupported_spec", None


def enum_step(key: str, current: Any, direction: int) -> Any:
    """enum ノブを1段だけ動かす。既に端なら現状維持。"""
    spec = PROMPT_SPECS.get(key) or {}
    if spec.get("type") != "enum":
        return current
    allowed = list(spec.get("allowed") or [])
    if not allowed:
        return current
    idx = allowed.index(current) if current in allowed else allowed.index(spec["default"])
    new_idx = max(0, min(len(allowed) - 1, idx + (1 if direction > 0 else -1)))
    return allowed[new_idx]


def directive_lines(platform: Any) -> list[str]:
    """指定プラットフォームの実効値から、プロンプト末尾に足す日本語指示だけを返す。"""
    managed = platform_prompts(platform=platform)
    lines: list[str] = []
    for key, spec in PROMPT_SPECS.items():
        raw = managed.get(key, spec["default"])
        ok, _reason, value = validate_value(key, raw)
        if not ok:
            value = spec["default"]
        if value == spec["default"]:
            # 既定値は既存 RULES に既に反映されているので追加行は出さない。
            continue
        if spec.get("type") == "int":
            text = str(spec.get("directive", "")).format(value=value)
        else:
            text = str((spec.get("directives") or {}).get(value, ""))
        if text:
            lines.append(f"- {text}")
    return lines


def prompt_block(platform: Any) -> str:
    """指定プラットフォーム向けの追加プロンプト。既定値だけなら空文字。"""
    name = normalize_platform(platform)
    if not name:
        return ""
    lines = directive_lines(name)
    if not lines:
        return ""
    return ("\n" + PROMPT_TUNING_HEADER.format(platform=name) + "\n"
            "以下はこのプラットフォームの日次レポート指標から自動調整された追加指示です。\n"
            "既存のルールやブリーフの事実と矛盾するときは、既存ルール・ブリーフを優先してください。\n"
            + "\n".join(lines) + "\n")
