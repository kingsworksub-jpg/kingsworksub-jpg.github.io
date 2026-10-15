#!/usr/bin/env bash
# Delete an existing Hatena Blog entry via AtomPub, WSSE auth. Confirms deletion with a
# follow-up GET (expects 404) before reporting success — a 200/204 from the DELETE alone
# is not treated as proof the entry is actually gone.
#
# Requires env vars: HATENA_ID, HATENA_BLOG_DOMAIN, HATENA_API_KEY
#
# Usage:
#   scripts/delete-hatena-post.sh ENTRY_ID
#
#   ENTRY_ID    - the numeric entry id (from the edit URL
#                 .../atom/entry/<ENTRY_ID>)
set -euo pipefail

: "${HATENA_ID:?Set HATENA_ID (source .secrets/hatena.env)}"
: "${HATENA_BLOG_DOMAIN:?Set HATENA_BLOG_DOMAIN}"
: "${HATENA_API_KEY:?Set HATENA_API_KEY}"

ENTRY_ID="${1:?Usage: delete-hatena-post.sh ENTRY_ID}"

EDIT_URL="https://blog.hatena.ne.jp/${HATENA_ID}/${HATENA_BLOG_DOMAIN}/atom/entry/${ENTRY_ID}"

wsse_header() {
  local nonce_file digest nonce_b64 created
  nonce_file=$(mktemp)
  openssl rand 16 > "$nonce_file"
  nonce_b64=$(openssl base64 -A -in "$nonce_file")
  created=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  digest=$(cat "$nonce_file" <(printf '%s%s' "$created" "$HATENA_API_KEY") | openssl dgst -sha1 -binary | openssl base64 -A)
  rm -f "$nonce_file"
  printf 'UsernameToken Username="%s", PasswordDigest="%s", Nonce="%s", Created="%s"' \
    "$HATENA_ID" "$digest" "$nonce_b64" "$created"
}

DELETE_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$EDIT_URL" \
  -H "X-WSSE: $(wsse_header)")

echo "DELETE status: $DELETE_CODE"
if [ "$DELETE_CODE" != "200" ] && [ "$DELETE_CODE" != "204" ]; then
  echo "Delete failed (expected 200 or 204)." >&2
  exit 1
fi

# WSSE nonces are single-use; build a fresh header for the confirmation GET.
CONFIRM_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$EDIT_URL" \
  -H "X-WSSE: $(wsse_header)")

echo "Confirmation GET status: $CONFIRM_CODE"
if [ "$CONFIRM_CODE" != "404" ]; then
  echo "DELETE returned $DELETE_CODE but the entry is still fetchable (GET returned $CONFIRM_CODE, expected 404)." >&2
  echo "Do NOT treat this as a successful delete." >&2
  exit 1
fi

echo "Deleted and confirmed gone: entry $ENTRY_ID"
