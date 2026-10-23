# -*- coding: utf-8 -*-
"""Update (PUT) an existing Hatena Blog entry via AtomPub, WSSE auth — pure Python.

Equivalent to update-hatena-post.sh, but avoids passing Japanese title text through
bash variable capture (which mangled multi-byte text on this machine's Windows console
codepage and produced a 400 XML Parse Failed from Hatena). Reads title/content from
files, never from a shell-expanded argument.

Usage:
    python hatena_update.py <entry_id> <title_file_or_literal> <content_html_file>

Requires env vars: HATENA_ID, HATENA_BLOG_DOMAIN, HATENA_API_KEY (source .secrets/hatena.env)
"""
import base64
import hashlib
import io
import os
import sys
import time
import urllib.request
import urllib.error
import uuid
import xml.sax.saxutils as saxutils


def wsse_header(username, api_key):
    nonce = uuid.uuid4().bytes
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    digest = hashlib.sha1(nonce + created.encode("utf-8") + api_key.encode("utf-8")).digest()
    nonce_b64 = base64.b64encode(nonce).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return (
        f'UsernameToken Username="{username}", PasswordDigest="{digest_b64}", '
        f'Nonce="{nonce_b64}", Created="{created}"'
    )


def update_entry(entry_id, title, content_html):
    hid = os.environ["HATENA_ID"]
    domain = os.environ["HATENA_BLOG_DOMAIN"]
    api_key = os.environ["HATENA_API_KEY"]

    url = f"https://blog.hatena.ne.jp/{hid}/{domain}/atom/entry/{entry_id}"
    escaped_title = saxutils.escape(title)
    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<entry xmlns="http://www.w3.org/2005/Atom" xmlns:app="http://www.w3.org/2007/app">\n'
        f"  <title>{escaped_title}</title>\n"
        f"  <author><name>{hid}</name></author>\n"
        f"  <content type=\"text/html\"><![CDATA[{content_html}]]></content>\n"
        f"  <updated>{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}</updated>\n"
        "  <app:control><app:draft>no</app:draft></app:control>\n"
        "</entry>\n"
    ).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("X-WSSE", wsse_header(hid, api_key))
    req.add_header("Content-Type", "application/atom+xml;type=entry")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main():
    if len(sys.argv) != 4:
        print("Usage: python hatena_update.py <entry_id> <title_file> <content_html_file>", file=sys.stderr)
        sys.exit(1)
    entry_id, title_file, content_file = sys.argv[1:4]
    with io.open(title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with io.open(content_file, encoding="utf-8") as f:
        content_html = f.read()
    status, resp = update_entry(entry_id, title, content_html)
    print(f"HTTP status: {status}")
    if status != 200:
        print(resp)
        sys.exit(1)


if __name__ == "__main__":
    main()
