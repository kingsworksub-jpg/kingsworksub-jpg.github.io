"""Shared AtomPub helpers for the Hatena Blog integration (WSSE auth, entry list, delete).

Used by fix-hatena-banners.py and platform_sync.py. post-to-hatena.sh / update-hatena-post.sh
remain separate bash scripts (they only need POST/PUT, not the entry-listing/delete helpers here).
"""

from __future__ import annotations

import base64
import hashlib
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ATOM = "{http://www.w3.org/2005/Atom}"
ENV_FILE = Path(__file__).parent.parent / ".secrets" / "hatena.env"


def load_env() -> dict:
    env = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip().removeprefix("export ").strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def wsse(user: str, key: str) -> str:
    nonce = os.urandom(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + key.encode()).digest()).decode()
    return (f'UsernameToken Username="{user}", PasswordDigest="{digest}", '
            f'Nonce="{base64.b64encode(nonce).decode()}", Created="{created}"')


def request(url: str, user: str, key: str, method: str = "GET", body: bytes | None = None):
    """Raw AtomPub request. Returns (status, body_bytes). Raises urllib.error.HTTPError on 4xx/5xx
    (the caller can read .code / .read() on the exception for the response body)."""
    req = urllib.request.Request(url, data=body, method=method, headers={
        "X-WSSE": wsse(user, key), "Content-Type": "application/atom+xml;type=entry"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


def list_entries(base: str, user: str, key: str):
    url = base
    while url:
        _, data = request(url, user, key)
        root = ET.fromstring(data)
        for e in root.findall(f"{ATOM}entry"):
            edit = next((l.get("href") for l in e.findall(f"{ATOM}link") if l.get("rel") == "edit"), None)
            alt = next((l.get("href") for l in e.findall(f"{ATOM}link") if l.get("rel") == "alternate"), "")
            content = e.find(f"{ATOM}content")
            draft = e.find("{http://www.w3.org/2007/app}control/{http://www.w3.org/2007/app}draft")
            yield {
                "edit": edit, "url": alt, "title": e.findtext(f"{ATOM}title") or "",
                "type": content.get("type") if content is not None else "",
                "html": (content.text or "") if content is not None else "",
                "draft": draft is not None and draft.text == "yes",
            }
        url = next((l.get("href") for l in root.findall(f"{ATOM}link") if l.get("rel") == "next"), None)


def entry_edit_url(user: str, domain: str, entry_id: str) -> str:
    return f"https://blog.hatena.ne.jp/{user}/{domain}/atom/entry/{entry_id}"


def get_entry(user: str, domain: str, key: str, entry_id: str) -> dict | None:
    """Fetch one entry by id. Returns None on 404 (already gone), raises on other errors."""
    url = entry_edit_url(user, domain, entry_id)
    try:
        _, data = request(url, user, key)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    root = ET.fromstring(data)
    return {"title": root.findtext(f"{ATOM}title") or "", "url": url}


def delete_entry(user: str, domain: str, key: str, entry_id: str) -> None:
    """DELETE an entry, then confirm it's gone (expects a subsequent GET to 404).
    Raises on any unexpected response — callers must not treat a non-raising return
    as success unless the follow-up GET actually returned None."""
    url = entry_edit_url(user, domain, entry_id)
    status, _ = request(url, user, key, method="DELETE")
    if status not in (200, 204):
        raise RuntimeError(f"Hatena DELETE {entry_id} returned unexpected status {status}")
    still_there = get_entry(user, domain, key, entry_id)
    if still_there is not None:
        raise RuntimeError(f"Hatena DELETE {entry_id} returned {status} but entry is still fetchable afterwards")
