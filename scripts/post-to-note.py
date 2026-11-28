# -*- coding: utf-8 -*-
"""note.com への投稿を Playwright でsemi自動化する。

なぜブラウザか:
  note.com には投稿用の公開 API が存在しない（はてなブログは AtomPub がある）。
  そのため Chromium の永続プロファイルにログイン状態を保存し、
  エディタへの入力だけ自动化する。公開も `--publish` で自動化するのが既定運用
  （2026-09-29 ユーザー指示）。保存だけ止める場合は `--save`。

エディタの仕様（2026-09 実測 + 公開事例）:
  - タイトルは通常の input。fill() が効く。
  - 本文は [contenteditable="true"]。fill() は効かないのでキー入力か insertText を使う。
  - note のエディタは Markdown ショートカットをリアルタイムで解釈する
    （"## " → 見出し、"**x**" → 太字、"#tag" → タグチップ）。
  - 画像は markdown の ![](url) を理解しない。アップロード/貼り付けで挿入する必要がある。
  - class 名はビルドごとに変わるため、文字列ベースのセレクタだけを使う。

使い方:
  # 1回だけ。ブラウザが開くので手動でログインして端末に Enter を押す
  python scripts/post-to-note.py --login

  # 下書きを投稿画面に入力して止まる（推奨）
  python scripts/post-to-note.py --slug bebop-52nd-street-nights

  # 公開ボタンまで自動で押す
  python scripts/post-to-note.py --slug bebop-52nd-street-nights --publish

オプション:
  --slug <slug>   対象記事のスラッグ（省略時は note-drafts/ の一覧を表示）
  --all           note-drafts/ にある全ファイルを順番に処理
  --login         ログイン状態の初期化/更新だけを行う
  --publish       入力後に「公開する」まで自動で押す（既定は押さない）
  --no-images     画像を挿入せずテキストのみ（貼り付けが失敗したとき用）
  --fast          insertText で一括入力（高速。ただし Markdown 変換が効かない場合あり）
  --profile <dir> Chromium プロファイルの場所（既定 data/note_user_data）
  --delete-key <key> --expect-title "<タイトル>"  自分の記事一覧から削除(published/draft両対応)
  --edit-key <key> --slug <slug>   既存記事を最新draftで上書き(新規下書きを作らない)
  --allow-duplicate  同名の公開済み記事があっても明示的に新規作成する
"""
import argparse
import base64
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = r"C:\Users\norio\my-github-blog"
DRAFTS = os.path.join(BASE, "scripts", "note-drafts")
PROFILE = os.path.join(BASE, "data", "note_user_data")
NEW_NOTE_URL = "https://note.com/new"
EDITOR_URL = "https://editor.note.com/new"  # 実際の編集画面（note.com/new からリダイレクトされる）
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)
# bot 判定回避。headless のままだと本文が空で取得できないことがある。
INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['ja', 'ja-JP', 'en']});
"""

IMG_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<url>https://[^)\s]+)\)\s*$")


# ---------------------------------------------------------------- draft parse


def parse_draft(path):
    """note ドラフトを title / tags / body に分解する。"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")

    title, tags, body = "", "", []
    mode = None
    for ln in lines:
        s = ln.rstrip()
        if s.startswith("# タイトル"):
            mode = "title"
            continue
        if s.startswith("# タグ"):
            mode = "tags"
            continue
        if s.startswith("# 本文"):
            mode = "body"
            continue
        if mode == "title":
            if s.strip() and not title:
                title = s.strip()
                mode = None
        elif mode == "tags":
            if s.strip():
                tags = s.strip()
                mode = None
        elif mode == "body":
            body.append(ln)
    return title, tags, "\n".join(body).strip("\n")


def split_blocks(body):
    """空行区切りのブロックに分ける。マークダウン記号で始まる行を先に処理するため。"""
    return [b for b in re.split(r"\n{2,}", body) if b.strip()]


LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")


def block_lines(block):
    """1ブロックを「note に入力する単位」に分割する。

    note の ProseMirror では Enter 1回だと同じ <p> 内に <br> が入るため、
    連続行を正しい要素にするため行ごとに分ける。
    """
    lines = [ln for ln in block.split("\n") if ln.strip()]
    return lines or [block]


def exit_image_caption(page):
    """画像貼付後にカーソルを <figcaption> から通常段落へ逃がす。

    note の <figcaption> は text-align:center が既定で、ここに本文が続くと
    その部分だけ中央寄せになる（2026-09-28 実測）。

    脱出し方として «Escape → Enter 2回» が唯一有効（ArrowDown は効かない）。
    ただし Enter 2回で図版直下に空 <p> が残るため、直後に Backspace で潰す。
    実測で「画像直後の空段落がゼロ」になるシーケンスは
    «Escape → Enter 2回 → Backspace» のみ（2026-09-28 実測）。
    """
    cap = page.locator('.ProseMirror figcaption').last
    try:
        cap.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(250)
        cap.click()
        page.wait_for_timeout(450)
    except Exception as e:  # noqa: BLE001
        print(f"    [warn] figcaption のクリック失敗: {e}")
        return False

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    for _ in range(2):
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
    page.keyboard.press("Backspace")   # 図版直下の空 <p> を潰す
    page.wait_for_timeout(300)

    escaped = page.evaluate("""() => {
        const s = window.getSelection();
        if (!s || !s.anchorNode) return false;
        const el = s.anchorNode.nodeType === 3 ? s.anchorNode.parentElement : s.anchorNode;
        return !el.closest('figcaption');
    }""")
    print(f"    figcaption 脱出: {'OK' if escaped else 'NG'}", flush=True)
    return escaped


def set_text_align(page, mode="指定なし", max_retry=3):
    """本文の段落を左寄せに確定させる。

    note の仕様（2026-09-28 実測）:
      - 選択肢は「指定なし」「中央寄せ」「右寄せ」のみ
      - 「指定なし」= 左寄せ（text-align: start / left）
      - バブルメニューは «単一ブロック内の選択» にしか出ない。Ctrl+A や
        複数ブロックをまたぐ Shift+クリックでは出ない（画像の有無を問わない）
      - そのため「中央/右になっている要素」だけを 1 ブロックずつ
        三クリックして指定なしを適用する（通常時は 0 回で終わる）
      - 通常時は何も変更しないので、意図しない中央/右寄せは発生しない
    """
    BAD = ("center", "right", "end")

    def bad_blocks():
        return page.evaluate("""(BAD) => {
            const sels = ['p','h1','h2','h3','h4','h5','h6','li','blockquote','figcaption'];
            const out = [];
            let idx = 0;
            for (const s of sels) {
                for (const e of document.querySelectorAll('.ProseMirror '+s)) {
                    const t = (e.innerText||'').replace(/\\s+/g,' ').trim();
                    if (!t) continue;
                    const a = getComputedStyle(e).textAlign;
                    if (BAD.includes(a)) out.push({i: idx++, tag: s, align: a, text: t.slice(0,30)});
                }
            }
            return out;
        }""", BAD)

    def apply_to(nth_text_block):
        """n 番目の「テキストのあるブロック」を三クリックして指定なし。"""
        loc = page.locator(
            '.ProseMirror p, .ProseMirror h1, .ProseMirror h2, .ProseMirror h3, '
            '.ProseMirror h4, .ProseMirror h5, .ProseMirror h6, '
            '.ProseMirror li, .ProseMirror blockquote, .ProseMirror figcaption')
        for _ in range(max_retry):
            for _ in range(3):
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
            try:
                b = loc.nth(nth_text_block)
                b.scroll_into_view_if_needed(timeout=6000)
                page.wait_for_timeout(250)
                b.click(click_count=3, timeout=6000)
                page.wait_for_timeout(450)
            except Exception:  # noqa: BLE001
                return False
            btn = page.locator('button[aria-label="文章の配置"]').first
            try:
                if not btn.is_visible(timeout=3000):
                    continue
                btn.click(force=True)
                page.wait_for_timeout(1000)
            except Exception:  # noqa: BLE001
                continue
            opt = page.get_by_role("button", name=mode, exact=True)
            n = opt.count()
            if n == 0:
                page.keyboard.press("Escape")
                continue
            try:
                opt.nth(n - 1).click(timeout=8000)   # 手前のもの
                page.wait_for_timeout(1100)
            except Exception:  # noqa: BLE001
                page.keyboard.press("Escape")
                continue
            now = page.evaluate("""(i) => {
                const sels = ['p','h1','h2','h3','h4','h5','h6','li','blockquote','figcaption'];
                const all = [];
                for (const s of sels) {
                    for (const e of document.querySelectorAll('.ProseMirror '+s)) {
                        if ((e.innerText||'').trim()) all.push(e);
                    }
                }
                const e = all[i];
                return e ? getComputedStyle(e).textAlign : null;
            }""", nth_text_block)
            if now in (None, "start", "left"):
                return True
        return False

    total_bad = len(bad_blocks())
    print(f"    中央/右寄せの要素: {total_bad} 個", flush=True)
    fixed = 0
    for i in range(max_retry):
        bad = bad_blocks()
        if not bad:
            break
        for rec in bad:
            if apply_to(rec["i"]):
                fixed += 1
                print(f"      修正: <{rec['tag']}> {rec['align']} → left  {rec['text']!r}", flush=True)
            else:
                print(f"      [NG] 修正失敗: <{rec['tag']}> {rec['text']!r}", flush=True)
    print(f"    修正 {fixed} / {total_bad} 個", flush=True)

    res = page.evaluate("""() => {
        const sels = ['p','h1','h2','h3','h4','h5','h6','li','blockquote','figcaption'];
        const computed = {};
        for (const s of sels) for (const e of document.querySelectorAll('.ProseMirror '+s)) {
            if (!(e.innerText||'').trim()) continue;
            const a = getComputedStyle(e).textAlign;
            computed[a] = (computed[a] || 0) + 1;
        }
        return computed;
    }""")
    print(f"    最終 text-align 内訳: {res}", flush=True)
    return res


def validate_body(page, max_caption=60):
    """入力後の本文を検証する。見つけた問題を警告として返す。

    特に重要なのは figcaption。note の <figcaption> は text-align:center が
    初期値で、画像の直後に本文を接着すると本文ごとセンター寄せになる
    （2026-09-28 実測）。キャプションは max_caption 文字以内に収めること。
    """
    return page.evaluate("""(maxCap) => {
        const pm = document.querySelector('.ProseMirror');
        if (!pm) return {error: 'ProseMirror なし'};
        const problems = [];
        const caps = [...pm.querySelectorAll('figcaption')];
        for (const c of caps) {
            const t = (c.innerText || '').replace(/\\s+/g, ' ').trim();
            if (t.length > maxCap) {
                problems.push(`figcaption が長すぎ（${t.length}文字 > ${maxCap}）: ${t.slice(0,40)}…`);
            }
        }
        const sels = ['p', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote', 'figcaption'];
        const alignTally = {};
        for (const s of sels) {
            for (const e of pm.querySelectorAll(s)) {
                const t = (e.innerText || '').replace(/\\s+/g, ' ').trim();
                // 空要素は視覚的に無影響なので集計しない
                if (!t) continue;
                const a = getComputedStyle(e).textAlign;
                alignTally[a] = (alignTally[a] || 0) + 1;
            }
        }
        for (const [k, v] of Object.entries(alignTally)) {
            if (k !== 'start' && k !== 'left') {
                problems.push(`text-align=${k} が ${v} 要素に残存（左寄せになっていない）`);
            }
        }
        // 空段落（<br> だけ / 空白だけ）の数 = 画像と文字の隙間の大きさ
        let emptyP = 0;
        for (const e of pm.querySelectorAll('p, div')) {
            if (e.closest('figure')) continue;
            if (e.querySelector('p, figure, img, ul, ol')) continue;
            const t = (e.innerText || '').replace(/[\\s\\u3000]/g, '');
            if (!t) emptyP++;
        }
        if (emptyP > 2) {
            problems.push(`空段落が ${emptyP} 個ある（画像と文字の間隔が広い）`);
        }
        return {
            figure: pm.querySelectorAll('figure').length,
            figcaption: caps.length,
            h2: pm.querySelectorAll('h2').length,
            h3: pm.querySelectorAll('h3').length,
            p: pm.querySelectorAll('p').length,
            emptyP: emptyP,
            alignTally: alignTally,
            problems: problems,
        };
    }""", max_caption)


def print_validation(page):
    v = validate_body(page)
    if v.get("error"):
        print(f"  [検証] エラー: {v['error']}", flush=True)
        return v
    print(f"  [検証] figure={v['figure']} figcaption={v['figcaption']} "
          f"h2={v['h2']} h3={v['h3']} p={v['p']} 空段落={v.get('emptyP', '?')}", flush=True)
    print(f"  [検証] text-align 内訳: {v['alignTally']}", flush=True)
    if v["problems"]:
        for p in v["problems"]:
            print(f"  [検証][NG] {p}", flush=True)
    else:
        print("  [検証] 問題なし", flush=True)
    return v


def remove_empty_paragraphs(page, max_iter=80):
    """本文中の空 <p>（<br> だけ / 空白だけ）を順に削除する。

    note は見出しの直後・画像の前後に空段落を残すため
    （2026-09-28 実測）、入力側で完璧に潰すのは困難。
    入力後に «空段落を 1 つクリック → Backspace» を繰り返して掃除する。
    """
    removed = 0
    for _ in range(max_iter):
        idx = page.evaluate("""() => {
            const pm = document.querySelector('.ProseMirror');
            let n = 0;
            for (const e of pm.children) {
                if (e.tagName !== 'P') continue;
                if (e.querySelector('img, figure, br.ProseMirror-trailingBreak + img')) continue;
                const t = (e.innerText || '').replace(/[\\s\\u3000]/g, '');
                if (!t) return n;
                n++;
            }
            return -1;
        }""")
        if idx is None or idx < 0:
            break
        p = page.locator('.ProseMirror > p').nth(idx)
        try:
            p.scroll_into_view_if_needed(timeout=4000)
            page.wait_for_timeout(200)
            p.click(timeout=4000)
            page.wait_for_timeout(250)
            page.keyboard.press("Backspace")
            page.wait_for_timeout(320)
            removed += 1
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] 空段落削除を中断: {e}")
            break
    if removed:
        print(f"    空段落を {removed} 個削除", flush=True)
    return removed


def click_button_by_text(page, text, timeout=30):
    """テキストが一致する <button> を JS で探して座標クリックする。

    note のボタンは React で再描画されるため、 get_by_role() は要素が
    detached になって失敗することが多い（2026-09-29 実測）。座標を取得して
    mouse.click() 才是最安定。見つからなければ False。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        pos = page.evaluate("""(t) => {
            for (const b of document.querySelectorAll('button')) {
                const bt = (b.innerText || '').trim();
                const al = (b.getAttribute('aria-label') || '').trim();
                if (bt === t || al === t) {
                    const r = b.getBoundingClientRect();
                    if (r.width < 1 || r.height < 1) continue;
                    return {x: r.left + r.width / 2, y: r.top + r.height / 2,
                            disabled: b.disabled === true};
                }
            }
            return null;
        }""", text)
        if pos and not pos["disabled"]:
            page.mouse.move(pos["x"], pos["y"])
            page.wait_for_timeout(300)
            page.mouse.click(pos["x"], pos["y"])
            return True
        page.wait_for_timeout(1200)
    return False


def public_note_url(page, key):
    """ブラウザ内 fetch で note API を叩き、公開済みなら公開URLを返す。"""
    return page.evaluate("""async (k) => {
        try {
            const res = await fetch('https://note.com/api/v3/notes/' + k,
                                    {credentials: 'include'});
            if (res.status !== 200) return null;
            const j = await res.json();
            const d = j.data || {};
            if (!d.is_published && d.status !== 'published') return null;
            return d.note_url || null;
        } catch (e) { return null; }
    }""", key)


def note_status(page, key):
    """Fetch a note's current status via the browser-side API (same fetch shape as public_note_url)."""
    return page.evaluate("""async (k) => {
        try {
            const res = await fetch('https://note.com/api/v3/notes/' + k, {credentials: 'include'});
            if (res.status !== 200) return null;
            const j = await res.json();
            const d = j.data || {};
            return {status: d.status, is_published: !!d.is_published, name: d.name || ''};
        } catch (e) { return null; }
    }""", key)


def _dump_delete_diagnostics(page, key, stage):
    """Best-effort screenshot + visible-button dump for debugging a failed delete_note() step.
    Returns the screenshot path (or None if even that failed) — never raises itself."""
    try:
        path = os.path.join(BASE, "data", f"note_delete_fail_{key}_{stage}.png")
        page.screenshot(path=path, full_page=True)
    except Exception:  # noqa: BLE001
        path = None
    try:
        texts = page.evaluate(
            "() => Array.from(document.querySelectorAll('button, [role=menuitem], a'))"
            ".map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 60)"
        )
        print(f"  [debug] note {key} @ {stage}: url={page.url}", flush=True)
        print(f"  [debug] visible button/menuitem/link texts: {texts}", flush=True)
    except Exception:  # noqa: BLE001
        pass
    return path


def delete_note(page, key, expected_title):
    """Delete a note (published OR draft) from the '自分の記事' list page.

    2026-11-24 実測: エディタの「その他」メニューには削除が無く（あるのは「変更履歴」だけ）、
    昔のコードは「削除」ボタンと誤認して画像ツールバーの削除を押していた。公式ヘルプどおり
    プロフィール → 自分の記事 (https://note.com/notes) の行メニューから削除する。

    Flow: find the row by its note key -> verify the row title against `expected_title` ->
    open that row's menu (aria-labelledby ties it to the button) -> click 削除 -> confirm ->
    verify via /api/v3/notes/<key> that status == deleted and the row is gone. Any mismatch
    raises BEFORE a destructive click. Native confirm() is accepted; a custom [role=dialog]
    is confirmed with its 削除する button.
    """
    st = note_status(page, key)
    if st is None:
        raise RuntimeError(f"note {key}: 現在の状態をAPIで取得できません(削除操作を中止)")
    if st["status"] == "deleted":
        return  # already gone, nothing to do — idempotent
    page.goto("https://note.com/notes", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    row_anchor = page.locator(f'a[href*="{key}"]').first
    is_draft_row = row_anchor.count() == 0
    if not is_draft_row:
        row = row_anchor.locator("xpath=ancestor::li[1]")
    else:
        # 下書き行には記事URLの<a>が無く、代わりに「{title}を編集」ボタンがある。
        # APIで status=draft かつ name が期待タイトルであることを先に確認し、
        # 一覧からは「同じタイトル & 下書きバッジ」の行が1件だけの場合に限定する。
        if st["status"] != "draft" or st.get("name", "").strip() != expected_title.strip():
            _dump_delete_diagnostics(page, key, "row-not-found")
            raise RuntimeError(f"note {key}: 「自分の記事」一覧に行が見つかりません(削除操作を中止)")
        row_index = page.evaluate(
            """(title) => {
                const all = Array.from(document.querySelectorAll('li'));
                const hits = all.filter(li => {
                    const h = li.querySelector('h3');
                    return h && (h.innerText || '').trim() === title
                        && (li.innerText || '').includes('下書き');
                });
                return hits.length === 1 ? all.indexOf(hits[0]) : -1;
            }""", expected_title.strip())
        if row_index < 0:
            _dump_delete_diagnostics(page, key, "row-not-found")
            raise RuntimeError(f"note {key}: 下書き行が一意に特定できません(削除操作を中止)")
        row = page.locator("li").nth(row_index)
    actual_title = (row.locator("h3").first.inner_text() or "").strip()
    if actual_title != expected_title.strip():
        _dump_delete_diagnostics(page, key, "title-mismatch")
        raise RuntimeError(
            f"note {key}: 一覧のタイトル「{actual_title}」が期待値「{expected_title}」と"
            "一致しないため中止(誤削除防止)")

    native_dialog = {"seen": None}
    page.on("dialog", lambda d: (native_dialog.__setitem__("seen", d.message), d.accept()))

    # 下書き行には先頭に「〜を編集」ボタンがあり、その次が行メニューなので、
    # aria-haspopup 付きのボタンを明示的に選ぶ（ published 行でも同じボタン）。
    menu_button = row.locator('button[aria-haspopup="true"]').first
    if menu_button.count() == 0:
        menu_button = row.locator("button").first
    button_id = menu_button.get_attribute("id")
    menu_button.click()
    menu = (page.locator(f'[role="menu"][aria-labelledby="{button_id}"]')
            if button_id else page.locator('[role="menu"]').last)
    try:
        menu.wait_for(state="visible", timeout=10000)
    except Exception as e:  # noqa: BLE001
        shot = _dump_delete_diagnostics(page, key, "row-menu")
        raise RuntimeError(f"note {key}: 行メニューが開きません(削除操作を中止、"
                           f"スクリーンショット: {shot}): {e}") from e

    delete_item = menu.locator('button[role="menuitem"][data-key="削除"]')
    if delete_item.count() == 0:
        _dump_delete_diagnostics(page, key, "no-delete-menuitem")
        raise RuntimeError(f"note {key}: 行メニューに「削除」がありません(削除操作を中止)")
    _dump_delete_diagnostics(page, key, "pre-delete-click")
    delete_item.click()
    page.wait_for_timeout(1500)
    dialog = page.locator('[role="dialog"]')
    try:
        dialog.wait_for(state="visible", timeout=10000)
    except Exception as e:  # noqa: BLE001
        if native_dialog["seen"] is not None:
            print(f"  [debug] note {key}: native confirm: {native_dialog['seen']}", flush=True)
        else:
            shot = _dump_delete_diagnostics(page, key, "confirm-dialog")
            raise RuntimeError(f"note {key}: confirm dialog did not appear (screenshot: {shot}): {e}") from e
    else:
        confirm = dialog.get_by_role("button", name="削除する")
        if confirm.count() == 0:
            _dump_delete_diagnostics(page, key, "confirm-button")
            raise RuntimeError(f"note {key}: 確認ダイアログに「削除する」がありません(削除操作を中止)")
        confirm.first.click()
        page.wait_for_timeout(3000)

    st2 = note_status(page, key)
    if st2 is None or st2["status"] != "deleted":
        raise RuntimeError(f"note {key}: 削除操作後もAPI上でdeleted状態になっていません: {st2}")
    page.goto("https://note.com/notes", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    still_there = page.locator(f'a[href*="{key}"]').count() > 0
    if is_draft_row:
        still_there = still_there or page.evaluate(
            """(title) => Array.from(document.querySelectorAll('li')).some(li => {
                const h = li.querySelector('h3');
                return h && (h.innerText || '').trim() === title
                    && (li.innerText || '').includes('下書き');
            })""", expected_title.strip())
    if still_there:
        raise RuntimeError(f"note {key}: API上はdeletedですが一覧にまだ行が残っています")


def publish_note(page, timeout=120):
    """note の下書きを公開する（2026-09-29 実測の2段階）。

    1. 編集画面の「公開に進む」を押す  → /publish/ の公開設定画面に移動するだけ
    2. 公開設定画面右上の「投稿する」を押す → ここで初めて公開される

    1段目だけで止めると公開されないので、2段目まで実行する。
    公開済みarticle では 1段目のボタンが「更新する」になる。
    """
    # 現在の下書きkey（編集URLから取り出す）
    # key は "n" 始まり（例 n0893de9eb19f）なので [a-z0-9] で拾う
    m = re.search(r"/notes/([a-z0-9]{12,})", page.url)
    key = m.group(1) if m else None

    # --- 1段目: 公開に進む
    step1 = None
    for name in ("公開に進む", "更新する"):
        if click_button_by_text(page, name, timeout=25):
            step1 = name
            break
    if step1 is None:
        print("  [warn] 「公開に進む」/「更新する」がありません。"
              "ブラウザ側で手で操作してください。", flush=True)
        return None
    print(f"  「{step1}」を押します…", flush=True)
    page.wait_for_timeout(4000)

    if "/publish/" not in page.url:
        print(f"  [warn] 公開設定画面(/publish/)へ移動しませんでした: {page.url}",
              flush=True)
        return None
    print("  公開設定画面(/publish/)に遷移しました", flush=True)
    page.wait_for_timeout(4000)

    # --- 2段目: 投稿する
    # 公開済み記事を再更新する場合は「投稿する」ではなく「更新する」になる
    # （2026-09-29 実測。タイトル差し替えのとき publish_note() が止まって Manual に落ちた）
    if not (click_button_by_text(page, "投稿する", timeout=30)
            or click_button_by_text(page, "更新する", timeout=30)):
        print("  [warn] 公開設定画面の「投稿する」/「更新する」がありません。"
              "ブラウザ側で手で押してください。", flush=True)
        return None
    print("  「投稿する」を押します…", flush=True)
    page.wait_for_timeout(12000)
    try:
        page.wait_for_load_state("networkidle", timeout=90000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(4000)

    # --- 公開確認（API で検証する。遷移先は like_reaction_setting などに飛ぶため）
    if key:
        url = public_note_url(page, key)
        if url:
            print(f"  公開しました: {url}", flush=True)
            return url
        print("  [warn] API 上ではまだ公開されていません。"
              "「投稿する」の后再読込が必要かもしれません。", flush=True)
    print(f"  遷移先: {page.url}", flush=True)
    return None


# ---------------------------------------------------------------- image paste


def download(url):
    """画像をダウンロードする。GitHub Pages に未デプロイならローカルの static/ を使う。

    2026-11-28: 11/18以降の記事で画像が `[画像: ...]` のままになっていた原因は、
    記事公開時に画像URLがまだデプロイされておらず 404 になっていたこと。
    ローカルに同じファイルがあればフォールバックして貼付できるようにする。
    """
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    fd, path = tempfile.mkstemp(suffix=ext, prefix="noteimg_")
    os.close(fd)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
            f.write(r.read())
        return path
    except Exception:
        parsed = urllib.parse.urlparse(url)
        if "kingsworksub-jpg.github.io" in parsed.netloc:
            # ローカルstatic/のファイル名はURLエンコードのまま保存されていることがある
            # (例: Roman_Baths%2C_Bath%2C_Somerset_69.jpg)ため、生パスも試す。
            candidates = [
                os.path.join(BASE, "static", parsed.path.lstrip("/")),
                os.path.join(
                    BASE, "static", urllib.parse.unquote(parsed.path).lstrip("/")),
            ]
            for local in candidates:
                if os.path.isfile(local):
                    shutil.copyfile(local, path)
                    print(f"    [info] 未デプロイ画像をローカルから使用: {local}", flush=True)
                    return path
        os.remove(path)
        raise


def count_figures(page):
    return page.evaluate(
        "() => document.querySelectorAll('.note-prose-image, figure, [data-image-id]').length"
    )


def figure_width(page):
    d = page.evaluate("""() => {
        const fs = [...document.querySelectorAll('.ProseMirror figure')];
        const f = fs[fs.length - 1];
        const i = f && f.querySelector('img');
        return i ? Math.round(i.getBoundingClientRect().width) : 0;
    }""")
    return d or 0


def shrink_image(page, steps=1):
    """画像ツールバーの「縮小」ボタンで幅を段階的に縮める。

    note は figure に float / style を保持しないため（2026-09-28 実測）、
    幅を変える手段は「縮小」ボタンだけ。1回押すと 620px → 372px。
    ツールバーは «画像をクリック» した時しか出ない（2026-09-28 実測）。
    """
    img = page.locator('.ProseMirror figure img').last
    try:
        img.scroll_into_view_if_needed(timeout=6000)
        page.wait_for_timeout(300)
        img.click(force=True, timeout=6000)      # 画像ツールバーを出すためクリック
        page.wait_for_timeout(1500)
    except Exception as e:  # noqa: BLE001
        print(f"    [warn] 画像クリック失敗: {e}")
        return 0

    base = figure_width(page)
    if not base:
        print("    [warn] 画像幅を測定できません", flush=True)
        return 0
    for _ in range(steps):
        btn = page.locator('button[aria-label="縮小"]').first
        try:
            if not btn.is_visible(timeout=5000):
                print("    [warn] 「縮小」ボタンが見えません", flush=True)
                break
            btn.click(force=True, timeout=6000)
            page.wait_for_timeout(2000)
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] 縮小失敗: {e}")
            break
    w = figure_width(page)
    print(f"    画像幅 {base}px → {w}px", flush=True)
    return w


CLIP_MIME = "image/png"  # Chromium の ClipboardItem.write が対応しているのは png だけ


def to_png(src_path):
    """jpeg/png を png に変換する（ClipboardItem は image/png しか書けない）。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    dst = src_path + ".conv.png"
    with Image.open(src_path) as im:
        im.convert("RGB").save(dst, "PNG")
    return dst


def svg_to_png(page, src_path):
    """SVG（レーダーチャート）をブラウザで描画して png にする。Pillow は SVG を読めない（2026-10-03）。"""
    svg = open(src_path, encoding="utf-8").read()
    dst = src_path + ".conv.png"
    p2 = page.context.new_page()
    try:
        p2.set_viewport_size({"width": 1000, "height": 920})
        p2.set_content('<html><body style="margin:0;background:#fff">'
                       '<div id="c" style="width:1000px">' + svg.replace("<svg ", '<svg width="1000" ', 1) + "</div></body></html>")
        p2.wait_for_timeout(300)
        p2.locator("#c svg").screenshot(path=dst)
    finally:
        p2.close()
    return dst


def paste_image(page, url):
    """画像をクリップボード経由で貼り込む。失敗時は False。

    2026-11-24: 画像URLが404でも例外を外に投げず、警告を出して記事の入力を続ける。
    画像1枚の失敗で投稿全体が止まり、再試行で下書きが乱立するのを防ぐ。
    """
    path = None
    try:
        path = download(url)
        orig = path
        conv = svg_to_png(page, orig) if orig.lower().endswith(".svg") else to_png(orig)
        if conv:
            path = conv
            try:
                os.remove(orig)
            except OSError:
                pass
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        page.evaluate(
            """async ([b64, mime]) => {
                const res = await fetch(`data:${mime};base64,${b64}`);
                const blob = await res.blob();
                await navigator.clipboard.write([new ClipboardItem({[mime]: blob})]);
            }""",
            [b64, CLIP_MIME],
        )
        before = count_figures(page)
        page.keyboard.press("Control+V")
        page.wait_for_timeout(3000)
        after = count_figures(page)
        if after <= before:
            # 失敗しても latin にはもう書き込まない（note は Enter で <br> を挿入するだけ）
            page.keyboard.press("Control+z")
            page.wait_for_timeout(500)
            return False
        page.keyboard.press("End")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"    [warn] 画像貼付失敗: {e}")
        return False
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass


LINK_LINE_RE = re.compile(r"^(Amazonで見る): (https://www\.amazon\.co\.jp/\S+)$")
# note はキー入力した Markdown リンクをリンク化しないので、変換済みドラフトの
# 「ラベル: URL」行と、手書きドラフトの [ラベル](URL) 行を HTML リンクとして貼る。
LABEL_URL_RE = re.compile(r"^(.{1,120}?): (https?://\S+)$")
MD_LINK_RE = re.compile(r"^\[([^\]]+)\]\((https?://\S+)\)$")
# 冒頭の「オリジナル記事」と末尾の「元記事（ブログ）」。ラベルは文字で、URL はリンクで貼る
ORIGINAL_LINE_RE = re.compile(
    r"^(オリジナル記事|元記事（ブログ）)[:：]\s*(https://kingsworksub-jpg\.github\.io/\S+)$")


def paste_link(page, text, url):
    """note は入力した URL を自動リンクしないので、HTML のリンクを貼り付ける。"""
    try:
        before = page.evaluate("() => document.querySelectorAll('.ProseMirror a[href]').length")
        page.evaluate(
            """async ([text, url]) => {
                const a = document.createElement('a');
                a.href = url; a.textContent = text;
                const html = new Blob([a.outerHTML], {type: 'text/html'});
                const plain = new Blob([text], {type: 'text/plain'});
                await navigator.clipboard.write([new ClipboardItem({'text/html': html, 'text/plain': plain})]);
            }""",
            [text, url],
        )
        page.keyboard.press("Control+V")
        page.wait_for_timeout(800)
        after = page.evaluate("() => document.querySelectorAll('.ProseMirror a[href]').length")
        if after > before:
            return True
        page.keyboard.press("Control+z")
        page.wait_for_timeout(300)
    except Exception as e:  # noqa: BLE001
        print(f"    [warn] リンク貼付失敗: {e}")
    return False


# ---------------------------------------------------------------- input


def convert_italics(text):
    """note は斜体のマークダウン記法（*斜体* / _斜体_）に未対応（2026-09-28 実測）。

    `**x**` と `__x__` だけが <strong> になるため、斜体はボールドにフォールバックする。
    画像行の `![alt](url)` は変えない。
    """
    if IMG_RE.match(text.strip()):
        return text
    bolds = []

    def stash(m):
        bolds.append(m.group(0))
        return f"\x00{len(bolds) - 1}\x00"

    t = re.sub(r"(\*\*|__).+?\1", stash, text)
    t = re.sub(r"(?<![A-Za-z0-9*])\*(?!\s)([^*\n]*\S[^*\n]*)(?<!\s)\*(?![A-Za-z0-9*])", r"**\1**", t)
    t = re.sub(r"(?<![A-Za-z0-9_])_(?!\s)([^_\n]*\S[^_\n]*)(?<!\s)_(?![A-Za-z0-9_])", r"**\1**", t)
    for i, b in enumerate(bolds):
        t = t.replace(f"\x00{i}\x00", b)
    return t


def new_paragraph(page, n=2):
    """次のブロック（見出し/リスト/画像）へ移動する。

    note の ProseMirror では Enter 1回だと同じ <p> 内に <br> が入るため、
    ブロック要素を新しい段落の先頭に出すには Enter 2回が必要（2026-09-28 実測）。
    """
    for _ in range(n):
        page.keyboard.press("Enter")
        page.wait_for_timeout(220)


def type_text(page, text, fast=False, delay=8):
    """テキストだけを入力する（変換記号なし）。"""
    if fast:
        page.keyboard.insert_text(text)
    else:
        page.keyboard.type(text, delay=delay)
    page.wait_for_timeout(120)


def type_markdown_line(page, text, fast=False):
    """マークダウン行を入力する。

    note が理解する記法（2026-09-28 実測）:
      - `## ` → <h2>、`### ` → <h3>
      - `- ` / `* ` / `1. ` → <ul>/<ol> の <li>
      - `**x**` と `__x__` → <strong>
      - `*斜体*` / `_斜体_` → 未対応（convert_italics でボールド化）
      - `# `（h1）と `> `（引用）は未対応
    """
    s = text.strip()

    m = re.match(r"^(#{2,6})\s+(.*)$", s)
    if m:
        page.keyboard.type(m.group(1) + " ", delay=90)
        page.wait_for_timeout(700)
        page.keyboard.type(convert_italics(m.group(2)), delay=8)
        return

    if LIST_RE.match(s):
        m2 = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", s)
        indent, marker, rest = m2.group(1), m2.group(2), m2.group(3)
        # 箇条書きの中のリンクも実リンクとして貼る（単に type すると文字列のままになる）
        lm = MD_LINK_RE.match(rest) or LABEL_URL_RE.match(rest)
        if lm:
            page.keyboard.type(marker + " ", delay=90)
            page.wait_for_timeout(400)
            paste_link(page, lm.group(1), lm.group(2))
            return
        if indent:
            for _ in range(len(indent) // 2):
                page.keyboard.press("Tab")
                page.wait_for_timeout(150)
        page.keyboard.type(marker + " ", delay=90)
        page.wait_for_timeout(600)
        page.keyboard.type(convert_italics(rest), delay=8)
        return

    m = ORIGINAL_LINE_RE.match(s)
    if m:
        page.keyboard.type(m.group(1) + ": ", delay=8)
        page.wait_for_timeout(600)  # 貼付失敗時の Ctrl+Z でラベルまで戻さないよう履歴を分ける
        if not paste_link(page, m.group(2), m.group(2)):
            page.keyboard.type(m.group(2), delay=8)
        return

    m = MD_LINK_RE.match(s)
    if m and paste_link(page, m.group(1), m.group(2)):
        return

    m = LINK_LINE_RE.match(s) or LABEL_URL_RE.match(s)
    if m and paste_link(page, m.group(1), m.group(2)):
        return

    t = convert_italics(s)
    if t.startswith("**") or "__" in t:
        page.keyboard.type(t, delay=8)  # 変換記号は実キー入力が必要
    elif fast:
        page.keyboard.insert_text(t)
    else:
        page.keyboard.type(t, delay=8)


def type_block(page, text, fast=False, enter=True):
    """後方互換のラッパ（1行入力 + Enter）。"""
    type_markdown_line(page, text, fast)
    if enter:
        page.keyboard.press("Enter")
        page.wait_for_timeout(120)


def fill_body(page, body, tags, use_images, fast, img_scale=0):
    """本文をブロック単位で入力する。

    note の仕様（2026-09-28 実測）に基づく:
      - Enter 1回 → 同じ <p> 内に <br> が入る
      - Enter 2回 → 兄弟の新しい <p> ができる（«空段落なし» で区切れる）
      - 画像は必ず «新しい段落» に貼り付ける。既存 <p> の末尾に貼ると
        後続のテキストがすべて <figcaption> に入ってしまう
      - note は figure に float / style を保持しない（JS で set しても破棄される）。
        img_scale で「縮小」ボタンにより幅だけ縮めることは可能。

    間隔の詰め方:
      ブロック境界では «Enter 2回» だけを使い、空 <p> は作らない。
      （Enter 1回 + Enter 1回 に分けると <br> だけの空段落が残って
        画像と文字の隙間が異常に広くなる）
    """
    blocks = split_blocks(body)
    total = len(blocks)
    at_line_start = True      # 直前に改行済み = 段落の先頭にいる

    for i, block in enumerate(blocks, 1):
        lines = block_lines(block)
        m = IMG_RE.match(lines[0].strip()) if len(lines) == 1 else None

        if m:
            url, alt = m.group("url"), m.group("alt")
            print(f"  [{i}/{total}] 画像: {os.path.basename(url)}", flush=True)
            if at_line_start:
                pass                      # すでに新しい段落の先頭
            else:
                # 画像は «Enter 1回» でよい。2 回だと図版の前に空 <p> が残る
                # （2026-09-28 実測: Enter1回=0個 / Enter2回=1個）
                new_paragraph(page, 1)
            ok = use_images and paste_image(page, url)
            if ok:
                if img_scale:
                    shrink_image(page, img_scale)
                # 図版直下の新しい <p> にカーソルを移す（後続本文を figcaption に入れない）
                if exit_image_caption(page):
                    at_line_start = True
                else:
                    new_paragraph(page, 2)
                    at_line_start = True
            else:
                type_markdown_line(page, f"[画像: {alt or url}]", fast)
                at_line_start = False
            continue

        head = lines[0]
        print(f"  [{i}/{total}] {head[:34]}", flush=True)

        prev_item = False
        prev_line = ""
        for j, line in enumerate(lines):
            is_item = bool(LIST_RE.match(line.strip()))

            if j == 0:
                if not at_line_start:
                    new_paragraph(page, 2)
            elif prev_item and is_item:
                page.keyboard.press("Enter")      # リストは Enter 1回で次の <li>
                page.wait_for_timeout(250)
            else:
                new_paragraph(page, 2)

            # 見出しの直後は note が空 <p> を残すので 1 つ潰す。
            # （実測: Enter2回のみ=1個 / Enter2回+Backspace=0個）
            if prev_line.strip().startswith("#") and not prev_item:
                page.keyboard.press("Backspace")
                page.wait_for_timeout(250)

            type_markdown_line(page, line, fast)
            prev_item = is_item
            prev_line = line
            at_line_start = False

    if tags:
        new_paragraph(page, 2)
        page.keyboard.type(tags, delay=30)   # #tag をチップ化させるため実キー入力
        page.wait_for_timeout(500)

    # 空段落を掃除して、画像と文字の間隔を詰める
    print("  [仕上げ] 空段落を削除（間隔を詰める）", flush=True)
    remove_empty_paragraphs(page)

    # 全文を左寄せに確定させる（中央/右になっている要素だけを修復）
    if not fast:
        print("  [仕上げ] 全段落を左寄せに統一（中央/右寄せの要素のみ修復）", flush=True)
        set_text_align(page, "指定なし")

    # 検証（figcaption 長すぎ / 中央寄せ残り を検出）
    print("  [検証] 本文レイアウトを検証", flush=True)
    print_validation(page)


def find_title_input(page):
    """タイトル欄を探す。実DOMは textarea[placeholder="記事タイトル"]（2026-09-28 実測）。"""
    cands = [
        page.locator('textarea[placeholder*="タイトル"]').first,
        page.locator('input[placeholder*="タイトル"]').first,
        page.get_by_placeholder(re.compile("タイトル")).first,
    ]
    for c in cands:
        try:
            c.wait_for(state="visible", timeout=8000)
            return c
        except Exception:  # noqa: BLE001, S110
            continue
    raise RuntimeError("タイトル欄が見つかりません（note のUIが変更された可能性があります）")


def find_body_editor(page):
    """本文の contenteditable を探す。実DOMは .ProseMirror（2026-09-28 実測）。"""
    cands = [
        page.locator('.ProseMirror[contenteditable="true"]').first,
        page.locator('.ProseMirror[contenteditable="true"]').last,
        page.locator('[contenteditable="true"]').first,
    ]
    for c in cands:
        try:
            c.wait_for(state="visible", timeout=10000)
            if c.evaluate("e => e.getBoundingClientRect().height") > 30:
                return c
        except Exception:  # noqa: BLE001, S110
            continue
    raise RuntimeError("本文エディタが見つかりません（note のUIが変更された可能性があります）")


def fill_title(page, title):
    el = find_title_input(page)
    el.click()
    el.fill(title)


LOGIN_URLS = ("/login", "accounts.google", "sign_in", "/signup")


def is_login_page(page):
    return any(k in page.url for k in LOGIN_URLS)


def is_logged_in(page):
    """投稿画面が開いている = ログイン済み。

    実DOM（2026-09-28 実測）:
      textarea[placeholder="記事タイトル"]
      div.ProseMirror[contenteditable="true"]
      ボタン: 下書き保存 / 公開に進む
    """
    if is_login_page(page):
        return False
    try:
        if page.locator(".ProseMirror").count() > 0:
            return True
        return page.locator(
            'textarea[placeholder*="タイトル"], input[placeholder*="タイトル"]'
        ).first.is_visible(timeout=3000)
    except Exception:  # noqa: BLE001
        return False


def ensure_logged_in(page, wait=0):
    if is_logged_in(page):
        return True
    if wait:
        print("  ブラウザでログインしてください。完了したらこの端末に Enter を押してください…")
        input()
    return is_logged_in(page)


def wait_for_login(page, timeout=900):
    """ログイン完了をポーリングで待つ（input() が使えない環境向け）。"""
    print("  ブラウザで note.com にログインしてください（自動検知します）…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_logged_in(page):
            print("  ログインを検知しました。")
            return True
        page.wait_for_timeout(2000)
    return False


# ---------------------------------------------------------------- main


def open_editor(p, headless=False, url=None, navigate=True):
    """ブラウザを起動して編集画面を開く。navigate=False ならページを開かず ctx/page だけ返す。

    url を渡すとその記事を開く（既存の公開済み記事を更新するとき用）。
    省略時は新規下書き（editor.note.com/new）を作る。**新規下書きを作るたびに
    タイトル・本文が空の下書きが1件増える**ので、既存記事触るときは key を渡すこと
    （2026-09-29 実測）。
    """
    ctx = p.chromium.launch_persistent_context(
        PROFILE,
        headless=headless,
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        viewport={"width": 1440, "height": 900},
        user_agent=UA,
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        ignore_https_errors=True,
    )
    ctx.add_init_script(INIT_SCRIPT)
    try:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] クリップボード権限を付与できませんでした: {e}")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    if not navigate:
        print("  画面: (未遷移)", flush=True)
        return ctx, page

    # 初回だけ編集画面が空のことがあるため最大3回リトライする。
    # ただし「自分の記事」一覧など編集画面以外を開くときは ProseMirror が無いので
    # リトライせず1回だけ読み込む（2026-11-24: 削除対象42回の無駄な待ちを防止）。
    target = url or NEW_NOTE_URL
    is_editor = "editor.note.com" in target
    for attempt_no in range(1, 4 if is_editor else 2):
        page.goto(target, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(12000 if is_editor else 3000)
        if is_login_page(page) or page.locator(".ProseMirror").count() > 0 or not is_editor:
            break
        print(f"  [retry] 編集画面が空でした（{attempt_no} 回目）。再読み込みします…", flush=True)
    print(f"  画面: {page.url}", flush=True)
    return ctx, page


def do_login(p, args):
    ctx, page = open_editor(p)
    print(f"ブラウザを起動しました: {page.url}", flush=True)
    if is_logged_in(page):
        print("  既にログイン済みです。", flush=True)
    else:
        ok = wait_for_login(page, timeout=args.login_timeout)
        if not ok:
            print("  [error] タイムアウトしました。ログインし直してください。", flush=True)
            ctx.close()
            return
    page.wait_for_timeout(1500)
    print("ログイン状態を保存しました。以後は --login なしでも利用できます。", flush=True)
    time.sleep(2)
    ctx.close()


def list_drafts():
    if not os.path.isdir(DRAFTS):
        print(f"note ドラフトがありません: {DRAFTS}")
        return []
    out = sorted(f for f in os.listdir(DRAFTS) if f.endswith(".note.txt"))
    paid = os.path.join(DRAFTS, "paid")
    if os.path.isdir(paid):
        out += sorted("paid/" + f for f in os.listdir(paid) if f.endswith(".note.txt"))
    return out


def draft_path(slug):
    """slug のドラフトを探す。有料記事の下書きは paid/ にある。"""
    for sub in ("", "paid"):
        cand = os.path.join(DRAFTS, sub, slug + ".note.txt")
        if os.path.exists(cand):
            return cand
    return os.path.join(DRAFTS, slug + ".note.txt")


JS_NOTE_LIST = """async (pg) => {
  const r = await fetch('https://note.com/api/v2/note_list/contents?limit=20&page=' + pg,
                       {credentials: 'include'});
  if (r.status !== 200) return {status: r.status};
  return await r.json();
}"""

JS_NOTE_DETAIL = """async (key) => {
  const r = await fetch('https://note.com/api/v3/notes/' + key, {credentials: 'include'});
  if (r.status !== 200) return {status: r.status};
  const j = await r.json();
  return j.data || {};
}"""


def _collect_existing_notes(page, out):
    """既に開いたページのブラウザ内 fetch で自分の記事を列挙し out に追加する。"""
    page.goto("https://note.com/notes", wait_until="domcontentloaded", timeout=60000)
    for pg in range(1, 11):
        d = page.evaluate(JS_NOTE_LIST, pg)
        data = (d or {}).get("data") or {}
        notes = data.get("notes") or []
        if not notes:
            break
        for n in notes:
            key = n.get("key")
            if not key:
                continue
            status = n.get("status") or ""
            title = n.get("name") or ""
            if status == "draft" or not title:
                try:
                    detail = page.evaluate(JS_NOTE_DETAIL, key)
                    title = (detail or {}).get("name") or title
                except Exception:  # noqa: BLE001
                    pass
            out.append({"key": key, "status": status, "title": title,
                        "url": f"https://note.com/shining_finger01/n/{key}"
                        if status == "published" else ""})
        if data.get("isLastPage"):
            break


def list_existing_notes(page=None):
    """ログイン済みプロファイルから、公開済み/下書き両方の記事を読み取り専用で列挙する。

    note の自分の記事一覧は API /api/v2/note_list/contents が status と key を返す。
    下書きは name が null なので /api/v3/notes/{key} でタイトルを取得する。
    (2026-11-24 調査。投稿前の重複チェックと下書き再利用に使う。)

    `page` を渡すとそのページを使う（sync_playwright コンテキスト内から呼ぶ場合必須）。
    省略時は監査スクリプト用に一時ブラウザを起動する。
    """
    out = []
    if page is not None:
        _collect_existing_notes(page, out)
        return out
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=True,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            user_agent=UA, locale="ja-JP", timezone_id="Asia/Tokyo", ignore_https_errors=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _collect_existing_notes(page, out)
        finally:
            ctx.close()
    return out


def find_existing_notes(page, title):
    """タイトル完全一致のnote記事を status 別に返す。"""
    wanted = (title or "").strip()
    return [n for n in list_existing_notes(page) if (n.get("title") or "").strip() == wanted]


def post_one(p, path, args):
    slug = os.path.basename(path).replace(".note.txt", "")
    title, tags, body = parse_draft(path)
    print(f"\n=== {slug} ===")
    print(f"  タイトル: {title}")
    print(f"  タグ    : {tags[:60]}")
    print(f"  本文    : {len(body)} 文字 / {len(split_blocks(body))} ブロック")

    # 2026-11-24 の重複・下書き乱立事故対策。
    # 旧コードは毎回 open_editor() で新規下書きを作っていたため、画像取得失敗などで
    # 再試行するたびに空の下書きが残り、公開済み記事と同名の下書きも作られていた。
    # まずブラウザだけ起動し(新規下書きは作らない)、同じ sync_playwright セッションの
    # page で既存記事を確認してから、既存下書き or 新規エディタへ遷移する。
    # 別の sync_playwright() をネストさせると "Sync API inside asyncio loop" で失敗する。
    ctx, page = open_editor(p, navigate=False)
    try:
        try:
            existing = find_existing_notes(page, title)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 既存note記事の確認に失敗しました: {e}")
            existing = []
        published = [n for n in existing if n["status"] == "published"]
        drafts = [n for n in existing if n["status"] == "draft"]

        if published and not getattr(args, "allow_duplicate", False):
            keys = ", ".join(n["key"] for n in published)
            print(f"  [abort] 同名タイトルの公開済みnoteが既にあります (key: {keys})。"
                  "重複投稿を避けるため中止します。既存記事を更新する場合は --edit-key <key>、"
                  "明示的に重複を作る場合のみ --allow-duplicate を使ってください。")
            return None
        editor_url = None
        if drafts:
            key = drafts[0]["key"]
            print(f"  既存下書き key={key} を再利用します(新規下書きは作りません)。")
            editor_url = f"https://editor.note.com/notes/{key}/edit/"
        elif published:
            print("  [warn] --allow-duplicate が指定されたため、同名記事を新規作成します。")

        target_url = editor_url or NEW_NOTE_URL
        for attempt_no in range(1, 4):
            page.goto(target_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(12000)
            if is_login_page(page) or page.locator(".ProseMirror").count() > 0:
                break
            print(f"  [retry] 編集画面が空でした（{attempt_no} 回目）。再読み込みします…", flush=True)
        if not is_logged_in(page):
            print("  ログインが必要です。ブラウザを開いたままログインしてください…", flush=True)
            if not wait_for_login(page, timeout=args.login_timeout):
                print("  [error] ログインできません。先に --login を実行してください。")
                return None
            page.goto(target_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(12000)
        fill_title(page, title)
        ed = find_body_editor(page)
        ed.click()
        page.wait_for_timeout(400)
        t0 = time.time()
        fill_body(page, body, tags, not args.no_images, args.fast, args.img_scale)
        print(f"  入力完了 ({time.time() - t0:.0f} 秒)")

        page.wait_for_timeout(3000)
        if args.save:
            sbtn = page.get_by_role("button", name="下書き保存").first
            try:
                sbtn.click(timeout=15000)
                page.wait_for_timeout(4000)
                print("  下書き保存しました。", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  [warn] 下書き保存: {e}", flush=True)
        if args.publish:
            url = publish_note(page)
            if url:
                return url
        print("  ここで内容を確認して、ブラウザの「公開に進む」を押してください。", flush=True)
        print("  (自動で押す場合は --publish を付けます)", flush=True)
        if args.no_wait:
            time.sleep(args.hold)
        else:
            try:
                input("  ブラウザを閉じてよいったら Enter …")
            except EOFError:
                print("  (stdin なし。時間経過で閉じます)", flush=True)
                time.sleep(args.hold)
        return page.url
    finally:
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass


def edit_existing_note(p, key, path, args):
    """既存の note 記事(key)を、draft ファイルの最新内容で上書きして再公開する。

    2026-10-23: Amazonアフィリエイトリンクのタグを note-img-sub-22 に一括で
    書き換えるため追加。新規下書きは作らず、既存記事の編集URLを直接開いて
    タイトル・本文を全消去 → 再入力 → 「更新する」で上書きする(重複投稿防止)。
    """
    slug = os.path.basename(path).replace(".note.txt", "")
    title, tags, body = parse_draft(path)
    print(f"\n=== 既存記事を更新: {slug} (key={key}) ===")

    ctx, page = open_editor(p, url=f"https://editor.note.com/notes/{key}/edit/")
    try:
        if not is_logged_in(page):
            print("  [error] ログインが必要です。先に --login を実行してください。")
            return None

        fill_title(page, title)

        ed = find_body_editor(page)
        ed.click()
        page.wait_for_timeout(300)
        page.keyboard.press("Control+a")
        page.wait_for_timeout(200)
        page.keyboard.press("Backspace")
        page.wait_for_timeout(500)

        t0 = time.time()
        fill_body(page, body, tags, not args.no_images, args.fast, args.img_scale)
        print(f"  入力完了 ({time.time() - t0:.0f} 秒)")
        page.wait_for_timeout(3000)

        if args.publish:
            url = publish_note(page)
            if url:
                return url
            print("  [warn] 自動公開に失敗しました。ブラウザで確認してください。")
        print("  ブラウザで内容を確認してから「更新する」を押してください。", flush=True)
        if args.no_wait:
            time.sleep(args.hold)
        else:
            try:
                input("  ブラウザを閉じてよかったら Enter …")
            except EOFError:
                time.sleep(args.hold)
        return page.url
    finally:
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--profile", default=None, help="Chromium プロファイルの場所")
    ap.add_argument("--login-timeout", type=int, default=900, help="ログイン待ちの秒数")
    ap.add_argument("--no-wait", action="store_true", help="確認待ちの Enter を求めない")
    ap.add_argument("--hold", type=int, default=180,
                    help="--no-wait のときブラウザを開いておく秒数")
    ap.add_argument("--save", action="store_true", help="下書き保存ボタンを押す")
    ap.add_argument("--img-scale", type=int, default=0,
                    help="画像を「縮小」ボタンで縮める回数（0=full幅620px、1=約372px）")
    ap.add_argument("--delete-key", help="削除する公開済み記事の note key(n始まり)")
    ap.add_argument("--expect-title", help="--delete-key 使用時、削除前に照合するタイトル(必須・誤削除防止)")
    ap.add_argument("--edit-key", help="既存記事のnote key(n始まり)。--slugのdraftで本文を上書きして再公開する")
    ap.add_argument("--allow-duplicate", action="store_true",
                    help="同名の公開済みnoteがあっても新規作成する(通常は重複事故防止のため中止)")
    args = ap.parse_args()

    global PROFILE  # noqa: PLW0603
    if args.profile:
        PROFILE = args.profile

    with sync_playwright() as p:
        if args.login:
            do_login(p, args)
            return

        if args.delete_key:
            if not args.expect_title:
                print("[error] --delete-key には --expect-title が必須です(誤削除防止のため)")
                sys.exit(1)
            ctx, page = open_editor(p, url="https://note.com/notes")
            try:
                if is_login_page(page):
                    print("  ログインが必要です。先に --login を実行してください。")
                    sys.exit(1)
                delete_note(page, args.delete_key, args.expect_title)
                print(f"DELETED: {args.delete_key}")
            finally:
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass
            return

        if args.edit_key:
            if not args.slug:
                print("[error] --edit-key には --slug が必須です")
                sys.exit(1)
            cand = draft_path(args.slug)
            if not os.path.exists(cand):
                print(f"ドラフトが見つかりません: {cand}")
                sys.exit(1)
            result = edit_existing_note(p, args.edit_key, cand, args)
            if result:
                print(f"RESULT: {result}")
            return

        if args.all:
            targets = [os.path.join(DRAFTS, f) for f in list_drafts()]
        elif args.slug:
            cand = draft_path(args.slug)
            if not os.path.exists(cand):
                print(f"ドラフトが見つかりません: {cand}")
                print("利用可能:")
                for f in list_drafts():
                    print("  " + f.replace(".note.txt", ""))
                return
            targets = [cand]
        else:
            print("note ドラフト一覧:")
            for f in list_drafts():
                print("  " + f.replace(".note.txt", ""))
            print("\n--slug <slug> で個別に投稿、--all で全件")
            return

        for t in targets:
            result = post_one(p, t, args)
            if result:
                print(f"RESULT: {result}")


if __name__ == "__main__":
    main()
