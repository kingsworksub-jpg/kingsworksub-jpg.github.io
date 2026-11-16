#!/usr/bin/env python
"""Research a blog topic with opencode (gemini-3.5-flash-lite).

This replaces the Claude Code research subagent for the posting job.  It is
read-only: opencode runs in a scratch directory, uses websearch/webfetch, and
returns one JSON object.  The caller (Claude Code) still decides whether to
accept the result, reject the topic, or fall back to the existing subagent.

Usage:
    python scripts/oc_research.py --theme "<theme>" --angle "<angle>" \
        --category gear --sources "https://...,https://..." \
        --out /tmp/<slug>-research.json
    python scripts/oc_research.py --brief /tmp/<slug>-brief.json --out ...

Exit code is 0 only when the returned JSON passes the checks below:
  - facts >= --min-facts (default 4) and sources_checked >= --min-sources (5)
  - every fact has an http(s) source_url
  - sources include an official source (--source-policy official; the default) or
    an official/reference source (--source-policy any, for culture topics)
  - source URLs are reachable (404/410/connection errors fail; bot blocks pass)
  - no Hangul / Cyrillic / Thai characters in any string (language mix guard)
On failure a diagnostic goes to stderr and the exit code is non-zero, so the
posting job can fall back to the Claude subagent or retry.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

MODEL = os.environ.get("OC_RESEARCH_MODEL", "google/gemini-3.5-flash-lite")
AGENT = "build"
DEFAULT_TIMEOUT = int(os.environ.get("OC_RESEARCH_TIMEOUT", "300"))
FALLBACK_EXE = r"C:\Users\norio\AppData\Roaming\npm\opencode.cmd"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG = os.path.join(REPO_ROOT, "scripts", "scheduled", "logs", "oc-research.log")
LANG_MIX = re.compile(r"[\u0400-\u04FF\u0E00-\u0E7F\uAC00-\uD7AF]")  # Cyrillic, Thai, Hangul

PROMPT = """\
あなたは日本語ブログ記事のリサーチャーです。websearch と webfetch を使って調査し、
結果を JSON 1個だけ返してください。ファイルの作成・編集・bash の実行はしないでください。

## 調べること
- テーマ: {theme}
- 切り口: {angle}
- カテゴリ: {category}
- 起点URL: {sources}
- 比較対象: {subjects}

## ルール
- 合計 {min_sources} サイト以上を調べる。英語圏の情報源を優先する。
- facts は {min_facts} 件以上（可能なら6件以上）作る。1つの事実につき1つの出典URLを付ける。
- {official_rule}
- 製品・人物・作品が実在し、現在の情報か（現行モデルか、生産終了していないか）を確認する。
- 数値（価格・寸法・発売日・スペック）は、出典URLがあるものだけ書く。
- 確認できなかった点は unverified に書く。推測で埋めない。空欄を恐れず、事実だけを書く。
- sources_checked には、実際に開けて内容を確認したURLだけを書く。
- type は official（メーカー・主催者の公式）、reference（Wikipedia・事典・公的機関）、review（レビュー）、news（ニュース）、other から選ぶ。
- 出力する文字列は日本語にする（製品名・URL・固有名詞の英字は可）。
- ハングル・キリル文字・タイ文字を混ぜない。
- JSON の前後に説明文やコードフェンスを付けない。

## 出力形式
{{
  "topic": "テーマ",
  "checked_at": "YYYY-MM-DD",
  "entities": [
    {{"name": "対象名", "status": "current|discontinued|unverified", "evidence_url": "https://..."}}
  ],
  "facts": [
    {{"claim": "出典に書かれている事実", "source_url": "https://...", "source_title": "サイト名"}}
  ],
  "numbers": [
    {{"item": "価格・寸法など", "value": "数値と単位", "source_url": "https://..."}}
  ],
  "unverified": ["確認できなかった点"],
  "sources_checked": [
    {{"url": "https://...", "title": "サイト名", "type": "official|review|news|other"}}
  ]
}}
"""


def die(msg: str) -> "NoReturn":
    print(f"oc_research: {msg}", file=sys.stderr)
    raise SystemExit(1)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


def log_event(path: str, msg: str) -> None:
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        stamp = dt.datetime.now().isoformat(timespec="seconds")
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"[{stamp}] {msg}\n")
    except OSError as exc:
        print(f"oc_research: log write failed: {exc}", file=sys.stderr)


def find_opencode() -> str:
    exe = shutil.which("opencode")
    if exe:
        return exe
    if os.path.exists(FALLBACK_EXE):
        return FALLBACK_EXE
    die("opencode CLI not found on PATH (looked for 'opencode' and " + FALLBACK_EXE + ")")


def run_opencode(prompt: str, cwd: str, timeout: int) -> tuple[int, str, str]:
    exe = find_opencode()
    # Pipe the prompt on stdin: the Windows opencode.CMD shim truncates a
    # multi-line argument at the first newline.
    cmd = [exe, "run", "--standalone", "--model", MODEL, "--agent", AGENT,
           "--auto", "--archived", "--format", "json", "--title", "blog research"]
    env = dict(os.environ)
    env["PWD"] = cwd
    env["OLDPWD"] = cwd
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, input=prompt, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        die(f"opencode timed out after {timeout}s")
    except OSError as exc:
        die(f"failed to launch opencode: {exc}")
    return proc.returncode, proc.stdout or "", proc.stderr or ""


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


def strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```[a-zA-Z0-9]*\s*\n(.*?)\n```$", text, re.S)
    return m.group(1).strip() if m else text


def extract_json(text: str) -> dict:
    text = strip_fences(text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("top-level JSON is not an object")
    return obj


def iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v)


def validate(obj: dict, min_facts: int, min_sources: int, source_policy: str) -> list[str]:
    errs: list[str] = []
    facts = obj.get("facts")
    sources = obj.get("sources_checked")
    if not isinstance(facts, list) or len(facts) < min_facts:
        errs.append(f"facts が {len(facts) if isinstance(facts, list) else 0} 件（{min_facts}件以上必要）")
    if not isinstance(sources, list) or len(sources) < min_sources:
        errs.append(f"sources_checked が {len(sources) if isinstance(sources, list) else 0} 件（{min_sources}件以上必要）")
    if isinstance(facts, list):
        for i, f in enumerate(facts, 1):
            if not isinstance(f, dict):
                errs.append(f"facts[{i}] がオブジェクトでない")
                continue
            url = str(f.get("source_url") or "")
            if not re.match(r"^https?://", url):
                errs.append(f"facts[{i}] に http(s) の source_url が無い")
            if not str(f.get("claim") or "").strip():
                errs.append(f"facts[{i}] の claim が空")
    if isinstance(sources, list):
        for i, s in enumerate(sources, 1):
            if not isinstance(s, dict) or not re.match(r"^https?://", str(s.get("url") or "")):
                errs.append(f"sources_checked[{i}] に http(s) の url が無い")
            elif s.get("type") not in ("official", "reference", "review", "news", "other"):
                errs.append(f"sources_checked[{i}] の type が不正: {s.get('type')!r}")
        allowed = ("official",) if source_policy == "official" else ("official", "reference")
        if not any(isinstance(s, dict) and s.get("type") in allowed for s in sources):
            errs.append(f"sources_checked に type={'/'.join(allowed)} が1件も無い")
    if not str(obj.get("topic") or "").strip():
        errs.append("topic が空")
    for text in iter_strings(obj):
        if LANG_MIX.search(text):
            errs.append(f"日本語以外の文字（ハングル・キリル・タイ）が混入: {text[:60]!r}")
            break
    return errs


def collect_urls(obj: dict) -> list[str]:
    urls: list[str] = []
    for s in obj.get("sources_checked") or []:
        if isinstance(s, dict) and isinstance(s.get("url"), str):
            urls.append(s["url"])
    for f in obj.get("facts") or []:
        if isinstance(f, dict) and isinstance(f.get("source_url"), str):
            urls.append(f["source_url"])
    for n in obj.get("numbers") or []:
        if isinstance(n, dict) and isinstance(n.get("source_url"), str):
            urls.append(n["source_url"])
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        u = u.strip().rstrip(".,);]")
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def check_urls(obj: dict, timeout: int = 12) -> list[str]:
    """Return hard failures only (404/410/connection error). Bot blocks are tolerated."""
    errs: list[str] = []
    for u in collect_urls(obj):
        req = urllib.request.Request(
            u, headers={"User-Agent": "Mozilla/5.0 (compatible; blog-research-check/1.0)",
                        "Range": "bytes=0-2048"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = getattr(resp, "status", 200)
            if code in (404, 410):
                errs.append(f"URL が {code}: {u}")
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                errs.append(f"URL が {exc.code}: {u}")
            # 401/403/405/407/429/5xx: bot block or login wall -> tolerate
        except Exception:
            errs.append(f"URL に接続できない: {u}")
    return errs


def build_prompt(args: argparse.Namespace) -> str:
    sources = ", ".join(args.sources) if args.sources else "なし（websearch で探す）"
    subjects = ", ".join(args.subjects) if args.subjects else "なし"
    if args.source_policy == "official":
        official_rule = "メーカー公式・主催者公式など、一次情報の公式サイトを必ず1つ含める。"
    else:
        official_rule = "公式サイトまたは一次資料（Wikipedia・公的機関・事典など）を必ず1つ含める。"
    return PROMPT.format(theme=args.theme, angle=args.angle or "指定なし",
                         category=args.category or "指定なし", sources=sources,
                         subjects=subjects, min_sources=args.min_sources,
                         min_facts=args.min_facts, official_rule=official_rule)


def research(args: argparse.Namespace) -> dict:
    prompt = build_prompt(args)
    last_errs: list[str] = []
    last_text = ""
    attempts = args.retries + 1
    log_event(args.log, f"start model={MODEL} policy={args.source_policy} "
                        f"min_facts={args.min_facts} min_sources={args.min_sources} "
                        f"sources={len(args.sources)} theme={args.theme!r} out={args.out}")
    for attempt in range(1, attempts + 1):
        scratch = tempfile.mkdtemp(prefix="oc-research-")
        try:
            rc, stdout, stderr = run_opencode(prompt, scratch, args.timeout)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        last_text = extract_final_text(stdout)
        if not last_text:
            tail = (stderr or "").strip().splitlines()
            last_errs = [f"出力が空（exit {rc}）: {tail[-1] if tail else 'no stderr'}"]
        else:
            try:
                obj = extract_json(last_text)
            except (json.JSONDecodeError, ValueError) as exc:
                last_errs = [f"JSON を解析できない: {exc}"]
            else:
                last_errs = validate(obj, args.min_facts, args.min_sources, args.source_policy)
                if not last_errs and args.check_urls:
                    last_errs = check_urls(obj)
                if not last_errs:
                    obj["model"] = MODEL
                    obj["researched_at"] = dt.datetime.now(
                        dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
                    nf, ns = len(obj.get("facts", [])), len(obj.get("sources_checked", []))
                    log_event(args.log, f"attempt {attempt}/{attempts} ok facts={nf} sources={ns}")
                    log_event(args.log, f"result=ok facts={nf} sources={ns}")
                    return obj
        log_event(args.log, f"attempt {attempt}/{attempts} fail: {'; '.join(last_errs)}")
        if attempt < attempts:
            print(f"oc_research: attempt {attempt}/{attempts} failed; retrying: {'; '.join(last_errs)}",
                  file=sys.stderr)
            prompt += ("\n\n## 前回の出力の問題（必ず直す）\n- "
                       + "\n- ".join(last_errs)
                       + f"\nJSON だけを返し直してください。facts は{args.min_facts}件以上必要です。\n")
    snippet = last_text[-400:].replace("\n", " ")
    log_event(args.log, f"result=fail after {attempts} attempts: {'; '.join(last_errs)}")
    die("research failed after retries:\n  - " + "\n  - ".join(last_errs)
        + f"\n  last_text={snippet!r}")


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Research a blog topic with opencode (gemini flash lite)")
    ap.add_argument("--brief", help="brief JSON with theme/angle/category/sources/subjects")
    ap.add_argument("--theme")
    ap.add_argument("--angle")
    ap.add_argument("--category")
    ap.add_argument("--sources", default="", help="comma-separated starting URLs")
    ap.add_argument("--subjects", default="", help="comma-separated comparison targets")
    ap.add_argument("--min-sources", type=int, default=5)
    ap.add_argument("--min-facts", type=int, default=4)
    ap.add_argument("--source-policy", choices=("official", "any"), default="official",
                    help="official: 公式サイト必須 / any: 公式または一次資料")
    ap.add_argument("--check-urls", dest="check_urls", action="store_true", default=True,
                    help="check source URLs and fail on 404/410/connection errors (default)")
    ap.add_argument("--no-check-urls", dest="check_urls", action="store_false")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--out", help="write JSON here instead of stdout")
    ap.add_argument("--log", default=DEFAULT_LOG, help="append run log here (default: scripts/scheduled/logs/oc-research.log)")
    ap.add_argument("--no-log", dest="log", action="store_const", const="", default=DEFAULT_LOG)
    args = ap.parse_args(argv)

    if args.brief:
        brief = json.loads(read_text(args.brief))
        args.theme = args.theme or brief.get("theme")
        args.angle = args.angle or brief.get("angle")
        args.category = args.category or brief.get("category")
        if not args.sources:
            args.sources = brief.get("sources") or []
        if not args.subjects:
            args.subjects = brief.get("subjects") or []
    if isinstance(args.sources, str):
        args.sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if isinstance(args.subjects, str):
        args.subjects = [s.strip() for s in args.subjects.split(",") if s.strip()]
    if not args.theme:
        die("--theme か --brief の theme が必要")

    obj = research(args)
    text = json.dumps(obj, ensure_ascii=False, indent=1) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print(f"oc_research: ok facts={len(obj.get('facts', []))} "
              f"sources={len(obj.get('sources_checked', []))} out={args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
