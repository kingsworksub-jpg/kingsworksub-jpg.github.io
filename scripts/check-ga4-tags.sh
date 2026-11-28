#!/usr/bin/env bash
# ビルド済みHTMLにGA4タグと主要イベントが入っていることを検証する。
# 使い方: bash scripts/check-ga4-tags.sh [public]
set -euo pipefail

DIR="${1:-public}"
HOME_HTML="$DIR/index.html"
MEASUREMENT_ID="G-ZL0DCF6JXB"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[ -f "$HOME_HTML" ] || fail "$HOME_HTML がありません"

# 先頭の1件はリダイレクト頁や古いビルドの残骸になり得るため、
# gtag.js と config を持つ実記事を1件見つける（検証自体はビルド全体に対して行う）。
POST_HTML=""
while IFS= read -r candidate; do
  if grep -Fq "googletagmanager.com/gtag/js?id=$MEASUREMENT_ID" "$candidate" \
     && grep -Eq "gtag\(['\"]config['\"],[[:space:]]*['\"]$MEASUREMENT_ID['\"]" "$candidate"; then
    POST_HTML="$candidate"
    break
  fi
done < <(find "$DIR/posts" -type f -name index.html 2>/dev/null | sort)
[ -n "$POST_HTML" ] && [ -f "$POST_HTML" ] || fail "gtag config を持つ記事HTMLが見つかりません ($DIR/posts)"

count=$(grep -Fo "googletagmanager.com/gtag/js?id=$MEASUREMENT_ID" "$HOME_HTML" | wc -l | tr -d ' ')
[ "$count" = "1" ] || fail "gtag.js の読込は1回であるべきです (実際: $count)"

# Hugo の minify でクォートや空白が変わるため、形式に依存せず config を確認する。
grep -Eq "gtag\(['\"]config['\"],[[:space:]]*['\"]$MEASUREMENT_ID['\"]" "$POST_HTML" \
  || fail "記事HTMLに gtag config ($MEASUREMENT_ID) がありません: $POST_HTML"

# イベント名は挿入されるページがビルドごとに変わり得るため、ビルド全体で確認する。
for token in \
  "affiliate_click" \
  "internal_link_click" \
  "site_search" \
  "article_progress" \
  "article_read" \
  "outbound_click" \
  "article_group" \
  "ascsubtag" \
  "countapi"
do
  grep -rFq --include='*.html' "$token" "$DIR" || fail "ビルド済みHTMLに '$token' がありません: $DIR"
done

echo "OK: GA4タグ検証通過 ($MEASUREMENT_ID / $POST_HTML)"
