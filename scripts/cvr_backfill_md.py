# -*- coding: utf-8 -*-
"""P1: 公開Markdownへ「コンバージョン率改善プランA」のCVRパーツをバックフィルする。

既存の figure / 画像URL / アフィリエイトリンク / 文体 / 内部リンクは変更しない。
挿入するのは次の4種類だけ（すべて data-cvr 属性で冪等）:

  1. cta-intro    : 導入文直後のメイン商品CTA（既存の商品画像＋ASINを利用）
  2. text-ASIN    : 各商品画像リンク直後のテキストリンク（最大6本）
  3. price        : 価格に触れた段落直後の実売価格確認note（1回だけ）
  4. assurance    : まとめ直サイズ・設置・保証・ランニングコストの不安解消

使い方:
    python scripts/cvr_backfill_md.py --dry-run              # 差分だけ表示
    python scripts/cvr_backfill_md.py --apply                # 19本へ書き込む
    python scripts/cvr_backfill_md.py --apply --slugs a.md,b.md
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_DIR = os.path.join(ROOT, "content", "posts")
DEFAULT_SLUGS = [
    "piano-practice-apps-3choice-2026",
    "sony-pslx3bt-deep-dive-2026",
    "bodum-douro-carafe-deep-dive-2026",
    "odate-akita-sugi-sake-set-deep-dive-2026",
    "budget-whisky-10choice-2026",
    "canned-coffee-5choice-2026",
    "sodastream-terra-carbonation-guide-2026",
    "turntable-5choice-2026",
    "record-stylus-lifespan-guide-2026",
    "modal-jazz-challenge",
    "condenser-mic-5choice-2026",
    "sampler-5choice-2026",
    "statement-hat-trends-autumn-2026",
    "jazz-style-fashion-revival-2026",
    "daw-5choice-2026",
    "dtm-school-or-self-study-2026",
    "midi-keyboard-5choice-2026",
    "adult-piano-learning-2026",
    "anime-and-jazz",
]

DEFAULT_TAG = "nakimoto1-22"
MAX_TEXT_LINKS = 6

FIGURE_RE = re.compile(r"<figure\b[^>]*>.*?</figure>", re.S)
ANCHOR_RE = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
ASIN_RE = re.compile(r"amazon\.co\.jp/(?:dp|gp/product)/([A-Z0-9]{10})")
TAG_RE = re.compile(r"[?&]tag=([A-Za-z0-9_-]+)")
IMG_RE = re.compile(r'<img\b[^>]*?src="([^"]+)"[^>]*?alt="([^"]*)"', re.S)
CAPTION_RE = re.compile(r"<figcaption\b[^>]*>(.*?)</figcaption>", re.S)
CREDIT_RE = re.compile(r'<span class="credit".*?</span>', re.S)
HTMLTAG_RE = re.compile(r"<[^>]+>")

PRICE_RE = re.compile(r"[0-9][0-9,]*\s*円")
PRICE_CTX_RE = re.compile(r"価格|定価|実売|参考価格|円前後|円台|コスパ|値段")

PRICE_NOTE = (
    '<p class="cvr-price-note" data-cvr="price">'
    "※記載した価格は参考だ。現在の実売価格やタイムセール・ポイント還元の状況は、Amazonリンクから確認してほしい。"
    "</p>"
)
ASSURANCE = (
    '<p class="cvr-assurance" data-cvr="assurance">'
    "サイズ感や設置場所、保証、ランニングコストやメンテナンスの手間まで含めて判断したい場合は、"
    "商品ページの仕様欄とレビューが参考になる。付属品と返品条件もあわせて確認しておけば、"
    "届いてから困ることはない。"
    "</p>"
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", HTMLTAG_RE.sub("", text)).strip()


def _products(body: str) -> list[dict]:
    products = []
    for m in FIGURE_RE.finditer(body):
        fig = m.group(0)
        anchors = ANCHOR_RE.findall(fig)
        link = ""
        for href, _inner in anchors:
            if ASIN_RE.search(href):
                link = href
                break
        if not link:
            continue
        asin = ASIN_RE.search(link).group(1)
        tag_m = TAG_RE.search(link)
        tag = tag_m.group(1) if tag_m else DEFAULT_TAG
        img_m = IMG_RE.search(fig)
        img, alt = (img_m.group(1), img_m.group(2)) if img_m else ("", "")
        cap_m = CAPTION_RE.search(fig)
        cap = _clean(CREDIT_RE.sub("", cap_m.group(1))) if cap_m else ""
        name = alt or cap or asin
        if len(name) > 34:
            name = name[:34].rstrip("。・、 ") + "…"
        products.append({
            "asin": asin, "tag": tag, "img": img, "name": name,
            "url": f"https://www.amazon.co.jp/dp/{asin}?tag={tag}",
            "figure_end": m.end(),
        })
    return products


def _intro_cta(p: dict) -> str:
    img = f'\n<img src="{p["img"]}" alt="{p["name"]}" loading="lazy">' if p["img"] else ""
    return (
        '<div class="cvr-cta-block" data-cvr="cta-intro">\n'
        '<p class="cvr-cta-title">まずはこの一本から</p>\n'
        f'<a class="product-banner" href="{p["url"]}" target="_blank" rel="noopener sponsored nofollow">{img}\n'
        '<span class="product-banner-info">\n'
        f'<span class="product-banner-name">{p["name"]}</span>\n'
        '<span class="product-banner-cta">Amazonで見る →</span>\n'
        "</span>\n"
        "</a>\n"
        "</div>"
    )


def _text_link(p: dict) -> str:
    return (
        f'<p class="cvr-text-link" data-cvr="text-{p["asin"]}">'
        f'<a href="{p["url"]}" target="_blank" rel="noopener sponsored nofollow">{p["name"]}の実売価格・レビューをAmazonで確認する →</a>'
        "</p>"
    )


def _insert_after(body: str, pos: int, block: str) -> str:
    return body[:pos] + "\n\n" + block + "\n\n" + body[pos:].lstrip("\n")


def optimize(text: str) -> tuple[str, list[str]]:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end == -1:
            return text, ["frontmatter parsing failed"]
        front = text[: end + 5]
        body = text[end + 5 :]
    else:
        front, body = "", text

    changes = []
    products = _products(body)

    # 1. 冒頭CTA（既存ならスキップ）
    shift = 0
    if products and 'data-cvr="cta-intro"' not in body:
        first_heading = body.find("\n## ")
        first_rule = body.find("\n---\n")
        candidates = [x for x in (first_heading, first_rule) if x != -1]
        pos = min(candidates) + 1 if candidates else len(body)
        before = len(body)
        body = _insert_after(body, pos, _intro_cta(products[0]))
        shift = len(body) - before
        changes.append("導入直後にメイン商品のCTAブロックを追加")

    # 2. 商品画像リンク直後のテキストリンク（最大6本）
    #    後ろから挿入すると手前の figure の位置がズレない。冒頭CTAの分だけオフセットを足す。
    targets = [p for p in products if f'data-cvr="text-{p["asin"]}"' not in body][:MAX_TEXT_LINKS]
    for p in sorted(targets, key=lambda x: x["figure_end"], reverse=True):
        pos = p["figure_end"] + shift
        body = _insert_after(body, pos, _text_link(p))
    if targets:
        changes.append(f"商品画像リンク直後にテキストリンクを{len(targets)}本追加")

    # 3. 価格note（1回だけ）
    if 'data-cvr="price"' not in body:
        blocks = re.split(r"\n{2,}", body)
        for i, block in enumerate(blocks):
            stripped = block.strip()
            if not stripped or stripped.startswith(("<", "|", "!", "##")):
                continue
            if PRICE_RE.search(stripped) and PRICE_CTX_RE.search(stripped):
                blocks.insert(i + 1, PRICE_NOTE)
                body = "\n\n".join(blocks)
                changes.append("価格に触れた段落の直後に実売価格の確認noteを追加")
                break

    # 4. まとめ直前の不安解消
    if 'data-cvr="assurance"' not in body:
        m = re.search(r"\n## まとめ[^\n]*\n", body)
        if m:
            pos = m.start() + 1
        else:
            headings = list(re.finditer(r"\n## [^\n]+\n", body))
            pos = headings[-1].start() + 1 if headings else -1
        if pos != -1:
            body = _insert_after(body, pos, ASSURANCE)
            changes.append("まとめ直前に購入前の不安解消段落を追加")

    result = (front + body).replace("\r\n", "\n")
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result, changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="実際にファイルを書き込む（既定はdry-run）")
    ap.add_argument("--slugs", default=None, help="対象slugをカンマ区切りで指定（既定はP1候補19本）")
    args = ap.parse_args()

    slugs = args.slugs.split(",") if args.slugs else DEFAULT_SLUGS
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== P1 CVR backfill ({mode}) / {len(slugs)}本 ===", flush=True)
    total_changes = 0
    for slug in slugs:
        path = os.path.join(POSTS_DIR, slug + ".md")
        if not os.path.exists(path):
            print(f"  [SKIP] ファイルなし: {slug}", flush=True)
            continue
        with io.open(path, "r", encoding="utf-8-sig", newline="") as fh:
            original = fh.read()
        new, changes = optimize(original)
        if not changes:
            print(f"  [SKIP] 変更なし: {slug}", flush=True)
            continue
        total_changes += len(changes)
        print(f"  [{slug}]", flush=True)
        for c in changes:
            print(f"    - {c}", flush=True)
        if args.apply:
            with io.open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
    print(f"完了: {total_changes}件の変更" + ("（書き込み済み）" if args.apply else "（dry-run）"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
