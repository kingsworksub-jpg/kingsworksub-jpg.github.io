#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compress static images: resize JPEG if wider than MAX_W, re-encode q=QUALITY.
Keeps the smaller of (original, new) bytes per file. PNGs are recompressed only if
they shrink (format is kept). Prints a summary; writes new dims for resized files."""
import shutil
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "static" / "images"
MAX_W = 1600
Q = 82

saved_b, grew, resized, done = 0, 0, [], 0
for f in sorted(IMAGES.rglob("*")):
    ext = f.suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        continue
    try:
        im = Image.open(f)
        im.load()
    except Exception:
        continue
    w, h = im.size
    fmt = im.format
    nw, nh = w, h
    if ext in (".jpg", ".jpeg") and w > MAX_W:
        nh = round(h * MAX_W / w)
        nw = MAX_W
        im = im.resize((nw, nh), Image.LANCZOS)
    tmp = f.with_suffix(f.suffix + ".tmp")
    if ext == ".png":
        im.save(tmp, "PNG", optimize=True)
    else:
        if im.mode in ("RGBA", "LA", "PA"):
            im = im.convert("RGB")
        im.save(tmp, "JPEG", quality=Q, optimize=True)
    before, after = f.stat().st_size, tmp.stat().st_size
    if after < before:
        shutil.move(str(tmp), str(f))
        saved_b += before - after
        if (nw, nh) != (w, h):
            resized.append((f, w, h, nw, nh))
        done += 1
    else:
        tmp.unlink(missing_ok=True)
        grew += 1

print(f"compressed: {done} files, saved {saved_b/1024:.0f}KB, skipped(no gain|larger): {grew}")
for f, w, h, nw, nh in resized:
    print(f"RESIZED {f.relative_to(ROOT)}: {w}x{h} -> {nw}x{nh}")