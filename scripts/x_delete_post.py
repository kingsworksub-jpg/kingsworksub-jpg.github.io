# -*- coding: utf-8 -*-
"""指定した自分の投稿だけをXのUIから削除する（2026-11-23の誤投稿対応）。

安全策:
- 共有ミューテックスを取得してからブラウザを開く（他のXジョブと衝突しない）
- data/x-consulting/auto-improve-state.json の履歴から status_id を引き、
  その本文の先頭が対象ツイートに含まれることを確認してから削除する
- --confirm を付けない限りはドライラン（何もクリックしない）

使い方:
  python scripts/x_delete_post.py --status-id 2124795538336100765
  python scripts/x_delete_post.py --status-id 2124795538336100765 --confirm
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
STATE_PATH = BASE / "data" / "x-consulting" / "auto-improve-state.json"
MUTEX_NAME = "Local\\kingsworksub-blog-x-jobs"


def _load_post_module():
    path = SCRIPTS / "post-to-x.py"
    spec = importlib.util.spec_from_file_location("post_to_x_delete", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def acquire_mutex(timeout_sec: float):
    if os.name != "nt":
        return True
    k32 = ctypes.windll.kernel32
    h = k32.CreateMutexW(None, False, MUTEX_NAME)
    if not h:
        return None
    r = k32.WaitForSingleObject(h, int(timeout_sec * 1000))
    if r in (0, 0x80):
        return h
    k32.CloseHandle(h)
    return None


def release_mutex(h) -> None:
    if os.name == "nt" and h:
        k32 = ctypes.windll.kernel32
        k32.ReleaseMutex(h)
        k32.CloseHandle(h)


def expected_text(status_id: str) -> str:
    try:
        obj = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    for e in reversed(obj.get("history") or []):
        if str(e.get("status_id")) == status_id:
            return str(e.get("post_text") or "")[:30]
    return ""


def find_article(page, status_id: str, needle: str):
    page.goto(f"https://x.com/i/status/{status_id}", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector('article[data-testid="tweet"]', timeout=30000)
    page.wait_for_timeout(1500)
    articles = page.query_selector_all('article[data-testid="tweet"]')
    for a in articles:
        try:
            hrefs = a.query_selector_all(f'a[href*="/status/{status_id}"]')
            if not hrefs:
                continue
            txt = a.inner_text() or ""
            if needle and needle[:15] not in txt:
                continue
            return a, txt
        except Exception:
            continue
    return None, ""


def _click_text(page, container, texts: list[str], tag: str) -> bool:
    for sel in ['[role="menuitem"]', 'button', '[role="button"]']:
        nodes = container.query_selector_all(sel) if container else page.query_selector_all(sel)
        for n in nodes:
            try:
                label = (n.inner_text() or "") + " " + (n.get_attribute("aria-label") or "")
            except Exception:
                continue
            if any(t in label for t in texts):
                try:
                    n.click(timeout=5000)
                    print(f"[+] {tag}: clicked ({label.strip()[:40]})")
                    return True
                except Exception as exc:
                    print(f"[!] {tag} click failed: {exc}")
        # fallback: page-level scan once per selector
        if container is not None:
            for n in page.query_selector_all(sel):
                try:
                    label = (n.inner_text() or "") + " " + (n.get_attribute("aria-label") or "")
                except Exception:
                    continue
                if any(t in label for t in texts):
                    try:
                        n.click(timeout=5000)
                        print(f"[+] {tag}: clicked ({label.strip()[:40]})")
                        return True
                    except Exception as exc:
                        print(f"[!] {tag} click failed: {exc}")
    return False


def delete_target(status_id: str, confirm: bool, lock_wait: float) -> dict[str, Any]:
    needle = expected_text(status_id)
    if not needle:
        return {"ok": False, "error": "status_id not found in auto-improve history; refusing to delete"}

    mutex = acquire_mutex(lock_wait)
    if not mutex:
        return {"ok": False, "error": "could not acquire X jobs mutex"}
    try:
        pt = _load_post_module()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = pt.open_browser(p)
            try:
                page = ctx.new_page()
                art, text = find_article(page, status_id, needle)
                if art is None:
                    return {"ok": False, "error": "target post not found or text mismatch", "needle": needle}
                print(f"[i] target article text head: {text[:80].replace(chr(10), ' ')}")

                if not confirm:
                    return {"ok": True, "dry_run": True, "target_verified": True, "status_id": status_id}

                more = None
                for sel in ['[data-testid="moreHorizontal"]', 'button[aria-label*="もっと"]',
                            'button[aria-label*="More"]', 'button[aria-label*="詳細"]']:
                    try:
                        cand = art.query_selector(sel)
                    except Exception:
                        cand = None
                    if cand:
                        more = cand
                        break
                if more is None:
                    return {"ok": False, "error": "more button not found"}
                more.click(timeout=8000)
                page.wait_for_timeout(800)

                if not _click_text(page, None, ["削除", "Delete"], "delete menu"):
                    return {"ok": False, "error": "delete menu item not found"}

                page.wait_for_timeout(1000)
                # Xの確認ダイアログは role=alertdialog / data-testid=confirmationSheetConfirm。
                confirm_btn = page.query_selector('[data-testid="confirmationSheetConfirm"]')
                dialog = None
                if confirm_btn is None:
                    for sel in ['[role="alertdialog"]', '[role="dialog"]', '[data-testid*="confirm"]']:
                        try:
                            dialog = page.query_selector(sel)
                        except Exception:
                            dialog = None
                        if dialog:
                            break
                    if dialog is not None:
                        confirm_btn = dialog.query_selector('[data-testid="confirmationSheetConfirm"]')
                if confirm_btn is not None:
                    try:
                        confirm_btn.click(timeout=8000)
                        print("[+] confirm dialog: clicked delete")
                    except Exception as exc:
                        return {"ok": False, "error": f"confirm click failed: {exc}"}
                elif dialog is not None:
                    if not _click_text(page, dialog, ["削除", "Delete"], "confirm dialog"):
                        return {"ok": False, "error": "confirm button not found"}
                else:
                    return {"ok": False, "error": "delete confirmation dialog not found (nothing clicked yet)"}

                page.wait_for_timeout(3000)
                # 新しいページで読み直して本当に消えたか確認する（DOMの古い要素を誤検出しない）。
                verify = ctx.new_page()
                try:
                    verify.goto(f"https://x.com/i/status/{status_id}", wait_until="domcontentloaded", timeout=45000)
                    verify.wait_for_timeout(3000)
                    left = verify.query_selector_all(f'article[data-testid="tweet"] a[href*="/status/{status_id}"]')
                finally:
                    verify.close()
                if left:
                    return {"ok": False, "error": "post still visible after delete attempt"}
                return {"ok": True, "deleted": True, "status_id": status_id}
            finally:
                ctx.close()
    finally:
        release_mutex(mutex)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status-id", required=True)
    ap.add_argument("--confirm", action="store_true", help="実際に削除する（未指定はドライラン）")
    ap.add_argument("--lock-wait-sec", type=float, default=300)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    res = delete_target(args.status_id, args.confirm, args.lock_wait_sec)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
