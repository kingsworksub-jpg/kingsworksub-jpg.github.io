#!/usr/bin/env python
"""Generate blog *content* with opencode using a 4-stage model chain.

The posting job is orchestrated by opencode (google/gemini-3.5-flash#high), which handles claim,
research, image fetching, validation and publishing.  Only the generation work is delegated here:
the article body, title, frontmatter, image selection + placement, and the X post text.  The caller
writes the brief, calls this helper, then fetches the chosen images and verifies them visually.
Claude Code is not involved.

Usage:
    python scripts/oc_generate.py article --brief <brief.json> \
        --article-out <content/posts/slug.md> --meta-out <meta.json>
    python scripts/oc_generate.py text --instruction <file> [--out <file>]

The article mode runs opencode in a scratch directory.  The model writes
article.md and meta.json there; this script validates them against the same
rules as scripts/validate_post.py, enriches the figures with the candidate
metadata, and writes the two output files.

The brief (JSON) must contain:
    slug, date, slot_time, channel, category, article_type, theme, angle,
    target_chars, research, image_dir, image_candidates, recent_titles
and may contain:
    products (list of {name, asin, note}), channel_notes (extra instructions)

Each image candidate: {id, source, title, url, page, license, author, credit,
size}.  The caller derives them from `python scripts/topic_plan.py images`.

Exit code is 0 on success; on failure a diagnostic goes to stderr and the code
is non-zero, so the posting job can retry or mark the topic failed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

from model_chains import GENERATE_CHAIN, resolve_chain, split_models

MODEL_CHAIN = resolve_chain(GENERATE_CHAIN, "OC_GENERATE_MODEL_CHAIN", "OC_GENERATE_MODEL")
MODEL = MODEL_CHAIN[0]  # backwards-compatible alias for logs/callers
AGENT = "build"
DEFAULT_TIMEOUT = int(os.environ.get("OC_GENERATE_TIMEOUT", "540"))
FALLBACK_EXE = r"C:\Users\norio\AppData\Roaming\npm\opencode.cmd"
MIN_BODY = 3500          # must match validate_post.MIN_BODY
MIN_FIGURES = 2
MAX_FIGURES = 6
MIN_DESC, MAX_DESC = 90, 140
X_MAX_WEIGHT = 280

RULES = """\
あなたは日本語の専門ブログ記事を執筆するプロのライターです。
与えられたブリーフだけを根拠に、記事を1本完成させてください。作業ディレクトリに
  article.md  … frontmatter + 本文（Markdown）
  meta.json   … タイトル等のメタ情報
の2ファイルだけを作成してください。他のファイルは作らないでください。

## 守るルール
- 日本語だけで書く（製品名・固有名詞の英字は可）。中国語・韓国語・キリル文字・タイ文字を混ぜない。
- ブリーフの research に無い事実を作らない。推測や体験談を捏造しない。「実際に〜してみた」と書かない。
- 次の語句は使わない: あるレビューでは / 海外フォーラムでは / と評されている / 隅から隅まで / 味わい尽くす / の転載です / エージェント / 自動生成 / 読み込んで。
- Web検索・コマンド実行・画像の取得や生成はしない。画像はブリーフの image_candidates だけを使う。
- 本文は target_chars 字以上（既定5000字）。見出し `##` を3つ以上入れる。1段落は2〜3文で改行する。
- タイトルは言い回しを毎回変える。次の型・語は禁止: を全機能解剖 / の味と仕様 / の仕様と使い方 / の現在地 — / 徹底比較 / 隅から隅まで / 味わい尽くす / 五番勝負。
- description は110〜120字（必ず90〜140字に収める）。

## article.md の形式
先頭に次の frontmatter を置く（slug・date・category・slot_time はブリーフの値をそのまま使う）:
---
title: "<タイトル>"
description: "<説明>"
images: ["/images/og/<slug>.jpg"]
date: "<ブリーフの date>"
categories: ["<ブリーフの category>"]
tags: ["<タグ1>", "<タグ2>"]
draft: false
scheduled_time: "<ブリーフの slot_time>"
---
（本文）

画像は次の形式の figure を2〜5個入れる（比較記事は対象ごとに1枚）。左右は交互にする:
<figure class="photo photo--left">
<a href="https://www.amazon.co.jp/dp/<ASIN>?tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow"><img src="/<image_dir>/<ファイル名>.jpg" alt="…" width="220" height="150" loading="lazy"></a>
<figcaption>短い説明<span class="credit">候補の credit をそのまま</span></figcaption>
</figure>
- img の src は「/」+ meta.json の local_path と完全に一致させる。
- ASIN がブリーフにある製品の画像は必ず上の Amazon リンクで包む。無い製品は公式サイト等へのリンクで包む。
- Amazon のテキストリンク（https://www.amazon.co.jp/…）を1つでも書くなら、figure のうち少なくとも1枚は必ず
  <a href="https://www.amazon.co.jp/s?k=<商品名>&tag=nakimoto1-22" …> の検索リンクで包む（検証で必須）。
- Amazon のテキストリンクを書く場合は必ず ?tag=nakimoto1-22 を付ける。
- 画像を自分で作らない。候補に無い画像を使わない。同じ画像を使い回さない。

## CVR（全チャンネル共通）
- 導入直後に、メイン商品の画像＋「Amazonで見る →」の CTA ブロックを置く。
- 画像 figure の直後、および各商品の解説直後に「Amazonで価格とレビューを見る」等のテキストリンク（ASIN付き）を1本。
- 消耗品・関連アクセサリへのテキストリンクを1本。
- 価格を書いた段落の直後に「※現在の実売価格やセール状況は下のリンクからご確認ください。」を1回だけ。
- まとめの直前に、サイズ・設置・保証・維持費などの不安を1〜2文で先回りして払拭する。
- [CTA_BLOCK: …] / [TEXT_LINK: …] / [SUB_LINK: …] などのプレースホルダーは残さない（実リンクに置き換える）。

## meta.json の形式
{
  "title": "…",
  "description": "…",
  "tags": ["…", "…"],
  "x_post": "…",
  "figures": [
    {"candidate_id": "c1", "local_path": "<image_dir>/<ファイル名>.jpg", "alt": "…", "caption": "…", "credit": "候補の credit"}
  ]
}
- figures は記事で使った画像すべて（重複なし）。
- x_post は X 用。日本語本文100字前後＋改行＋記事URL（https://kingsworksub-jpg.github.io/posts/<slug>/）＋ハッシュタグ1〜2個。
  280字相当（日本語は1字2、URLは23字換算）を超えないこと。
"""


AMEBA_NOTES = """\

## Ameba チャンネル専用（channel が ameba のとき）
この記事は「ドリンク・飲料と酒の分析、カクテルの歴史やレシピ、ドリンク関連のツールやハック」に特化した
Ameba ブログ向け。次の標準構成とトーンに従う。
- カテゴリー: drink-lab（分析・成分・比率）/ drink-recipe（歴史・レシピ）/ drink-tools（道具・ギア）/
  drink-hack（ハック）/ drink（飲料の総合深掘り）。
- 構成: 1 導入（なぜ今・読者のメリット）→ 2 結論・要約データ（数値や比較表を先に）→
  3 詳細検証・解説（成分表の読み方・比率の科学・歴史）→ 4 実践・レシピ（配合比・温度・時間を具体的に）→
  5 まとめ・関連ツール。
- トーン: 感覚より数値と根拠。「〜と感じた」より「〜という結果になった」。専門用語はカタカナ併記＋一言解説。
  レシピは「この比率・この温度・この時間」と再現可能に。過度な煽り・根拠のない「最強」「絶対」・他社製品の貶めは禁止。
- Ameba は Amazon の生リンクを許可しない。画像リンクは Ameba Pick の商品カードに、ASIN 付きテキストリンクは
  Pick テキストリンクに変換される。検索リンク（/s?k=）は変換できないため、CTA と消耗品リンクにも実在の ASIN を使う。
  ASIN がブリーフに無い場合は、無理に作らず検索リンクでよい（投稿スクリプト側で処理される）。
"""


def die(msg: str) -> "NoReturn":  # noqa: F821
    print(f"oc_generate: {msg}", file=sys.stderr)
    sys.exit(1)


def find_opencode() -> str:
    exe = shutil.which("opencode")
    if exe:
        return exe
    if os.path.exists(FALLBACK_EXE):
        return FALLBACK_EXE
    return ""


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill opencode and its children.

    On Windows ``opencode`` is a .CMD shim that starts node.exe; killing only
    the shim leaves the node process (and its private server) running, which
    kept the 2026-11-16 flint run stuck after the timeout.  taskkill /T takes
    the whole tree down.
    """
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def run_opencode(prompt: str, cwd: str, timeout: int, model: str) -> tuple[int, str, str]:
    exe = find_opencode()
    if not exe:
        return 127, "", f"opencode CLI not found (looked for 'opencode' and {FALLBACK_EXE})"
    # The message is piped on stdin: the Windows opencode.CMD shim truncates a
    # multi-line argument at the first newline.
    # --standalone runs a private server; PWD/OLDPWD must point at cwd too, or
    # opencode inherits Git Bash's PWD and writes its files into that directory
    # instead of the scratch directory.
    cmd = [exe, "run", "--standalone", "--model", model, "--agent", AGENT, "--auto", "--archived",
           "--format", "json", "--title", "blog generation"]
    env = dict(os.environ)
    env["PWD"] = cwd
    env["OLDPWD"] = cwd
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                encoding="utf-8", errors="replace",
                                start_new_session=(os.name != "nt"))
    except OSError as exc:
        return 127, "", f"failed to launch opencode ({model}): {exc}"
    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        return 124, "", f"opencode ({model}) timed out after {timeout}s; process tree killed"
    return proc.returncode, stdout or "", stderr or ""


def strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```[a-zA-Z0-9]*\s*\n(.*?)\n```$", text, re.S)
    return m.group(1).strip() if m else text


def read_text(path: str) -> str:
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


def plain_body(article: str) -> str:
    m = re.match(r"---\n(.*?)\n---\n(.*)", article, re.S)
    body = m.group(2) if m else article
    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)|\[([^\]]*)\]\([^)]*\)|[#|*`>-]", r"\1", body)
    return re.sub(r"\s+", "", text)


def field(fm: str, name: str) -> str:
    m = re.search(rf'(?m)^{name}:\s*"?(.*?)"?\s*$', fm)
    return m.group(1) if m else ""


def weighted_len(text: str) -> int:
    """X weighted length: ASCII=1, others=2, every URL=23."""
    for url in re.findall(r"https?://\S+", text):
        text = text.replace(url, "U" * 23, 1)
    return sum(1 if ord(ch) < 128 else 2 for ch in text)


def validate(article: str, meta: dict, brief: dict) -> list[str]:
    errs: list[str] = []
    m = re.match(r"---\n(.*?)\n---\n(.*)", article, re.S)
    if not m:
        return ["article.md が frontmatter + 本文の形になっていない"]
    fm, body = m.group(1), m.group(2)

    title = field(fm, "title")
    desc = field(fm, "description")
    if not title:
        errs.append("frontmatter に title が無い")
    for b in ("を全機能解剖", "の味と仕様", "の仕様と使い方", "の現在地 — ", "徹底比較",
              "隅から隅まで", "味わい尽くす", "五番勝負"):
        if b in title:
            errs.append(f"タイトルに禁止語: {b}")
    if not (MIN_DESC <= len(desc) <= MAX_DESC):
        errs.append(f"description の長さ {len(desc)}（90〜140字）")
    if field(fm, "draft").lower() == "true":
        errs.append("draft: true のまま")
    if not re.search(rf'(?m)^images:\s*\[[^\]]*?/images/og/{re.escape(brief["slug"])}\.jpg[^\]]*\]\s*$', fm):
        errs.append("images: に /images/og/<slug>.jpg が無い（" + (re.search(r"(?m)^images:.*$", fm).group(0) if re.search(r"(?m)^images:", fm) else "images: 行なし") + "）")
    if field(fm, "date") != brief["date"]:
        errs.append(f"date がブリーフと違う（{field(fm, 'date')!r} != {brief['date']!r}）")
    if not re.search(rf'(?m)^categories:\s*\[\s*"{re.escape(brief["category"])}"\s*\]\s*$', fm):
        errs.append("categories がブリーフの category と違う（" + (re.search(r"(?m)^categories:.*$", fm).group(0) if re.search(r"(?m)^categories:", fm) else "categories: 行なし") + "）")
    if not re.search(rf'(?m)^scheduled_time:\s*"?{re.escape(brief["slot_time"])}"?\s*$', fm):
        errs.append(f"scheduled_time がブリーフの slot_time と違う（{field(fm, 'scheduled_time')!r}）")

    n = len(plain_body(article))
    if n < MIN_BODY:
        errs.append(f"本文が短い（{n}字 < {MIN_BODY}字）")
    if len(re.findall(r"(?m)^## ", body)) < 3:
        errs.append("見出し（##）が3つ未満")
    if re.search(r"\[(?:CTA_BLOCK|TEXT_LINK|SUB_LINK):", body):
        errs.append("CVRプレースホルダーが未解決")
    if re.search(r"[\u0400-\u04FF\u0E00-\u0E7F\uAC00-\uD7AF]", body):
        errs.append("日本語以外の文字（キリル・タイ・ハングル）が混入")

    figs = re.findall(r'<figure class="photo photo--(?:left|right)">(.*?)</figure>', body, re.S)
    if len(figs) < MIN_FIGURES:
        errs.append(f"figure.photo が {len(figs)} 枚（2枚以上必要）")
    if len(figs) > MAX_FIGURES:
        errs.append(f"figure.photo が多すぎる（{len(figs)} 枚）")
    srcs = []
    for f in figs:
        src = re.search(r'<img\s+src="([^"]+)"', f)
        if not src:
            errs.append("figure に img が無い")
            continue
        srcs.append(src.group(1))
        if "<figcaption>" not in f:
            errs.append(f"figcaption が無い: {src.group(1)}")
        cr = re.search(r'<span class="credit">(.*?)</span>', f, re.S)
        if not cr or not re.search(r"(CC|Public domain|Image:|Photo:?(?:\s|$)|撮影|出典)", cr.group(1), re.I):
            errs.append(f"クレジットが無い: {src.group(1)}")
    for dup in {s for s in srcs if srcs.count(s) > 1}:
        errs.append(f"同じ画像の使い回し: {dup}")

    if "amazon.co.jp" in body and figs and not any(
            re.search(r'<a\s+href="https://www\.amazon\.co\.jp/', f) for f in figs):
        errs.append("Amazon 製品の画像が Amazon リンクで包まれていない")
    for a in re.findall(r'https://www\.amazon\.co\.jp/[^\s"\)]+', body):
        if "tag=nakimoto1-22" not in a:
            errs.append(f"Amazon リンクに tag=nakimoto1-22 が無い: {a[:50]}")

    if not isinstance(meta.get("figures"), list):
        errs.append("meta.json に figures が無い")
        return errs
    local = {"/" + str(f.get("local_path", "")).lstrip("/") for f in meta["figures"]}
    for s in srcs:
        if s not in local:
            errs.append(f"記事の img が meta.json の figures に無い: {s}")
    if len(meta["figures"]) != len(srcs):
        errs.append(f"meta.json の figures 数 {len(meta['figures'])} と記事の画像数 {len(srcs)} が違う")
    if not meta.get("title"):
        errs.append("meta.json に title が無い")
    if not meta.get("x_post"):
        errs.append("meta.json に x_post が無い")
    else:
        w = weighted_len(str(meta["x_post"]))
        if w > X_MAX_WEIGHT:
            errs.append(f"x_post が長い（{w}字相当 > {X_MAX_WEIGHT}）")
    return errs


def enrich(meta: dict, brief: dict) -> None:
    cands = {c["id"]: c for c in brief.get("image_candidates", []) if "id" in c}
    for f in meta.get("figures", []):
        c = cands.get(f.get("candidate_id"))
        if not c:
            continue
        for k in ("source", "title", "url", "page", "license", "author", "credit", "size"):
            if k in c and not f.get(k):
                f[k] = c[k]


def build_prompt(brief: dict) -> str:
    notes = str(brief.get("channel_notes") or "なし")
    if brief.get("channel") == "ameba":
        notes += "\n" + AMEBA_NOTES
    return (RULES + "\n## 追加指示（チャンネル別）\n"
            + notes + "\n"
            + "\n## ブリーフ（この内容だけを根拠にする）\n"
            + json.dumps(brief, ensure_ascii=False, indent=1) + "\n")


def resolve_for_args(args: argparse.Namespace) -> list[str]:
    """--model pins one model, --models replaces the whole chain, otherwise use the default."""
    if getattr(args, "models", None):
        return split_models(args.models) or MODEL_CHAIN
    if getattr(args, "model", None):
        return [args.model]
    return MODEL_CHAIN


def cmd_article(args: argparse.Namespace) -> int:
    brief = json.loads(read_text(args.brief))
    for key in ("slug", "date", "slot_time", "channel", "category", "article_type",
                "theme", "target_chars", "research", "image_dir", "image_candidates"):
        if key not in brief:
            die(f"brief に {key} が無い")
    if not brief["image_candidates"]:
        die("brief の image_candidates が空（先に topic_plan.py images で候補を集める）")

    chain = resolve_for_args(args)
    prompt = build_prompt(brief)
    all_errs: list[str] = []

    for stage, model in enumerate(chain, 1):
        scratch = tempfile.mkdtemp(prefix="oc-generate-")
        try:
            rc, stdout, stderr = run_opencode(prompt, scratch, DEFAULT_TIMEOUT, model)
            art_path = os.path.join(scratch, "article.md")
            meta_path = os.path.join(scratch, "meta.json")
            tail = (stderr or "").strip().splitlines()
            detail = tail[-1] if tail else f"exit {rc}"
            if rc != 0:
                errs = [f"exit {rc}: {detail}"]
            elif not os.path.exists(art_path) or not os.path.exists(meta_path):
                files = sorted(os.listdir(scratch))
                snippet = extract_final_text(stdout)[-500:]
                errs = [f"生成物が無い（article.md / meta.json 未作成）: files={files} "
                        f"text_tail={snippet!r} stderr={detail}"]
            else:
                article = read_text(art_path).replace("\r\n", "\n")
                try:
                    meta = json.loads(strip_fences(read_text(meta_path)))
                except (json.JSONDecodeError, ValueError) as exc:
                    errs = [f"meta.json を解析できない: {exc}"]
                else:
                    if not isinstance(meta, dict):
                        errs = ["meta.json が JSON オブジェクトではない"]
                    else:
                        errs = validate(article, meta, brief)
                    if not errs:
                        enrich(meta, brief)
                        os.makedirs(os.path.dirname(os.path.abspath(args.article_out)), exist_ok=True)
                        with open(args.article_out, "w", encoding="utf-8", newline="\n") as fh:
                            fh.write(article.rstrip() + "\n")
                        with open(args.meta_out, "w", encoding="utf-8", newline="\n") as fh:
                            json.dump(meta, fh, ensure_ascii=False, indent=1)
                            fh.write("\n")
                        print(f"oc_generate: ok stage={stage}/{len(chain)} model={model} "
                              f"title={meta.get('title','')!r} figures={len(meta.get('figures',[]))} "
                              f"x={weighted_len(str(meta.get('x_post','')))}", file=sys.stderr)
                        return 0
                    if args.keep_raw:
                        os.makedirs(args.keep_raw, exist_ok=True)
                        shutil.copy2(art_path, os.path.join(args.keep_raw, "article.md"))
                        shutil.copy2(meta_path, os.path.join(args.keep_raw, "meta.json"))
                        print(f"oc_generate: raw output kept in {args.keep_raw} "
                              f"(stage {stage} model={model})", file=sys.stderr)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        all_errs.append(f"stage {stage} {model}: " + "; ".join(errs))
        next_model = chain[stage] if stage < len(chain) else "none"
        print(f"oc_generate: stage {stage}/{len(chain)} failed on {model}; "
              f"next={next_model}: " + "; ".join(errs), file=sys.stderr)

    die("all generate stages failed:\n  - " + "\n  - ".join(all_errs))


def cmd_text(args: argparse.Namespace) -> int:
    instruction = read_text(args.instruction).strip()
    if not instruction:
        die("instruction が空")
    chain = resolve_for_args(args)
    all_errs: list[str] = []

    for stage, model in enumerate(chain, 1):
        scratch = tempfile.mkdtemp(prefix="oc-generate-text-")
        try:
            rc, stdout, stderr = run_opencode(instruction, scratch, DEFAULT_TIMEOUT, model)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        text = extract_final_text(stdout)
        tail = (stderr or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit {rc}"
        if rc != 0:
            errs = [f"exit {rc}: {detail}"]
        elif not text:
            errs = [f"テキスト出力が空: {detail}"]
        else:
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text.rstrip() + "\n")
            else:
                print(text)
            print(f"oc_generate: text ok stage={stage}/{len(chain)} model={model}", file=sys.stderr)
            return 0

        all_errs.append(f"stage {stage} {model}: " + "; ".join(errs))
        next_model = chain[stage] if stage < len(chain) else "none"
        print(f"oc_generate: text stage {stage}/{len(chain)} failed on {model}; "
              f"next={next_model}: " + "; ".join(errs), file=sys.stderr)

    die("all text stages failed:\n  - " + "\n  - ".join(all_errs))


def extract_final_text(stdout: str) -> str:
    by_message: dict[str, list[str]] = {}
    order: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "text" and isinstance((event.get("part") or {}).get("text"), str):
            mid = event["part"].get("messageID") or "_"
            if mid not in by_message:
                by_message[mid] = []
                order.append(mid)
            by_message[mid].append(event["part"]["text"])
    return "\n".join(by_message[order[-1]]).strip() if order else ""


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Generate blog content with opencode (4-stage model chain)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("article", help="write article.md + meta.json from a brief")
    a.add_argument("--brief", required=True)
    a.add_argument("--article-out", required=True)
    a.add_argument("--meta-out", required=True)
    a.add_argument("--keep-raw", help="copy raw article.md/meta.json here if validation fails")
    a.add_argument("--model", help="pin one provider/model#variant instead of the 4-stage chain")
    a.add_argument("--models", help="semicolon/comma separated model chain override (stage 1 first)")
    a.set_defaults(func=cmd_article)

    t = sub.add_parser("text", help="return the model's final text (e.g. fix an X post)")
    t.add_argument("--instruction", required=True)
    t.add_argument("--out")
    t.add_argument("--model", help="pin one provider/model#variant instead of the 4-stage chain")
    t.add_argument("--models", help="semicolon/comma separated model chain override (stage 1 first)")
    t.set_defaults(func=cmd_text)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
