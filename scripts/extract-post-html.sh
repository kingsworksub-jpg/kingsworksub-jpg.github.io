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

# Hatena does not load this site's CSS, so hatena_banner.py inlines the .product-banner
# sizing (120x120 thumbnail, 468x120 banner). Without it the banner image renders at full size.
# hatena_figures.py likewise inlines the photo--left/right float so photos wrap text there.
# Prefer the project venv. If it is missing, fall back to a real interpreter: on this
# machine a bare `python` can resolve to the Windows Store stub
# (WindowsApps/python.exe), which is a 0-byte launcher that exits doing nothing.
PY="$REPO_ROOT/scripts/.venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then
  PY=""
  for cand in python3 python; do
    cand_path="$(command -v "$cand" 2>/dev/null || true)"
    [ -n "$cand_path" ] || continue
    case "$cand_path" in
      *WindowsApps*) continue ;;
    esac
    PY="$cand_path"
    break
  done
  if [ -z "$PY" ]; then
    echo "No usable Python interpreter found (venv missing and python is the Store stub)." >&2
    echo "Recreate it: python -m venv \"$REPO_ROOT/scripts/.venv\"" >&2
    exit 1
  fi
  echo "warning: project venv missing, falling back to $PY" >&2
fi

# Extract everything between the post-content div and its matching </div>,
# tracking nesting depth so nested raw <div> blocks (e.g. the per-product
# affiliate-link divs) don't trip a premature stop at their own closing tag.
# Also rewrite root-relative src/href (e.g. the radar chart images) to
# absolute URLs, since on Hatena's domain a relative "/images/..." would
# 404 instead of pointing back at this site.
awk -v start_marker='<div class="post-content md-content">' '
  BEGIN { depth = 0; started = 0 }
  {
    line = $0
    if (!started) {
      idx = index(line, start_marker)
      if (idx == 0) next
      line = substr(line, idx + length(start_marker))
      started = 1
      depth = 1
    }
    out = ""
    while (length(line) > 0) {
      open_idx = index(line, "<div")
      close_idx = index(line, "</div>")
      if (open_idx == 0 && close_idx == 0) {
        out = out line
        line = ""
        break
      }
      if (close_idx > 0 && (open_idx == 0 || close_idx < open_idx)) {
        out = out substr(line, 1, close_idx - 1)
        depth--
        line = substr(line, close_idx + 6)
        if (depth == 0) { line = ""; break }
        out = out "</div>"
      } else {
        out = out substr(line, 1, open_idx + 3)
        depth++
        line = substr(line, open_idx + 4)
      }
    }
    print out
    if (depth == 0) exit
  }
' "$POST_HTML" \
  | sed -E "s@(src|href)=\"/([^\"#])@\1=\"${SITE_ORIGIN}/\2@g" \
  | "$PY" "$REPO_ROOT/scripts/hatena_banner.py" \
  | "$PY" "$REPO_ROOT/scripts/hatena_figures.py" \
  > "$OUT"

rm -rf "$BUILD_DIR"

echo "Extracted to: $OUT"
