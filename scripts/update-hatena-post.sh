#!/usr/bin/env bash
# Update (PUT) an existing Hatena Blog entry via AtomPub, WSSE auth.
# Useful for re-syncing content, and for testing integrations (e.g. an
# X/Twitter auto-share on publish/update) that trigger off a re-post.
#
# Requires env vars: HATENA_ID, HATENA_BLOG_DOMAIN, HATENA_API_KEY
#
# Usage:
#   scripts/update-hatena-post.sh ENTRY_ID "Title" content.html
#
#   ENTRY_ID    - the numeric entry id (from the edit URL
#                 .../atom/entry/<ENTRY_ID>)
set -euo pipefail

: "${HATENA_ID:?Set HATENA_ID (source .secrets/hatena.env)}"
: "${HATENA_BLOG_DOMAIN:?Set HATENA_BLOG_DOMAIN}"
: "${HATENA_API_KEY:?Set HATENA_API_KEY}"

ENTRY_ID="${1:?Usage: update-hatena-post.sh ENTRY_ID TITLE CONTENT_HTML_FILE}"
TITLE="${2:?Usage: update-hatena-post.sh ENTRY_ID TITLE CONTENT_HTML_FILE}"
CONTENT_FILE="${3:?Usage: update-hatena-post.sh ENTRY_ID TITLE CONTENT_HTML_FILE}"

EDIT_URL="https://blog.hatena.ne.jp/${HATENA_ID}/${HATENA_BLOG_DOMAIN}/atom/entry/${ENTRY_ID}"

NONCE_RAW_FILE=$(mktemp)
openssl rand 16 > "$NONCE_RAW_FILE"
NONCE_B64=$(openssl base64 -A -in "$NONCE_RAW_FILE")
CREATED=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DIGEST=$(cat "$NONCE_RAW_FILE" <(printf '%s%s' "$CREATED" "$HATENA_API_KEY") | openssl dgst -sha1 -binary | openssl base64 -A)
rm -f "$NONCE_RAW_FILE"
WSSE="UsernameToken Username=\"${HATENA_ID}\", PasswordDigest=\"${DIGEST}\", Nonce=\"${NONCE_B64}\", Created=\"${CREATED}\""

ESCAPED_TITLE=$(printf '%s' "$TITLE" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g')

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
  printf '  <app:control><app:draft>no</app:draft></app:control>\n'
  printf '</entry>\n'
} > "$XML_FILE"

HTTP_CODE=$(curl -s -o /tmp/hatena-update-response.xml -w "%{http_code}" -X PUT "$EDIT_URL" \
  -H "X-WSSE: $WSSE" \
  -H "Content-Type: application/atom+xml;type=entry" \
  --data-binary "@$XML_FILE")

rm -f "$XML_FILE"

echo "HTTP status: $HTTP_CODE"
cat /tmp/hatena-update-response.xml
echo ""

if [ "$HTTP_CODE" != "200" ]; then
  echo "Update failed (expected 200 OK)." >&2
  exit 1
fi

echo "Updated successfully."
