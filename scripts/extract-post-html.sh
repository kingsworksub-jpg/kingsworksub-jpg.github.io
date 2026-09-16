#!/usr/bin/env bash
# Extract a single post's rendered body HTML (for cross-posting to Hatena etc.)
# from a non-minified Hugo build. No attribution/canonical-link notice is
# prepended (removed 2026-09-17 per user instruction — do not re-add it).
#
# Usage:
#   scripts/extract-post-html.sh <slug> [output-file]
#
#   slug        - the post's directory name under content/posts/, e.g. daw-5choice-2026
#   output-file - defaults to /tmp/<slug>.html
set -euo pipefail

SLUG="${1:?Usage: extract-post-html.sh SLUG [OUTPUT_FILE]}"
OUT="${2:-/tmp/${SLUG}.html}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR=$(mktemp -d)
hugo --destination "$BUILD_DIR" >/dev/null

POST_HTML="$BUILD_DIR/posts/$SLUG/index.html"
if [ ! -f "$POST_HTML" ]; then
  echo "Not found: $POST_HTML (check the slug matches content/posts/$SLUG.md)" >&2
  rm -rf "$BUILD_DIR"
  exit 1
fi

SITE_ORIGIN="https://kingsworksub-jpg.github.io"

# Extract everything between the post-content div and its matching </div>.
# Safe because our posts are plain Markdown with no nested raw <div> tags.
# Also rewrite root-relative src/href (e.g. the radar chart images) to
# absolute URLs, since on Hatena's domain a relative "/images/..." would
# 404 instead of pointing back at this site.
awk '
  /<div class="post-content md-content">/ { grabbing=1; next }
  grabbing && /<\/div>/ { grabbing=0; next }
  grabbing { print }
' "$POST_HTML" \
  | sed -E "s@(src|href)=\"/([^\"#])@\1=\"${SITE_ORIGIN}/\2@g" \
  > "$OUT"

rm -rf "$BUILD_DIR"

echo "Extracted to: $OUT"
