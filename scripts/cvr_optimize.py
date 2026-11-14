# -*- coding: utf-8 -*-
"""コンバージョン率改善プランA を Ameba 投稿パイプラインで機械的に適用する。

`コンバージョン率改善プランA.md` の処理ルール(1〜6)のうち、記事を壊さずに
決定的に適用できる部分を担当する:

  1. 既存タグ・リンク・文体の維持
     - 本文の HTML は書き換え対象を限定し、`<figure>` / 画像URL / 既存リンク
       (`aid=...` などを含む) / 内部リンクには一切触れない。
  2. CTA ブロックとテキストリンクの挿入
     - 冒頭(導入文の直後)とまとめに CTA ブロック(商品画像つきカード)を追加。
     - Amazon 商品画像リンクの直後にテキストリンクを追加。
  3. 消耗品・関連アクセサリ導線
     - `[SUB_LINK: 商品名]` プレースホルダーを実リンクに解決する。
  4. 価格表記とクリックインセンティブ
     - 価格に触れている段落の直後に「実売価格はリンク先で確認」の一文を追加。
  5. 購入直前の心理的障壁の解消
     - まとめセクションの CTA 直前に、サイズ・設置・保証・ランニングコスト
       などの不安を先回りする短い段落を追加。
  6. スマホでの視認性
     - 挿入する要素は 1 要素 1 段落・短い文に限定し、長い段落を増やさない。

LLM(ブログ投稿ジョブ)側が `[CTA_BLOCK: ...]` / `[TEXT_LINK: ...]` /
`[SUB_LINK: ...]` を残した場合の解決も行う(プレースホルダーは公開物に
残さない)。ただし通常は記事 Markdown に実リンクを書くのが原則で、これは
書き漏らしを拾うための安全網。

使い方(パイプ):
    python scripts/cvr_optimize.py --platform ameba < in.html > out.html

使い方(JSON。プランAの出力フォーマット):
    python scripts/cvr_optimize.py --platform ameba --json < in.html

使い方(関数):
    from cvr_optimize import optimize
    html, changes = optimize(html, platform="ameba")
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import urllib.parse

DEFAULT_TAG = "nakimoto1-22"

CTA_MARK = 'data-cvr="cta"'
TEXT_MARK = 'data-cvr="text"'
PRICE_MARK = 'data-cvr="price"'
ASSURANCE_MARK = 'data-cvr="assurance"'

ASIN_RE = re.compile(r"amazon\.co\.jp/(?:dp|gp/product)/([A-Z0-9]{10})")
FIGURE_RE = re.compile(r'<figure\b[^>]*class="[^"]*\bphoto\b[^"]*"[^>]*>.*?</figure>', re.S)
ANCHOR_RE = re.compile(r'<a\b[^>]*\bhref="([^"]*amazon\.co\.jp[^"]*)"[^>]*>(.*?)</a>', re.S)
IMG_RE = re.compile(r'<img\b[^>]*?\bsrc="([^"]+)"[^>]*?>', re.S)
ALT_RE = re.compile(r'\balt="([^"]*)"')
CAPTION_RE = re.compile(r"<figcaption\b[^>]*>(.*?)</figcaption>", re.S)
CREDIT_RE = re.compile(r'<span class="credit".*?</span>', re.S)
TAG_RE = re.compile(r"<[^>]+>")

PLACEHOLDER_RE = re.compile(
    r"\[(CTA_BLOCK|TEXT_LINK|SUB_LINK):\s*([^\]\n]+?)\s*\]"
)

PRICE_PATTERN = re.compile(r"[0-9][0-9,]*\s*円")
PRICE_CONTEXT = re.compile(r"価格|定価|実売|参考価格|価格帯|円前後|円台")

PRICE_NOTE = (
    "※現在の実売価格やタイムセール・ポイント還元の状況は、"
    "以下のAmazonリンクからご確認ください。"
)
ASSURANCE = (
    "サイズ感や設置場所、保証、ランニングコストやメンテナンスの手間まで含めて判断したい場合は、"
    "商品ページの仕様欄とレビューが参考になります。付属品と返品条件もあわせて確認しておくと、"
    "届いてから困ることはありません。"
)

# インラインスタイル(Ameba にはサイトCSSが無いため、生成要素は自前で装飾する)
STYLE = {
    "box": (
        "border:1px solid #e3d9c6;border-radius:10px;padding:12px 14px;"
        "margin:1.4em 0;background:#fbf7ef"
    ),
    "title": "font-weight:700;font-size:1rem;margin:0 0 8px;line-height:1.5",
    "link": (
        "display:flex;align-items:center;gap:12px;text-decoration:none;color:inherit;"
        "border:0"
    ),
    "img": (
        "width:96px;height:96px;max-width:96px;max-height:96px;object-fit:contain;"
        "background:#fff;border:1px solid #eee;border-radius:8px;flex:0 0 96px;margin:0"
    ),
    "info": "flex:1;min-width:0",
    "name": (
        "display:block;font-weight:700;font-size:0.95rem;line-height:1.4;"
        "color:#222;margin:0 0 6px"
    ),
    "cta": "display:block;color:#E8590C;font-weight:700;font-size:0.95rem",
    "text_link": "margin:0.6em 0 1.3em;font-size:0.95rem;line-height:1.6",
    "text_anchor": (
        "color:#c2410c;font-weight:600;text-decoration:none;"
        "border-bottom:1px solid #f0b892"
    ),
    "price": "font-size:0.8em;color:#777;margin:0.4em 0 1.2em;line-height:1.6",
    "assurance": (
        "font-size:0.92rem;color:#555;background:#f6f6f4;border-left:3px solid #c2410c;"
        "padding:8px 12px;margin:1.2em 0;line-height:1.7"
    ),
}


def _esc(text: str) -> str:
    return htmllib.escape(text or "", quote=True)


def _strip_tags(fragment: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub("", fragment)).strip()


def _caption_of(figure: str) -> str:
    m = CAPTION_RE.search(figure)
    if not m:
        return ""
    cap = CREDIT_RE.sub("", m.group(1))
    return _strip_tags(cap)


def _first_img(fragment: str):
    m = IMG_RE.search(fragment)
    if not m:
        return None
    alt = ALT_RE.search(m.group(0))
    return m.group(1), (alt.group(1) if alt else "")


def collect_products(body: str):
    """図版の Amazon リンクから (ASIN, 画像URL, 商品名, キャプション) を集める。

    既存の <figure> の中身(画像URL・alt・キャプション)は変更せず、参照するだけ。
    """
    products = []
    for fig in FIGURE_RE.findall(body):
        a = ANCHOR_RE.search(fig)
        if not a:
            continue
        asin_m = ASIN_RE.search(a.group(1))
        if not asin_m:
            continue
        img = _first_img(a.group(2)) or _first_img(fig)
        caption = _caption_of(fig)
        name = caption or (img[1] if img else "") or asin_m.group(1)
        products.append({
            "asin": asin_m.group(1),
            "img": img[0] if img else "",
            "alt": img[1] if img else "",
            "caption": caption,
            "name": name,
        })
    return products


def _find_product(products, hint: str):
    """プレースホルダーの商品名から、記事内の商品をゆるく特定する。"""
    if not hint:
        return None
    hint_m = ASIN_RE.search(hint)
    if hint_m:
        for p in products:
            if p["asin"] == hint_m.group(1):
                return p
        return {"asin": hint_m.group(1), "img": "", "alt": "", "caption": "", "name": hint}
    key = re.sub(r"\s+", "", hint)
    for p in products:
        hay = re.sub(r"\s+", "", f"{p['name']} {p['caption']} {p['alt']}")
        if key and (key in hay or hay in key):
            return p
    return None


def _amazon_url(asin: str, keyword: str, tag: str) -> str:
    if asin:
        return f"https://www.amazon.co.jp/dp/{asin}?tag={tag}"
    q = urllib.parse.quote_plus(keyword)
    return f"https://www.amazon.co.jp/s?k={q}&tag={tag}"


def _cta_block(product: dict, tag: str, lead: str = "価格とレビューをまとめて確認") -> str:
    name = product.get("name") or product["asin"]
    short = name if len(name) <= 44 else name[:43] + "…"
    img = product.get("img") or ""
    alt = product.get("alt") or short
    url = _amazon_url(product["asin"], name, tag)
    thumb = (
        f'<img src="{_esc(img)}" alt="{_esc(alt)}" width="96" height="96" loading="lazy" '
        f'style="{STYLE["img"]}">'
        if img else ""
    )
    return (
        f'<div class="cvr-cta-block" {CTA_MARK} style="{STYLE["box"]}">'
        f'<p class="cvr-cta-title" style="{STYLE["title"]}">{_esc(lead)}</p>'
        f'<a class="cvr-cta-link" href="{_esc(url)}" target="_blank" '
        f'rel="noopener sponsored nofollow" style="{STYLE["link"]}">'
        f'{thumb}'
        f'<span class="cvr-cta-info" style="{STYLE["info"]}">'
        f'<span class="cvr-cta-name" style="{STYLE["name"]}">{_esc(short)}</span>'
        f'<span class="cvr-cta-action" style="{STYLE["cta"]}">Amazonで見る →</span>'
        f'</span></a></div>'
    )


def _text_link(asin: str, keyword: str, label: str, tag: str) -> str:
    url = _amazon_url(asin, keyword, tag)
    mark = TEXT_MARK + (f' data-cvr-asin="{_esc(asin)}"' if asin else "")
    return (
        f'<p class="cvr-text-link" {mark} style="{STYLE["text_link"]}">'
        f'<a href="{_esc(url)}" target="_blank" rel="noopener sponsored nofollow" '
        f'style="{STYLE["text_anchor"]}">{_esc(label)}</a></p>'
    )


def _price_note() -> str:
    return (
        f'<p class="cvr-price-note" {PRICE_MARK} style="{STYLE["price"]}">'
        f"{_esc(PRICE_NOTE)}</p>"
    )


def _assurance() -> str:
    return (
        f'<p class="cvr-assurance" {ASSURANCE_MARK} style="{STYLE["assurance"]}">'
        f"{_esc(ASSURANCE)}</p>"
    )


def resolve_placeholders(body: str, products, tag: str, platform: str = "ameba"):
    """`[CTA_BLOCK: ...]` / `[TEXT_LINK: ...]` / `[SUB_LINK: ...]` を実HTMLにする。"""
    changes = []

    def fallback(label: str, keyword: str, text: str) -> str:
        # Ameba は検索リンクを Ameba Pick に変換できず、リンクだけ外れて
        # 「押せない導線」になる。ASIN不明のプレースホルダーは出さない。
        if platform == "ameba":
            changes.append(f"{label}: ASINを特定できないためAmebaではリンクを挿入しません")
            return ""
        changes.append(f"{label}: ASINを特定できず検索リンクにしました")
        return _text_link("", keyword, text, tag)

    def repl(m: re.Match) -> str:
        kind, payload = m.group(1), m.group(2).strip()
        parts = [p.strip() for p in payload.split("|")]
        if kind == "CTA_BLOCK":
            product = _find_product(products, parts[0]) or (products[0] if products else None)
            if not product:
                changes.append("CTAブロック: 商品を特定できないため挿入しません")
                return ""
            changes.append(f"CTAブロックのプレースホルダーを実リンクに変換: {parts[0]}")
            return _cta_block(product, tag)
        if kind == "TEXT_LINK":
            label = parts[0]
            keyword = parts[1] if len(parts) > 1 else parts[0]
            asin = ""
            product = _find_product(products, keyword)
            if product:
                asin = product["asin"]
            elif re.fullmatch(r"[A-Z0-9]{10}", keyword):
                asin = keyword
            if not asin:
                return fallback(f"テキストリンク「{label}」", keyword, label)
            changes.append(f"テキストリンクのプレースホルダーを実リンクに変換: {label}")
            return _text_link(asin, keyword, label, tag)
        # SUB_LINK
        name = parts[0]
        hint = parts[1] if len(parts) > 1 else parts[0]
        product = _find_product(products, hint)
        asin = product["asin"] if product else ""
        if not asin and re.fullmatch(r"[A-Z0-9]{10}", hint):
            asin = hint
        if not asin:
            return fallback(f"関連商品「{name}」", hint, f"{name} をAmazonで確認する →")
        changes.append(f"消耗品・関連商品リンクのプレースホルダーを実リンクに変換: {name}")
        return _text_link(asin, hint, f"{name} をAmazonで確認する →", tag)

    out, n = PLACEHOLDER_RE.subn(repl, body)
    if n and not changes:
        changes.append(f"プレースホルダーを{n}件解決")
    return out, changes



def _insert_intro_cta(body: str, products, tag: str) -> tuple[str, str | None]:
    if not products:
        return body, None
    if CTA_MARK in body[:4000]:
        return body, None
    end = body.find("</p>")
    if end == -1:
        return body, None
    block = _cta_block(products[0], tag, lead="この記事の主役をまずチェック")
    return body[: end + 4] + "\n" + block + body[end + 4:], "導入文の直後にCTAブロックを追加"


def _insert_figure_links(body: str, products, tag: str) -> tuple[str, str | None]:
    if not products:
        return body, None
    by_asin = {}
    for p in products:
        by_asin.setdefault(p["asin"], p)
    existing = set(re.findall(r'data-cvr-asin="([A-Z0-9]{10})"', body))
    existing_count = len(re.findall(r'data-cvr="text"', body))
    if existing_count >= 6:
        return body, None
    added = 0
    pieces = []
    last = 0
    for m in FIGURE_RE.finditer(body):
        pieces.append(body[last:m.end()])
        last = m.end()
        a = ANCHOR_RE.search(m.group(0))
        if not a or existing_count + added >= 6:
            continue
        asin_m = ASIN_RE.search(a.group(1))
        if not asin_m:
            continue
        asin = asin_m.group(1)
        if asin in existing:
            continue
        p = by_asin[asin]
        cap = p["caption"] or p["name"]
        if len(cap) <= 24 and "。" not in cap:
            label = f"「{cap}」の価格・レビューをAmazonで確認する →"
        else:
            label = "この商品の価格・レビューをAmazonで確認する →"
        pieces.append("\n" + _text_link(asin, cap, label, tag))
        existing.add(asin)
        added += 1
    if not added:
        return body, None
    pieces.append(body[last:])
    return "".join(pieces), f"商品画像リンクの直後にテキストリンクを{added}件追加"


def _insert_price_note(body: str) -> tuple[str, str | None]:
    if PRICE_MARK in body:
        return body, None
    for m in re.finditer(r"<p\b[^>]*>(.*?)</p>", body, re.S):
        text = _strip_tags(m.group(1))
        if PRICE_PATTERN.search(text) and PRICE_CONTEXT.search(text):
            return body[:m.end()] + "\n" + _price_note() + body[m.end():], \
                "価格に触れている段落の直後に実売価格の確認を促す一文を追加"
    return body, None


def _summary_point(body: str) -> int:
    h = re.search(r"<h2\b[^>]*>(?:(?!</h2>).)*?(?:まとめ|結論|総括)(?:(?!</h2>).)*?</h2>", body, re.S)
    if h:
        nxt = body.find("<h2", h.end())
        if nxt != -1:
            return nxt
    # まとめ見出しが無い記事では「関連記事」ブロックの直前に入れる(回遊リンクは最後に残す)
    rel = re.search(r"<h2\b[^>]*>(?:(?!</h2>).)*?関連記事(?:(?!</h2>).)*?</h2>", body, re.S)
    if rel:
        return rel.start()
    return len(body)


def _insert_summary_cta(body: str, products, tag: str) -> tuple[str, str | None]:
    if not products or ASSURANCE_MARK in body:
        return body, None
    pos = _summary_point(body)
    block = "\n" + _assurance() + "\n" + _cta_block(products[-1], tag, lead="購入前の最終チェック") + "\n"
    return body[:pos] + block + body[pos:], \
        "まとめに購入前の不安を解消する補足とCTAブロックを追加"


def optimize(body: str, platform: str = "ameba", tag: str = DEFAULT_TAG):
    """本文HTMLにプランAの導線最適化を適用し、(html, changes) を返す。冪等。

    platform は Ameba 判定に使う(ASIN不明のAmazon検索リンクは、Amebaでは
    Pickに変換できずリンクが外れるため挿入しない)。
    """
    changes: list[str] = []

    body, ph_changes = resolve_placeholders(body, collect_products(body), tag, platform)
    changes += ph_changes

    products = collect_products(body)  # プレースホルダー解決後の状態で再収集

    body, c = _insert_intro_cta(body, products, tag)
    if c:
        changes.append(c)
    body, c = _insert_figure_links(body, products, tag)
    if c:
        changes.append(c)
    body, c = _insert_price_note(body)
    if c:
        changes.append(c)
    body, c = _insert_summary_cta(body, products, tag)
    if c:
        changes.append(c)

    return body, changes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", default="ameba", choices=["ameba", "hatena", "note", "github"])
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--json", action="store_true", help="プランAのJSON形式で出力する")
    args = parser.parse_args()

    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

    body = sys.stdin.read()
    optimized, changes = optimize(body, platform=args.platform, tag=args.tag)
    if args.json:
        print(json.dumps({"optimized_body": optimized, "changes_summary": changes},
                         ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(optimized)


if __name__ == "__main__":
    main()
