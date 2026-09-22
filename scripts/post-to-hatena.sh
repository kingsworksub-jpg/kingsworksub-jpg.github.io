#!/usr/bin/env bash
# Post (or draft) an entry to Hatena Blog via the AtomPub API, using WSSE auth.
#
# Requires env vars: HATENA_ID, HATENA_BLOG_DOMAIN, HATENA_API_KEY
# (see .secrets/hatena.env — `source .secrets/hatena.env` before running this)
#
# Usage:
#   scripts/post-to-hatena.sh "Title" content.html [draft]
#
#   Title       - entry title (plain text)
#   content.html - path to a file containing the HTML body to post
#   draft       - pass the literal word "draft" to post as a draft (not publicly visible)
#                 omit (or pass "publish") to publish immediately
set -euo pipefail

: "${HATENA_ID:?Set HATENA_ID (source .secrets/hatena.env)}"
: "${HATENA_BLOG_DOMAIN:?Set HATENA_BLOG_DOMAIN}"
: "${HATENA_API_KEY:?Set HATENA_API_KEY}"

TITLE="${1:?Usage: post-to-hatena.sh TITLE CONTENT_HTML_FILE [draft]}"
CONTENT_FILE="${2:?Usage: post-to-hatena.sh TITLE CONTENT_HTML_FILE [draft]}"
MODE="${3:-publish}"

ENDPOINT="https://blog.hatena.ne.jp/${HATENA_ID}/${HATENA_BLOG_DOMAIN}/atom/entry"

# --- WSSE auth (UsernameToken over the AtomPub API key) ---
NONCE_RAW_FILE=$(mktemp)
openssl rand 16 > "$NONCE_RAW_FILE"
NONCE_B64=$(openssl base64 -A -in "$NONCE_RAW_FILE")
CREATED=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DIGEST=$(cat "$NONCE_RAW_FILE" <(printf '%s%s' "$CREATED" "$HATENA_API_KEY") | openssl dgst -sha1 -binary | openssl base64 -A)
rm -f "$NONCE_RAW_FILE"

WSSE="UsernameToken Username=\"${HATENA_ID}\", PasswordDigest=\"${DIGEST}\", Nonce=\"${NONCE_B64}\", Created=\"${CREATED}\""

# --- escape title for XML (content goes in CDATA, so only title needs escaping) ---
ESCAPED_TITLE=$(printf '%s' "$TITLE" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g')

# Hatena's AtomPub app:draft element uses "yes"/"no", not "true"/"false"
DRAFT_FLAG="no"
if [ "$MODE" = "draft" ]; then DRAFT_FLAG="yes"; fi

XML_FILE=$(mktemp)
{
  printf '<?xml version="1.0" encoding="utf-8"?>\n'
  printf '<entry xmlns="http://www.w3.org/2005/Atom" xmlns:app="http://www.w3.org/2007/app">\n'
  printf '  <title>%s</title>\n' "$ESCAPED_TITLE"
  printf '  <author><name>%s</name></author>\n' "$HATENA_ID"
  printf '  <content type="text/html"><![CDATA['
  cat "$CONTENT_FILE"
  printf ']]></content>\n'
  printf '  <updated>%s</updated>\n' "$CREATED"
  printf '  <app:control><app:draft>%s</app:draft></app:control>\n' "$DRAFT_FLAG"
  printf '</entry>\n'
} > "$XML_FILE"

HTTP_CODE=$(curl -s -o /tmp/hatena-response.xml -w "%{http_code}" -X POST "$ENDPOINT" \
  -H "X-WSSE: $WSSE" \
  -H "Content-Type: application/atom+xml;type=entry" \
  --data-binary "@$XML_FILE")

rm -f "$XML_FILE"

echo "HTTP status: $HTTP_CODE"
cat /tmp/hatena-response.xml
echo ""

if [ "$HTTP_CODE" != "201" ]; then
  echo "Post failed (expected 201 Created)." >&2
  exit 1
fi

# Safety check: confirm the draft state actually matches what we asked for,
# so a bad request never silently goes live (bit us once already).
ACTUAL_DRAFT=$(grep -o '<app:draft>[a-z]*</app:draft>' /tmp/hatena-response.xml | sed 's/<[^>]*>//g')
if [ "$ACTUAL_DRAFT" != "$DRAFT_FLAG" ]; then
  EDIT_URL=$(grep -o 'rel="edit" href="[^"]*"' /tmp/hatena-response.xml | sed 's/.*href="//;s/"$//')
  echo "WARNING: requested draft=$DRAFT_FLAG but Hatena reports draft=$ACTUAL_DRAFT." >&2
  echo "Edit URL: $EDIT_URL" >&2
  exit 1
fi

echo "Posted successfully (mode: $MODE, confirmed draft=$ACTUAL_DRAFT)."
