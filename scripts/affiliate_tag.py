# -*- coding: utf-8 -*-
"""Amazonアフィリエイトリンクの tag= パラメータを、配信先プラットフォーム別の
トラッキングIDに一括で書き換える共通ヘルパー。

各プラットフォームのトラッキングID(2026-10-23、ユーザー指示・Amazonアソシエイト管理画面で作成済み):
  - GitHub Pages: nakimoto1-22 (既定。content/posts/*.md のソースはこのタグのまま変更しない)
  - はてなブログ: hatena-img-sub-22
  - note:         note-img-sub-22
  - Ameba:        ameba-img-sub-22

amazon.co.jp への URL に含まれる tag= の値だけを対象に書き換える(他ドメインの
クエリパラメータに誤爆しないよう、amazon.co.jp を含むURL文字列に限定してマッチする)。
tag= が無い amazon.co.jp リンクには新たに &tag=... または ?tag=... を追加する。

使い方(パイプ):
    python affiliate_tag.py hatena-img-sub-22 < in.html > out.html

使い方(関数):
    from affiliate_tag import rewrite_tag
    new_html = rewrite_tag(html, "hatena-img-sub-22")
"""
from __future__ import annotations

import re
import sys

TAGS = {
    "github": "nakimoto1-22",
    "hatena": "hatena-img-sub-22",
    "note": "note-img-sub-22",
    "ameba": "ameba-img-sub-22",
}

# amazon.co.jp を含む URL 全体にマッチ(href="..."・Markdown リンクの (...)・生URLのいずれでも
# 使える汎用の "URLらしき文字列" 一致。空白・ダブルクオート・シングルクオート・閉じ括弧・
# Markdownの閉じ括弧 ) で区切る)。
_URL_RE = re.compile(r'https?://(?:www\.)?amazon\.co\.jp/[^\s"\'<>)]+')
_TAG_PARAM_RE = re.compile(r'(?:^|[?&])tag=[^&]*')


def _rewrite_url(url: str, tag: str) -> str:
    if _TAG_PARAM_RE.search(url):
        return re.sub(r'tag=[^&]*', f'tag={tag}', url)
    sep = '&' if '?' in url else '?'
    return f'{url}{sep}tag={tag}'


def rewrite_tag(text: str, tag: str) -> str:
    """text 中の amazon.co.jp リンクすべての tag= を指定の値に書き換える(冪等)。"""
    return _URL_RE.sub(lambda m: _rewrite_url(m.group(0), tag), text)


def rewrite_for(text: str, platform: str) -> str:
    """platform ("github"/"hatena"/"note"/"ameba") 向けの既定タグで書き換える。"""
    return rewrite_tag(text, TAGS[platform])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python affiliate_tag.py <tag-or-platform> [< in.html > out.html]", file=sys.stderr)
        sys.exit(1)
    arg = sys.argv[1]
    tag = TAGS.get(arg, arg)
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(rewrite_tag(sys.stdin.read(), tag))
