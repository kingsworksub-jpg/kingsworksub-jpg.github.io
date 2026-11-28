# -*- coding: utf-8 -*-
"""生成物の鮮度を判定する共通ヘルパー。

週次Workflowが止まると、ダッシュボードは「横ばい」ではなく「古いデータを
読み回している」状態になる。各レポートがこのヘルパーを使って鮮度を明示する。
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(JST)


def _read_json(path: str):
    if not os.path.exists(path):
        return None
    try:
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return None


def parse_generated_at(value) -> datetime | None:
    """JSONの generated_at / メタJSONの値を datetime に変換する。"""
    if not value:
        return None
    text = str(value).strip().replace(" JST", "+09:00").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=JST)


def source_generated_at(path: str) -> datetime | None:
    """JSON内部の generated_at、無ければ隣接する .meta.json を読む。"""
    data = _read_json(path)
    if isinstance(data, dict) and data.get("generated_at"):
        return parse_generated_at(data["generated_at"])
    meta_path = os.path.splitext(path)[0] + ".meta.json"
    meta = _read_json(meta_path)
    if isinstance(meta, dict) and meta.get("generated_at"):
        return parse_generated_at(meta["generated_at"])
    return None


def check(paths, max_days: int = 7, now: datetime | None = None) -> list[dict]:
    """鮮度警告のリストを返す。古い順（警告が強い順）に並べる。"""
    now = now or now_jst()
    out = []
    for path in paths:
        generated = source_generated_at(path)
        if generated is None:
            out.append({
                "path": path, "generated_at": None, "age_days": None,
                "level": "missing", "message": f"{path}: 生成時刻が不明（未生成またはメタ欠落）",
            })
            continue
        age = (now - generated).total_seconds() / 86400.0
        level = "stale" if age > max_days else ("warn" if age > max_days / 2 else "ok")
        out.append({
            "path": path,
            "generated_at": generated.isoformat(timespec="seconds"),
            "age_days": round(age, 1),
            "level": level,
            "message": (f"{path}: {age:.1f}日前 ({generated.astimezone(JST):%Y-%m-%d %H:%M} JST)"),
        })
    order = {"stale": 0, "missing": 1, "warn": 2, "ok": 3}
    out.sort(key=lambda r: order.get(r["level"], 9))
    return out


def markdown(rows: list[dict], max_days: int = 7) -> list[str]:
    """レポート用のMarkdown行を返す。問題が無い場合も1行出す。"""
    problems = [r for r in rows if r["level"] != "ok"]
    if not problems:
        return [f"- データ鮮度: すべて {max_days}日以内（問題なし）"]
    lines = []
    for r in problems:
        prefix = "❌" if r["level"] in ("stale", "missing") else "⚠️"
        lines.append(f"- {prefix} {r['message']}（{max_days}日を超えていたら要再取得）")
    return lines
