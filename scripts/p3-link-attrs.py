# -*- coding: utf-8 -*-
"""P3: Amazonアフィリエイトリンクへ target / rel 属性を付与する。

対象は git で追跡されている content/posts/*.md のみ（未追跡のユーザー作業には触れない）。
既存の href / アンカーテキスト / タグ構造は一切変更せず、欠けている属性だけを追加する。

    target="_blank"                          ... 読者を自サイトに留める
    rel="noopener sponsored nofollow"        ... 新規タブのセキュリティ + スポンサー明示

すでに target と rel の両方があるアンカーはスキップ（冪等）。

使い方:
    python scripts/p3-link-attrs.py            # dry-run（差分件数のみ）
    python scripts/p3-link-attrs.py --apply    # 書き込み
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_REL = "content/posts"

# amazon.co.jp へのリンクを含む <a ...> タグのみを対象にする
ANCHOR_RE = re.compile(r"<a\b(?P<attrs>[^>]*)>")
AMAZON_RE = re.compile(r"amazon\.co\.jp")
ATTRS = ' target="_blank" rel="noopener sponsored nofollow"'


def tracked_posts() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", f"{POSTS_REL}/*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def fix(text: str) -> tuple[str, int]:
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        attrs = m.group("attrs")
        if not AMAZON_RE.search(attrs):
            return m.group(0)
        if "target=" in attrs and "rel=" in attrs:
            return m.group(0)
        count += 1
        return "<a" + attrs.rstrip() + ATTRS + ">"

    return ANCHOR_RE.sub(repl, text), count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== P3 affiliate link attributes ({mode}) ===", flush=True)

    files = tracked_posts()
    total = changed_files = 0
    for rel in files:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        with io.open(path, "r", encoding="utf-8-sig", newline="") as fh:
            original = fh.read()
        new, n = fix(original)
        if not n:
            continue
        changed_files += 1
        total += n
        print(f"  {os.path.basename(rel)}: +{n}", flush=True)
        if args.apply:
            with io.open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)

    print(
        f"完了: {total}件のリンクを更新（{changed_files}本）"
        + ("（書き込み済み）" if args.apply else "（dry-run）"),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
