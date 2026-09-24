#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compress JPEG images in place (resize if wider than MAX_W, re-encode q=QUALITY)."""
import sys, os
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MAX_W = 1600
QUALITY = 82

targets = [
    "static/images/hard-bop-blue-note/jazz-messengers-den-haag-1963.jpg",
    "static/images/hard-bop-blue-note/art-blakey-portrait.jpg",
    "static/images/modal-jazz/bill-evans-1961.jpg",
    "static/images/modal-jazz/john-coltrane-playing-sax.jpg",
    "static/images/jazz-shoes/celine-ss26-jazz-shoes.jpg",
    "static/images/jazz-shoes/celine-ss26-suited-booted.jpg",
    "static/images/jazz-shoes/serge-gainsbourg-jazz-shoes.jpg",
    "static/images/jazz-shoes/street-style-white-tee-midi.jpg",
    "static/images/alan-boguslavsky/heroes-2007-tour-sevilla-1.jpg",
    "static/images/alan-boguslavsky/heroes-2007-tour-sevilla-2.jpg",
]

for rel in targets:
    p = ROOT / rel
    if not p.exists():
        print(f"SKIP (missing): {rel}")
        continue
    before = p.stat().st_size
    im = Image.open(p)
    w, h = im.size
    nw, nh = w, h
    if w > MAX_W:
        nh = round(h * MAX_W / w)
        nw = MAX_W
        im = im.resize((nw, nh), Image.LANCZOS)
    im.save(p, "JPEG", quality=QUALITY, optimize=True)
    after = p.stat().st_size
    print(f"{rel}: {w}x{h} -> {nw}x{nh} | {before/1024:.0f}KB -> {after/1024:.0f}KB")