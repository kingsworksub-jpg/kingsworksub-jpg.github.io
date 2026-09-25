#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""各記事の og:image の実寸を取得し、frontmatter に
ogImageWidth / ogImageHeight を設定する(冪等)。"""
import re
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "content" / "posts"
IMAGES = ROOT / "static" / "images" / "og"

def get_first_og(md):
    m = re.search(r'^images\s*:\s*\[\s*"(/images/og/[^"]+)"', md, re.M)
    return m.group(1) if m else None

changed = 0
skipped = []
for p in sorted(POSTS.glob("*.md")):
    md = p.read_text(encoding="utf-8")
    if re.search(r"^draft\s*:\s*true", md, re.M | re.I):
        continue
    og = get_first_og(md)
    has_dims = bool(re.search(r"^ogImageWidth\s*:\s*\d+", md, re.M)) and \
               bool(re.search(r"^ogImageHeight\s*:\s*\d+", md, re.M))
    if not og:
        skipped.append(f"{p.name}: og images なし")
        continue
    f = IMAGES / Path(og).name
    if not f.exists():
        skipped.append(f"{p.name}: {f.name} が存在しない")
        continue
    if has_dims:
        continue
    w, h = Image.open(f).size
    lines = md.splitlines()
    out = []
    for ln in lines:
        out.append(ln)
        if ln.startswith("images:"):
            out.append(f"ogImageWidth: {w}")
            out.append(f"ogImageHeight: {h}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    changed += 1
    print(f"{p.name}: {w}x{h} added")

print(f"\nupdated: {changed}")
if skipped:
    print("skipped:")
    for s in skipped:
        print("  -", s)