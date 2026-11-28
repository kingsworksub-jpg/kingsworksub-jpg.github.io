# -*- coding: utf-8 -*-
"""ブログ記事を note.com 向けの投稿用テキストに変換する。

note の仕様:
  - タイトルは 15〜25 文字が推奨（一覧・X で省略されない）
  - タグは本文末尾に「#タグ」形式で並べる（1行に並べるのが一般的）
  - 画像は本文中に https の絶対URLで貼る
  - 独自記法の <figure> / <span class="credit"> は解釈されないため、
    画像は Markdown の ![]() に変え、出典は括弧書きにする
  - フィード表示用の冒頭に 1〜2 段落のリード文を置く

使い方:
  python scripts/convert-to-note.py <slug> [出力ファイル]
  例: python scripts/convert-to-note.py hard-bop-blue-note-golden-age
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from affiliate_tag import rewrite_for  # noqa: E402
import distribution as dist  # noqa: E402

BASE = r"C:\Users\norio\my-github-blog"
POSTS = os.path.join(BASE, "content", "posts")
NOTE_FULL = os.path.join(BASE, "scripts", "note-full")
SITE = "https://kingsworksub-jpg.github.io"
CTA_RE = re.compile(r"<!-- note-paywall-cta:start -->.*?<!-- note-paywall-cta:end -->", re.S)
PAYWALL_MARKER = "<!-- note-paywall -->"


def parse_front_matter(text):
    """--- で囲まれた front matter を返す。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4:].lstrip("\n")
    meta = {}
    for line in raw.split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip().rstrip(",")
        if v.startswith("[") and v.endswith("]"):
            items = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",")]
            meta[k] = [i for i in items if i]
        else:
            meta[k] = v.strip('"').strip("'")
    return meta, body


def convert_figures(body):
    """<figure class="photo photo--left"> ブロックを Markdown 画像に変える。"""
    pattern = re.compile(
        r'<figure[^>]*>\s*'
        r'(?:<a\s+href="([^"]+)"[^>]*>\s*)?'
        r'<img\s+src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>\s*(?:</a>\s*)?'
        r'<figcaption>(.*?)(?:<span class="credit">(.*?)</span>)?</figcaption>\s*'
        r'(?:<span class="credit">(.*?)</span>\s*)?'
        r'</figure>',
        re.DOTALL,
    )

    def repl(m):
        href, src, alt, caption = m.group(1), m.group(2), m.group(3), m.group(4)
        credit = m.group(5) or m.group(6) or ""
        # note は画像にリンクを付けられないので、Amazon リンクはキャプションに添える
        if href and "amazon." in href:
            caption = re.sub(r"（クリックで[^）]*）", "", caption)
        if src.startswith("/"):
            src = SITE + src
        caption = re.sub(r"\s+", " ", caption).strip()
        credit = re.sub(r"\s+", " ", credit).strip()
        out = "![%s](%s)\n" % (alt, src)
        if caption:
            out += "\n*%s*\n" % caption
        if credit:
            out += "\n（出典: %s）\n" % credit
        if href and "amazon." in href:
            out += "\nAmazonで見る: %s\n" % href
        return out

    return pattern.sub(repl, body)


def convert_links(body):
    """Markdown / HTML のリンクを note が実際にリンク化できる形式に変える。

    note エディタはキー入力された `[ラベル](URL)` をリンクに変換しないため、
    「ラベル: URL」行にして post-to-note.py の paste_link() で HTML リンクとして貼る。
    （2026-11-28: 11/18以降の記事で Amazon リンクが文字のままになっていた不具合の修正）
    """
    parts = re.split(r"(```.*?```)", body, flags=re.DOTALL)
    for i, part in enumerate(parts):
        if i % 2:  # コードブロックはそのまま
            continue
        # 画像を包む <a> は画像を残し、リンクは別行に出す（note は画像にリンクを付けられない）
        def img_anchor(m):
            url, img = m.group(1), m.group(2)
            if "amazon." in url:
                return "%s\n\nAmazonで見る: %s" % (img, url)
            return "%s\n\nリンク: %s" % (img, url)

        part = re.sub(
            r'<a\s[^>]*href="([^"]+)"[^>]*>\s*(<img\s[^>]*>)\s*</a>',
            img_anchor, part, flags=re.DOTALL)

        # 通常の <a> は中身のテキストをラベルにする
        def anchor(m):
            label = re.sub(r"<[^>]+>", "", m.group(2))
            label = re.sub(r"\s+", " ", label).strip() or "リンク"
            return "%s: %s" % (label, m.group(1))

        part = re.sub(
            r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            anchor, part, flags=re.DOTALL)

        # <figure> で包まれていない単独の <img> もnote向けのMarkdown画像にする
        def bare_img(m):
            src, alt = m.group(1), m.group(2)
            if src.startswith("/"):
                src = SITE + src
            return "![%s](%s)" % (alt, src)

        part = re.sub(
            r'<img\s+src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>',
            bare_img, part)

        # ![alt](url) は画像のまま残し、それ以外の [ラベル](url) をリンク行にする
        part = re.sub(
            r'(?<!!)\[([^\]\n]+)\]\((https?://[^)\s]+)\)',
            r'\1: \2', part)
        parts[i] = part
    return "".join(parts)


def clean_html(body):
    """note で解釈されない HTML タグを整理する。"""
    # 未変換の figure ブロックを削除
    body = re.sub(r"<figure.*?</figure>", "", body, flags=re.DOTALL)
    # 残った credit _span を括弧書きに
    body = re.sub(
        r'<span class="credit">(.*?)</span>',
        lambda m: "（出典: %s）" % re.sub(r"\s+", " ", m.group(1)).strip(),
        body,
        flags=re.DOTALL,
    )
    # その他のタグを外す
    body = re.sub(r"</?(?:div|span|p|section|aside)[^>]*>", "", body)
    return body


def convert_tables(body):
    """note は表を表示できないので、Markdown の表を箇条書きにする。"""
    def cells(line):
        return [re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", c).strip()
                for c in line.strip().strip("|").split("|")]

    def repl(m):
        rows = [r for r in m.group(0).strip("\n").split("\n")]
        head = cells(rows[0])
        out = []
        for r in rows[2:]:
            c = cells(r)
            if len(c) == 2:
                out.append("- %s：%s" % (c[0], c[1]))
            else:
                out.append("- %s：%s" % (c[0], " / ".join(
                    "%s %s" % (h, v) for h, v in zip(head[1:], c[1:]))))
        return "\n".join(out) + "\n"

    return re.sub(r"(?m)^\|.*\|[ \t]*\n\|[ \t:|-]+\|[ \t]*\n(?:\|.*\|[ \t]*(?:\n|$))+",
                  repl, body)


def clean_body(body):
    body = convert_figures(body)
    body = convert_tables(body)
    body = clean_html(body)
    body = absolutize_links(body)   # 相対URLを絶対URLにしてからリンクを変換する
    body = convert_links(body)
    # 連続する空行を 1 行に
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def absolutize_links(body):
    """相対リンク (/posts/xxx/ 等) を絶対URLへ変換する。note.comでは必須。

    note.com の自動リンク化は ")" の直後に日本語が続くとそこまでをURLとして
    解釈し、GA4 に不正な pagePath として記録される。区切りを1つ入れて防ぐ。
    """
    body = re.sub(r"\]\(/", "](" + SITE + "/", body)
    body, count = re.subn(r"(\]\([^)\s]+\))(?=[^\x00-\x7F])", r"\1 ", body)
    if count:
        print(f"  note: リンク直後の日本語に区切りを追加 ({count}件)")
    return body


def remove_lead_duplicate(body, desc):
    """本文冒頭が description と重複する場合、重複分を落とす。

    画像の figure が先頭にあるため、本文の文章は必ず find で探す。
    desc 全体が本文に含まれていたら、その1回分だけを削除する。
    """
    if not desc:
        return body
    if desc in body:
        return body.replace(desc, "", 1)
    return body


def build_title(meta, slug):
    """note のタイトルはブログと同じにする（2026-10-01 のタイトル刷新以降）。"""
    return meta.get("title", slug)


def normalize_tag(tag):
    """note のハッシュタグは空白やアポストロフィを使えないため取り除く。"""
    tag = re.sub(r"[\s'\"()、。,.\-&]+", "", tag)
    return tag


def build_tags(meta):
    tags = meta.get("tags", [])
    cats = meta.get("categories", [])
    out = list(tags) + list(cats)
    seen = set()
    uniq = []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def main():
    if len(sys.argv) < 2:
        print("使い方: python convert-to-note.py <slug> [出力ファイル]")
        sys.exit(1)

    slug = sys.argv[1]
    src = os.path.join(POSTS, slug + ".md")
    if not os.path.exists(src):
        print("記事が見つかりません: %s" % src)
        sys.exit(1)

    with io.open(src, encoding="utf-8") as f:
        text = f.read()

    meta, body = parse_front_matter(text)
    paid = str(meta.get("note_paid", "")).strip().lower() in ("true", "yes", "1")
    paywall_from = meta.get("note_paid_from", "")
    price = meta.get("note_price", "")

    # 有料記事の GitHub Pages 版は「無料部分＋CTA」なので、note には退避した全文を使う。
    full_src = os.path.join(NOTE_FULL, slug + ".md")
    if paid and os.path.exists(full_src):
        src = full_src
        with io.open(src, encoding="utf-8") as f:
            text = f.read()
        full_meta, body = parse_front_matter(text)
        for k in ("title", "description", "tags", "categories"):
            if full_meta.get(k):
                meta[k] = full_meta[k]
    elif paid and "github" in dist.platforms(slug):
        # GitHub 版を持つ有料記事は note_sync apply で全文を退避しているはず。
        print("有料記事ですが全文の退避がありません: %s" % full_src)
        print("先に scripts/note_sync.py apply を実行するか、note-full に全文を置いてください。")
        sys.exit(1)
    # GitHub が配信先でない有料記事は content/posts の本文が正本なので note-full は不要。

    # CTA は note には不要。マーカーは公開後に note_sync.py apply で使う。
    body = CTA_RE.sub("", body)
    marker_at = body.find(PAYWALL_MARKER)
    if marker_at != -1:
        after = body[marker_at + len(PAYWALL_MARKER):]
        m = re.search(r"(?m)^##\s+(.+)$", after)
        if m and not paywall_from:
            paywall_from = m.group(1).strip()
        body = body.replace(PAYWALL_MARKER, "")
    body = clean_body(body)

    # front matter の description は本文冒頭の書き出しと重複することがある。
    # 同一の書き出しが続く場合は description 側の重複を本文から落とす。
    desc = meta.get("description", "")
    body = remove_lead_duplicate(body, desc)

    title = build_title(meta, slug)
    tags = build_tags(meta)
    # 新フローでは「元記事」は canonical_platform 次第。note 自身が正本ならリンクを出さない。
    canonical = dist.canonical_platform(slug)
    url = dist.canonical_url(slug)
    show_original = canonical != "note"

    lines = []
    lines.append("# タイトル")
    lines.append(title)
    lines.append("")
    lines.append("# タグ（1行にまとめて貼り付け）")
    lines.append(" ".join("#%s" % normalize_tag(t) for t in tags))
    lines.append("")
    if paid or paywall_from:
        lines.append("# 公開設定")
        lines.append("この記事は note の有料記事です。エディタで「%s」の直前に有料ラインを置き、価格を %s 円に設定してください。"
                     % (paywall_from or "(有料部分の先頭見出し)", price or "(note で設定)"))
        if "github" in dist.platforms(slug):
            lines.append("公開後に `python scripts/note_sync.py sync` と "
                         "`python scripts/note_sync.py apply --slug %s` を実行すると、"
                         "GitHub Pages が無料部分＋CTA に揃います。" % slug)
        lines.append("")
    lines.append("# 本文（ここから貼り付け）")
    lines.append("")
    # 冒頭の「オリジナル記事」は canonical_platform のURL（旧フローでは GitHub Pages）。
    if show_original:
        lines.append("オリジナル記事: %s" % url)
        lines.append("")
    if desc:
        lines.append(desc)
        lines.append("")
    lines.append(body)
    lines.append("")
    # コメント率改善（2026-11-28 の note レポート提案）。貼り付け用本文の末尾に入れる。
    lines.append("このテーマについて、あなたの経験や「ここが気になった」という点があれば"
                 "コメントで教えてください。次の記事を書くときの参考にします。")
    lines.append("")
    if show_original:
        lines.append("---")
        lines.append("")
        lines.append("元記事（ブログ）: %s" % url)

    result = "\n".join(lines)
    result = rewrite_for(result, "note")

    if len(sys.argv) >= 3:
        out = sys.argv[2]
        if not os.path.isabs(out):
            out = os.path.join(BASE, out)
    else:
        # 有料記事の下書きは全文を含むため、公開リポジトリに入れない paid/ に置く。
        sub = "paid" if (paid or paywall_from) else ""
        out = os.path.join(BASE, "scripts", "note-drafts", sub, slug + ".note.txt")
        os.makedirs(os.path.dirname(out), exist_ok=True)

    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(result)

    plain = re.sub(r"[#*`\[\]()!]", "", body)
    print("出力: %s" % out)
    print("タイトル: %s（%d 文字）" % (title, len(title)))
    print("タグ: %s" % " ".join("#%s" % normalize_tag(t) for t in tags))
    print("本文の文字数: 約 %d" % len(plain.replace("\n", "")))
    print("元記事URL: %s" % url)
    if paid or paywall_from:
        print("有料記事: note エディタで「%s」の直前に有料ラインを置いてください。"
              % (paywall_from or "(有料部分の先頭見出し)"))


if __name__ == "__main__":
    main()
