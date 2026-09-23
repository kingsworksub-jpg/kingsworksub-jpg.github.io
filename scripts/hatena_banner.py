"""Inline the .product-banner layout so it renders correctly WITHOUT the site CSS.

Hatena Blog does not load this site's stylesheet, so the banner's <img> falls back to
its natural (huge) size there. This rewrites every <a class="product-banner"> block with
explicit inline styles and fixed width/height attributes (120x120 thumbnail, 468x120
banner -- identical to assets/css/extended/product-links.css). CSS variables carry
fallbacks, so on the Hugo site the theme colours still apply.

Idempotent: a banner whose <a> already has a style attribute is left alone.

    python hatena_banner.py < in.html > out.html
"""

from __future__ import annotations

import re
import sys

BORDER = "var(--border,#d9d9d9)"
STYLES = {
    "a": (
        "display:flex;align-items:stretch;box-sizing:border-box;width:468px;max-width:100%;"
        "height:120px;margin:1.5rem auto;border:1px solid " + BORDER + ";border-radius:12px;"
        "overflow:hidden;text-decoration:none;background:var(--entry,#fff);"
    ),
    "img": (
        "display:block;box-sizing:border-box;width:120px;height:120px;max-width:120px;"
        "max-height:120px;flex:0 0 120px;margin:0;padding:0;object-fit:contain;background:#fff;"
        "border:0;border-right:1px solid " + BORDER + ";border-radius:0;"
    ),
    "info": (
        "display:flex;flex-direction:column;justify-content:center;gap:8px;padding:0 17px;"
        "flex:1;min-width:0;"
    ),
    "name": (
        "display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;"
        "text-overflow:ellipsis;font-weight:700;font-size:15px;line-height:1.3;"
        "color:var(--content,#222);"
    ),
    "cta": "font-size:13.6px;font-weight:600;color:#E8590C;",
}

BANNER = re.compile(r'<a\b[^>]*\bclass="product-banner"[^>]*>.*?</a>', re.S)


def _add_style(tag: str, style: str, extra_attrs: str = "") -> str:
    """Insert style (and extra attrs) into an opening tag, replacing any existing ones."""
    tag = re.sub(r'\s(style|width|height)="[^"]*"', "", tag) if extra_attrs else re.sub(r'\sstyle="[^"]*"', "", tag)
    return re.sub(r"\s*/?>$", lambda m: f' {extra_attrs}style="{style}"' + m.group(0).lstrip(), tag, count=1)


def _fix_banner(block: str) -> str:
    open_tag = re.match(r"<a\b[^>]*>", block).group(0)
    if re.search(r'\sstyle="', open_tag):
        return block  # already inlined
    out = block.replace(open_tag, _add_style(open_tag, STYLES["a"]), 1)
    out = re.sub(r"<img\b[^>]*>", lambda m: _add_style(m.group(0), STYLES["img"], 'width="120" height="120" '), out, count=1)
    for cls, key in (("product-banner-info", "info"), ("product-banner-name", "name"), ("product-banner-cta", "cta")):
        out = re.sub(
            rf'<span class="{cls}">', f'<span class="{cls}" style="{STYLES[key]}">', out, count=1
        )
    return out


def inline_banners(html: str) -> str:
    return BANNER.sub(lambda m: _fix_banner(m.group(0)), html)


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(inline_banners(sys.stdin.read()))
