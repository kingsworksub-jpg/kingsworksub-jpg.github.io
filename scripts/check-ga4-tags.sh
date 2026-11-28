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

# 先頭の1件はエイリアスのリダイレクト頁になり得るため、gtag を含む実記事を選ぶ。
POST_HTML=""
while IFS= read -r candidate; do
  if grep -Fq "googletagmanager.com/gtag/js?id=$MEASUREMENT_ID" "$candidate"; then
    POST_HTML="$candidate"
    break
  fi
done < <(find "$DIR/posts" -type f -name index.html 2>/dev/null | sort)
[ -n "$POST_HTML" ] && [ -f "$POST_HTML" ] || fail "gtag を含む記事HTMLが見つかりません ($DIR/posts)"

count=$(grep -Fo "googletagmanager.com/gtag/js?id=$MEASUREMENT_ID" "$HOME_HTML" | wc -l | tr -d ' ')
[ "$count" = "1" ] || fail "gtag.js の読込は1回であるべきです (実際: $count)"

for token in \
  "gtag('config', '$MEASUREMENT_ID'" \
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
  grep -Fq "$token" "$POST_HTML" || fail "記事HTMLに '$token' がありません: $POST_HTML"
done

echo "OK: GA4タグ検証通過 ($MEASUREMENT_ID / $POST_HTML)"
