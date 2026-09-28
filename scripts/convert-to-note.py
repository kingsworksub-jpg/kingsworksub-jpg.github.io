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

BASE = r"C:\Users\norio\my-github-blog"
POSTS = os.path.join(BASE, "content", "posts")
SITE = "https://kingsworksub-jpg.github.io"


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
        r'<img\s+src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>\s*'
        r'<figcaption>(.*?)<span class="credit">(.*?)</span></figcaption>\s*'
        r'</figure>',
        re.DOTALL,
    )

    def repl(m):
        src, alt, caption, credit = m.group(1), m.group(2), m.group(3), m.group(4)
        if src.startswith("/"):
            src = SITE + src
        caption = re.sub(r"\s+", " ", caption).strip()
        credit = re.sub(r"\s+", " ", credit).strip()
        out = "![%s](%s)\n" % (alt, src)
        if caption:
            out += "\n*%s*\n" % caption
        if credit:
            out += "\n（出典: %s）\n" % credit
        return out

    return pattern.sub(repl, body)


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


def clean_body(body):
    body = convert_figures(body)
    body = clean_html(body)
    body = absolutize_links(body)
    # 連続する空行を 1 行に
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def absolutize_links(body):
    """相対リンク (/posts/xxx/ 等) を絶対URLへ変換する。note.comでは必須。"""
    return re.sub(r"\]\(/", "](" + SITE + "/", body)


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
    """ブログ用タイトルから note 向けタイトルを作る（15〜25 文字目安）。"""
    tags = meta.get("tags", [])
    if "ハードバップ" in tags or "Blue Note" in tags:
        return "ハードバップとブルー・ノート黄金時代"
    if "クール・ジャズ" in tags:
        return "クール・ジャズの時代とChet Bakerの西海岸"
    if "ビバップ" in tags:
        return "ビバップの夜明け — Charlie Parker"
    # ブログ用タイトルは長すぎるので、 区切り文字で 30 文字に詰める
    title = meta.get("title", slug)
    for sep in [" — ", " - ", "：", ": "]:
        if sep in title:
            title = title.split(sep)[0]
            break
    return title[:30]


def normalize_tag(tag):
    """note のハッシュタグは空白やアポストロフィを使えないため取り除く。"""
    tag = re.sub(r"[\s'\"()、。,.\-]+", "", tag)
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
    body = clean_body(body)

    # front matter の description は本文冒頭の書き出しと重複することがある。
    # 同一の書き出しが続く場合は description 側の重複を本文から落とす。
    desc = meta.get("description", "")
    body = remove_lead_duplicate(body, desc)

    title = build_title(meta, slug)
    tags = build_tags(meta)
    url = "%s/posts/%s/" % (SITE, slug)

    lines = []
    lines.append("# タイトル")
    lines.append(title)
    lines.append("")
    lines.append("# タグ（1行にまとめて貼り付け）")
    lines.append(" ".join("#%s" % normalize_tag(t) for t in tags))
    lines.append("")
    lines.append("# 本文（ここから貼り付け）")
    lines.append("")
    if desc:
        lines.append(desc)
        lines.append("")
    lines.append(body)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("元記事（ブログ）: %s" % url)

    result = "\n".join(lines)

    if len(sys.argv) >= 3:
        out = sys.argv[2]
        if not os.path.isabs(out):
            out = os.path.join(BASE, out)
    else:
        out = os.path.join(BASE, "scripts", "note-drafts", slug + ".note.txt")
        os.makedirs(os.path.dirname(out), exist_ok=True)

    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(result)

    plain = re.sub(r"[#*`\[\]()!]", "", body)
    print("出力: %s" % out)
    print("タイトル: %s（%d 文字）" % (title, len(title)))
    print("タグ: %s" % " ".join("#%s" % normalize_tag(t) for t in tags))
    print("本文の文字数: 約 %d" % len(plain.replace("\n", "")))
    print("元記事URL: %s" % url)


if __name__ == "__main__":
    main()
