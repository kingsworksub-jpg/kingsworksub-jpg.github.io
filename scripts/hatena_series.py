"""Choose one of the ten Hatena series names for a post, and build its header banner.

All ten names are always in play. The choice is deterministic: score the post's
frontmatter (title / description / tags / category) and the opening of its body
against each series' keyword rules, then take the highest score. Ties are broken
by the order the series are defined here, so the same post always gets the same
series no matter how many times it is re-checked.

The series name is NEVER added to the entry title: platform_sync.verify() matches
Hatena entries by exact frontmatter title, so changing the title would break
reconciliation. The name goes into an inline-styled HTML banner prepended to the
body instead (Hatena does not load this site's CSS).

    python hatena_series.py <slug>                       # chosen series + score breakdown
    python hatena_series.py --json <slug>                # machine-readable result
    python hatena_series.py --banner <slug>              # banner HTML only
    python hatena_series.py --prepend <slug> <html-file> # add banner before posting; JSON result
    python hatena_series.py --list                       # the ten series names

Adding/removing a name here is the only place needed to change the whole set.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import topic_plan as tp  # noqa: E402

# Definition order is also the tie-break order — do not reorder casually.
SERIES: tuple[str, ...] = (
    "迷ったときのこれ",
    "決める前のメモ",
    "選ぶときの目安",
    "比較してわかったこれ",
    "試した結果これ",
    "失敗が残したこれ",
    "後で効くこれ",
    "参考に残したこれ",
    "買う前に読むこれ",
    "選定の記録",
)

# Each series has strong / medium / weak regex signals. Weights below are per
# field; a pattern contributes at most 3 hits so a repetitive article can't
# drown out a single sharp signal in the title.
RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "迷ったときのこれ": {
        "strong": (r"迷っ?て", r"迷う", r"迷い", r"どっち", r"どちら", r"決めきれ", r"選べない", r"悩ん", r"悩む"),
        "medium": (r"おすすめ", r"候補", r"どれを", r"選ぶのに", r"結局これ", r"ひとつ?に絞"),
        "weak": (),
    },
    "決める前のメモ": {
        "strong": (r"決める前", r"判断する前", r"検討", r"事前に", r"確認し?ておき", r"チェックリスト", r"押さえ?ておき", r"下調べ"),
        "medium": (r"見落とし", r"見ておき", r"調べ", r"仕様を", r"スペックを", r"前提", r"確かめ"),
        "weak": (r"メモ", r"整理", r"準備"),
    },
    "選ぶときの目安": {
        "strong": (r"選び方", r"選ぶ(?:とき|際)?の(?:基準|目安)", r"比べる軸", r"比較軸", r"見るべき", r"目安", r"判断基準", r"軸で(?:比|選)"),
        "medium": (r"基準", r"スペック", r"仕様", r"特徴", r"違い", r"ポイント", r"用途", r"目的別", r"向いて"),
        "weak": (),
    },
    "比較してわかったこれ": {
        "strong": (r"比べ(?:て|た|る)", r"比較し(?:て|た)", r"違いがわか", r"差が(?:出|わか)", r"わかった"),
        "medium": (r"比較", r"対比", r"レーダーチャート", r"[3-7]本", r"[3-7]台"),
        "weak": (),
    },
    "試した結果これ": {
        "strong": (r"試し(?:て|た)", r"使ってみ", r"実際に(?:使|鳴ら|弾|測)", r"検証", r"テスト", r"計測", r"測っ?て"),
        "medium": (r"結果", r"体験", r"使い心地", r"手に取っ", r"レビュー", r"演奏", r"打ち込ん"),
        "weak": (r"使っ?た", r"使う"),
    },
    "失敗が残したこれ": {
        "strong": (r"失敗", r"やらか", r"後悔", r"痛い目", r"反省", r"落とし穴", r"罠", r"つまず", r"壊れ", r"故障", r"誤っ?た", r"間違い"),
        "medium": (r"注意点", r"気をつけ", r"回避", r"修復", r"補修", r"直し?た", r"ベタつき", r"ひび割れ", r"水滴", r"焦っ?た"),
        "weak": (r"弱点", r"不便", r"難し"),
    },
    "後で効くこれ": {
        "strong": (r"後で", r"将来", r"長く使", r"末永く", r"延命", r"買い替え", r"備え", r"残る", r"資産", r"続け(?:て|る)", r"維持", r"保守", r"寿命"),
        "medium": (r"数年", r"10年", r"習慣", r"継続", r"練習", r"鍛え", r"身につく", r"蓄積", r"交換", r"予備"),
        "weak": (),
    },
    "参考に残したこれ": {
        "strong": (r"参考", r"資料", r"記録として", r"まとめ", r"年表", r"歴史", r"背景", r"構造", r"仕組み", r"解説", r"用語"),
        "medium": (r"入門", r"基礎", r"知識", r"知っておき", r"覚え", r"年号", r"発売", r"成立", r"由来", r"成り立ち"),
        "weak": (r"メモ", r"読む"),
    },
    "買う前に読むこれ": {
        # Deliberately no bare "Amazon"/"円"/"発売": this blog's affiliate links and
        # price lists put those in nearly every comparison article, which would make
        # this series swallow everything. Price is only decisive when the headline
        # or description leads with it, not when a price appears deep in the body.
        "strong": (r"買う前", r"購入前", r"実売", r"相場", r"セール", r"値引き", r"割引", r"コスパ", r"費用", r"予算"),
        "medium": (r"価格", r"値段", r"税込", r"安い", r"高い", r"お得", r"型番", r"ブラックフライデー"),
        "weak": (),
    },
    "選定の記録": {
        "strong": (r"選定", r"厳選", r"絞っ?た", r"最終的?に", r"1台に", r"一台に", r"決定", r"採用", r"候補を", r"これに決"),
        "medium": (r"リスト", r"ピックアップ", r"取り上げ", r"5選", r"3選", r"4選", r"結論"),
        "weak": (r"比較", r"候補"),
    },
}

# Field weights. A hit in the headline matters far more than one deep in the body.
FIELD_WEIGHTS = {"title": {"strong": 6, "medium": 3, "weak": 1},
                 "description": {"strong": 4, "medium": 2, "weak": 1},
                 "tags": {"strong": 3, "medium": 2, "weak": 1},
                 "category": {"strong": 2, "medium": 1, "weak": 1},
                 "body": {"strong": 2, "medium": 1, "weak": 0}}
BODY_CHARS = 2500  # enough for the intro/axes, not so much that boilerplate dominates
HIT_CAP = 3

# These names describe the reader's INTENT, not the article's subject. A stray
# "価格" or "候補" buried in a deep dive must not turn it into a buying guide,
# so they only score fully when the frontmatter itself says so.
INTENT_SERIES = frozenset({"迷ったときのこれ", "決める前のメモ", "買う前に読むこれ", "選定の記録"})
INTENT_GATE_FACTOR = 0.3


def post_fields(slug: str) -> dict:
    """Read one post's frontmatter + body lead without Hugo. Mirrors topic_plan.posts()'s
    frontmatter parsing, with description added (that field is ignored there)."""
    path = os.path.join(tp.ROOT, "content", "posts", f"{slug}.md")
    if not os.path.exists(path):
        raise RuntimeError(f"content/posts/{slug}.md が見つかりません")
    s = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---", s, re.S)
    if not m:
        raise RuntimeError(f"content/posts/{slug}.md のfrontmatterが壊れています")
    fm, body = m.group(1), s[m.end():]

    def field(name: str, default: str = "") -> str:
        hit = re.search(rf'(?m)^{name}:\s*"?(.*?)"?\s*$', fm)
        return hit.group(1).strip() if hit else default

    tags_m = re.search(r"(?m)^tags:\s*\[([^\]]*)\]", fm)
    tags = [t.strip().strip("\"'") for t in tags_m.group(1).split(",")] if tags_m else []
    cat_m = re.search(r"(?m)^categories:\s*\[([^\]]*)\]", fm) or re.search(
        r"(?m)^categories:\s*\n\s*-\s*(\S+)", fm)
    category = re.sub(r"[\[\]\"' ]", "", cat_m.group(1).split(",")[0]) if cat_m else ""
    return {"slug": slug, "title": field("title"), "description": field("description"),
            "tags": tags, "category": category, "body": body[:BODY_CHARS]}


def score_post(fields: dict) -> dict[str, int]:
    """Score all ten series for one post. Always returns every series (zeros included)."""
    texts = {
        "title": [fields["title"]],
        "description": [fields["description"]],
        "tags": [" ".join(fields["tags"])],
        "category": [fields["category"]],
        "body": [fields["body"]],
    }
    scores = {name: 0 for name in SERIES}
    for name, rules in RULES.items():
        total = 0
        front_hit = False
        for field, chunks in texts.items():
            for tier, patterns in rules.items():
                for pattern in patterns:
                    hits = sum(min(len(re.findall(pattern, chunk)), HIT_CAP) for chunk in chunks)
                    if hits and tier in ("strong", "medium") and field in ("title", "description", "tags"):
                        front_hit = True
                    total += hits * FIELD_WEIGHTS[field][tier]
        if name in INTENT_SERIES and not front_hit:
            total = int(total * INTENT_GATE_FACTOR)
        scores[name] = total
    return scores


def ranked(fields: dict) -> list[dict]:
    scores = score_post(fields)
    # Definition order is the stable tie-break (Python's sort is stable).
    return [{"series": name, "score": scores[name]} for name in sorted(
        SERIES, key=lambda n: -scores[n])]


def choose_series(slug: str) -> str:
    return ranked(post_fields(slug))[0]["series"]


def chosen(slug: str) -> dict:
    r = ranked(post_fields(slug))[0]
    return {"slug": slug, "series": r["series"], "score": r["score"]}


def next_series_no(series: str, platforms: dict | None = None) -> int:
    """Sequential number within a series, counted from post-platforms.json records."""
    if platforms is None:
        platforms = tp.load(os.path.join(tp.S, "post-platforms.json"), {})
    used = [v.get("hatena_series_no", 0) for v in platforms.values()
            if v.get("hatena_series") == series and isinstance(v.get("hatena_series_no"), int)]
    return max(used, default=0) + 1


def banner_html(series: str, number: int) -> str:
    """Plain, inline-styled header. No punctuation in the name, no ranking language
    (no '1位'), no fixed post count — just the series and its number."""
    return (
        '<p class="hatena-series" style="margin:0 0 1.5em;padding:10px 14px;'
        'border:1px solid #d9d9d9;border-left:4px solid #e8590c;border-radius:6px;'
        'background:#fafafa;font-size:14px;line-height:1.5;">'
        f'<strong style="font-size:15px;">{series}</strong>'
        f'<span style="margin-left:8px;color:#666;">第{number}回</span>'
        '</p>\n'
    )


def prepend_banner(html_path: str, series: str, number: int) -> bool:
    """Put the banner at the top of an extracted HTML file. Idempotent: an existing
    hatena-series banner is replaced (so PUT updates never stack duplicates).
    Returns True if the file changed."""
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    banner = banner_html(series, number)
    new = re.sub(r'<p class="hatena-series".*?</p>\n?', "", html, count=1, flags=re.S)
    new = banner + new.lstrip("\n")
    if new == html:
        return False
    with open(html_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", nargs="?", help="content/posts/<slug>.md")
    ap.add_argument("html", nargs="?", help="extracted HTML file, for --prepend")
    ap.add_argument("--json", action="store_true", help="print the chosen series as JSON")
    ap.add_argument("--banner", action="store_true", help="print only the banner HTML")
    ap.add_argument("--prepend", action="store_true", help="prepend the chosen series banner to the HTML argument; prints {slug,series,series_no} as JSON")
    ap.add_argument("--list", action="store_true", help="list the ten series names")
    ap.add_argument("--all", action="store_true", help="with a slug: print all ten scores")
    a = ap.parse_args()

    if a.list:
        for i, name in enumerate(SERIES, 1):
            print(f"{i:2d}. {name}")
        return
    if not a.slug:
        ap.error("slug が必要です (--list を除く)")

    if a.prepend:
        if not a.html:
            ap.error("--prepend には HTML ファイルを続けて指定してください")
        series = chosen(a.slug)["series"]
        number = next_series_no(series)
        prepend_banner(a.html, series, number)
        print(json.dumps({"slug": a.slug, "series": series, "series_no": number}, ensure_ascii=False))
        return

    c = chosen(a.slug)
    if a.json:
        print(json.dumps(c, ensure_ascii=False))
    elif a.banner:
        sys.stdout.write(banner_html(c["series"], next_series_no(c["series"])))
    elif a.all:
        for row in ranked(post_fields(a.slug)):
            print(f"{row['score']:4d}  {row['series']}")
    else:
        print(f"{a.slug}: {c['series']} (score {c['score']}) 第{next_series_no(c['series'])}回")


if __name__ == "__main__":
    main()
