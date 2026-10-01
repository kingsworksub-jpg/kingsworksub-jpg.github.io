"""Inline the photo--left / photo--right float layout so figures wrap text on Hatena Blog.

Hatena Blog does not load this site's stylesheet, so <figure class="photo photo--left|right">
would otherwise stack as full-width blocks there. This adds inline styles that mirror
assets/css/extended/figures.css: the figure floats at 220px (max 42% so phone screens keep
a readable text column), the image fills it, and the caption/credit get small type.
Headings get clear:both so a float never runs into the next section, and a clearing div
is appended after the body.

Idempotent: a figure that already has a style attribute is left alone, and the clearing
div is only appended once.

    python hatena_figures.py < in.html > out.html
"""

from __future__ import annotations

import re
import sys

FIGURE = re.compile(r'<figure\b([^>]*)\bclass="photo photo--(left|right)"([^>]*)>(.*?)</figure>', re.S)
CLEAR_DIV = '<div style="clear:both"></div>'

FIG_STYLE = {
    "left": "float:left;width:220px;max-width:42%;margin:0.3em 1.2em 0.8em 0",
    "right": "float:right;width:220px;max-width:42%;margin:0.3em 0 0.8em 1.2em",
}
IMG_STYLE = "width:100%;height:auto;display:block;margin:0"
CAPTION_STYLE = "font-size:0.8em;line-height:1.5;margin:0.3em 0 0;text-align:left"
CREDIT_STYLE = "display:block;font-size:0.72em;line-height:1.4;color:#888;margin-top:0.2em"


def _fix_figure(m: re.Match) -> str:
    before, side, after, body = m.group(1), m.group(2), m.group(3), m.group(4)
    if "style=" in before + after:
        return m.group(0)  # already inlined
    body = re.sub(r"<img\b(?![^>]*\sstyle=)", f'<img style="{IMG_STYLE}"', body, count=1)
    body = body.replace("<figcaption>", f'<figcaption style="{CAPTION_STYLE}">')
    body = body.replace('<span class="credit">', f'<span class="credit" style="{CREDIT_STYLE}">')
    return f'<figure{before}class="photo photo--{side}"{after} style="{FIG_STYLE[side]}">{body}</figure>'


def _clear_heading(m: re.Match) -> str:
    tag, attrs = m.group(1), m.group(2) or ""
    if "style=" in attrs:
        return m.group(0)
    return f'<{tag}{attrs} style="clear:both">'


def inline_figures(html: str) -> str:
    out, n = FIGURE.subn(_fix_figure, html)
    if n == 0:
        return html
    out = re.sub(r"<(h[23])(\s[^>]*)?>", _clear_heading, out)
    if CLEAR_DIV not in out:
        out = out.rstrip("\n") + "\n" + CLEAR_DIV + "\n"
    return out


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(inline_figures(sys.stdin.read()))
