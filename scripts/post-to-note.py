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
"""
import argparse
import base64
import os
import re
import sys
import tempfile
import time
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
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    fd, path = tempfile.mkstemp(suffix=ext, prefix="noteimg_")
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


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


def paste_image(page, url):
    """画像をクリップボード経由で貼り込む。失敗時は False。"""
    path = download(url)
    try:
        orig = path
        conv = to_png(orig)
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
        try:
            os.remove(path)
        except OSError:
            pass


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
        if indent:
            for _ in range(len(indent) // 2):
                page.keyboard.press("Tab")
                page.wait_for_timeout(150)
        page.keyboard.type(marker + " ", delay=90)
        page.wait_for_timeout(600)
        page.keyboard.type(convert_italics(rest), delay=8)
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


def open_editor(p, headless=False, url=None):
    """ブラウザを起動して編集画面を開く。

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

    # 初回だけ編集画面が空のことがあるため最大3回リトライする
    target = url or NEW_NOTE_URL
    for attempt_no in range(1, 4):
        page.goto(target, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(12000)
        if is_login_page(page) or page.locator(".ProseMirror").count() > 0:
            break
        print(f"  [retry] 編集画面が空でした（{attempt_no} 回目）。再読み込みします…", flush=True)
    print(f"  編集画面: {page.url}", flush=True)
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
    return sorted(f for f in os.listdir(DRAFTS) if f.endswith(".note.txt"))


def post_one(p, path, args):
    slug = os.path.basename(path).replace(".note.txt", "")
    title, tags, body = parse_draft(path)
    print(f"\n=== {slug} ===")
    print(f"  タイトル: {title}")
    print(f"  タグ    : {tags[:60]}")
    print(f"  本文    : {len(body)} 文字 / {len(split_blocks(body))} ブロック")

    ctx, page = open_editor(p)
    try:
        if not is_logged_in(page):
            print("  ログインが必要です。ブラウザを開いたままログインしてください…", flush=True)
            if not wait_for_login(page, timeout=args.login_timeout):
                print("  [error] ログインできません。先に --login を実行してください。")
                return None
            page.goto(NEW_NOTE_URL, wait_until="domcontentloaded", timeout=90000)
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
    args = ap.parse_args()

    global PROFILE  # noqa: PLW0603
    if args.profile:
        PROFILE = args.profile

    with sync_playwright() as p:
        if args.login:
            do_login(p, args)
            return

        if args.all:
            targets = [os.path.join(DRAFTS, f) for f in list_drafts()]
        elif args.slug:
            cand = os.path.join(DRAFTS, args.slug + ".note.txt")
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
            post_one(p, t, args)


if __name__ == "__main__":
    main()
