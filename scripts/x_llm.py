# -*- coding: utf-8 -*-
"""x-following-reply.py 用のLLM呼び出し層。

モデルは次の順でフォールバックする（すべて失敗/空なら None）:
  1. opencode / google/gemini-3.5-flash-lite   （メイン）
  2. opencode / opencode/longcat-2.5-free     （フォールバック1・無料）
  3. claude code / haiku                       （フォールバック2）

opencode の CLI は1回の呼び出しごとにシステムプロンプト（実測で約8kトークン）を
運ぶため、1投稿ずつ呼ぶと起動オーバーヘッドが支配的になる。そこで複数の候補ツイートを
1回の呼び出しにまとめて処理する（バッチ生成）。これでモデル単価の差はそのままで、
固定費を1/バッチサイズに摊薄できる。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OPENCODE_FALLBACK_EXE = r"C:\Users\norio\AppData\Roaming\npm\opencode.cmd"
CLAUDE_EXE = r"C:\Users\norio\AppData\Local\Microsoft\WinGet\Links\claude.exe"

# 試行順。engine は "opencode" または "claude"。
MODEL_CHAIN = [
    {"name": "gemini-3.5-flash-lite", "engine": "opencode", "model": "google/gemini-3.5-flash-lite"},
    {"name": "longcat-2.5-free", "engine": "opencode", "model": "opencode/longcat-2.5-free"},
    {"name": "claude-haiku", "engine": "claude", "model": "haiku"},
]

TIMEOUT = int(os.environ.get("X_LLM_TIMEOUT", "180"))
AGENT = "build"


def find_opencode() -> str:
    exe = shutil.which("opencode")
    if exe:
        return exe
    if os.path.exists(OPENCODE_FALLBACK_EXE):
        return OPENCODE_FALLBACK_EXE
    return ""


def kill_tree(proc: subprocess.Popen) -> None:
    """opencode は .CMD シム経由で node を起こすため、プロセスツリーごと落とす。"""
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


def extract_final_text(stdout: str) -> str:
    """opencode --format json のストリームから、最後のテキストパートを抜き出す。"""
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
        part = event.get("part") or {}
        if event.get("type") == "text" and isinstance(part.get("text"), str):
            mid = part.get("messageID") or "_"
            if mid not in by_message:
                by_message[mid] = []
                order.append(mid)
            by_message[mid].append(part["text"])
    return "\n".join(by_message[order[-1]]).strip() if order else ""


def run_opencode(prompt: str, model: str, timeout: int = TIMEOUT) -> tuple[bool, str]:
    exe = find_opencode()
    if not exe:
        return False, "opencode CLI が見つからない"
    scratch = tempfile.mkdtemp(prefix="x-llm-")
    cmd = [exe, "run", "--standalone", "--model", model, "--agent", AGENT, "--auto",
           "--archived", "--format", "json", "--title", "x-following-reply"]
    env = dict(os.environ)
    env["PWD"] = scratch
    env["OLDPWD"] = scratch
    try:
        proc = subprocess.Popen(cmd, cwd=scratch, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                encoding="utf-8", errors="replace",
                                start_new_session=(os.name != "nt"))
    except OSError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        return False, f"opencode 起動失敗: {exc}"
    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(scratch, ignore_errors=True)
        return False, f"opencode ({model}) が {timeout}s でタイムアウト"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if proc.returncode != 0:
        tail = (stderr or "").strip().splitlines()
        return False, f"opencode ({model}) exit {proc.returncode}: {tail[-1] if tail else 'no stderr'}"
    text = extract_final_text(stdout or "")
    return (bool(text), text or "出力が空")


def run_claude(prompt: str, model: str = "haiku", timeout: int = TIMEOUT) -> tuple[bool, str]:
    if not os.path.exists(CLAUDE_EXE):
        return False, f"claude CLI が見つからない: {CLAUDE_EXE}"
    cmd = [CLAUDE_EXE, "-p", prompt, "--model", model, "--permission-mode", "auto",
           "--no-session-persistence"]
    try:
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=timeout,
                              cwd=BASE)
    except subprocess.TimeoutExpired:
        return False, f"claude ({model}) が {timeout}s でタイムアウト"
    except OSError as exc:
        return False, f"claude 起動失敗: {exc}"
    text = (proc.stdout or "").strip()
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        return False, f"claude ({model}) exit {proc.returncode}: {tail[-1] if tail else 'no stderr'}"
    return (bool(text), text)


def build_prompt(items: list[dict]) -> str:
    """items: [{id, author, text, topic, context}] を1つのプロンプトにまとめる。"""
    lines = ["あなたはX(Twitter)で自然に交流する一般のユーザーです。",
             "以下の各ツイートに対して、返信文を1つずつ作成してください。",
             "",
             "【絶対の禁止事項】",
             "- ツイートの文章・フレーズ・イベント名・固有名詞を「そのまま繰り返す」ことは禁止です。",
             "  話題の本質や自分の視点だけを書き、相手の言葉をなぞらないでください。",
             "- 定型文・お世辞・中身のない抽象的な褒め言葉（「勉強になります」「さすがですね」「〜の深さを感じます」等）は禁止。",
             "- ハッシュタグは付けない。絵文字は0〜1個。",
             "",
             "【品質】",
             "- 相手が「お、この人わかってるな」と思う考察、共感の理由、あるいは一言の意見をさりげなく添える。",
             "- 丁寧語（です・ます調）で、爽やかで嫌味のないトーン。",
             "- 1件あたり60〜110文字。",
             "- 本文から確認できない固有の事実（年代・製作者・背景など）を断定しない。推測は「〜のように思います」と柔らかく。",
             "- 返信本文だけで、余計な解説や引用符（「」）は付けない。",
             "- 補足に会話の履歴（元の投稿→自分の返信→相手の返信）がある場合は、その流れに沿って返す。",
             "",
             "【返信しない判断】",
             "- 宣伝・告知・イベントのお知らせ、文脈が掴めない投稿は無理に返信しない。",
             "  その場合は値に null を入れてください（例: {\"replies\": {\"123\": null}}）。",
             "",
             "【出力形式】次のJSONだけを出力する（コードフェンスで囲む）:",
             '{"replies": {"<id>": "<返信文>", "...": "..."}}',
             "",
             "【ツイート一覧】"]
    for it in items:
        lines.append(f"id: {it['id']}")
        lines.append(f"投稿者: @{it['author']}")
        lines.append(f"トピック: {it.get('topic') or '未分類'}")
        if it.get("context"):
            lines.append(f"補足: {it['context']}")
        lines.append(f"本文: {it['text']}")
        lines.append("")
    return "\n".join(lines)


def parse_replies(text: str, keep_empty: bool = False) -> dict[str, str]:
    """モデル出力から {id: 返信文} を取り出す。JSON崩れにも部分的に耐える。
    keep_empty=True のとき、モデルが明示的に null（=返信不要）にした id も
    空文字として残す（「解析失敗」と「返信不要の判断」を区別するため）。"""
    if not text:
        return {}
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [m.group(1)] if m else []
    candidates.append(text)
    for cand in candidates:
        try:
            data = json.loads(cand)
            reps = data.get("replies") if isinstance(data, dict) else None
            if isinstance(reps, dict) and reps:
                out = {}
                for k, v in reps.items():
                    v = (v or "").strip().strip('"').strip("'")
                    if v or keep_empty:
                        out[str(k)] = v
                if out:
                    return out
        except (json.JSONDecodeError, AttributeError):
            continue
    # 崩れたJSONの保険: "id": "text" を正規表現で拾う
    out = {}
    for k, v in re.findall(r'"(\d{5,})"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
        v = v.replace('\\"', '"').replace("\\n", " ").strip()
        if v:
            out[k] = v
    return out


def generate_replies(items: list[dict]) -> tuple[dict[str, str], list[str], set[str]]:
    """バッチ生成。戻り値は (生成できた {id: 返信文}, 試行ログ, 返信不要と判断した id 集合)。"""
    if not items:
        return {}, [], set()
    prompt = build_prompt(items)
    log: list[str] = []
    for spec in MODEL_CHAIN:
        if spec["engine"] == "opencode":
            ok, payload = run_opencode(prompt, spec["model"])
        else:
            ok, payload = run_claude(prompt, spec["model"])
        if not ok:
            log.append(f"[!] {spec['name']}: {payload}")
            continue
        parsed = parse_replies(payload, keep_empty=True)
        if parsed:
            replies = {k: v for k, v in parsed.items() if v}
            declined = {k for k, v in parsed.items() if not v}
            log.append(f"[✓] {spec['name']}: {len(replies)}件生成"
                       + (f" / {len(declined)}件は返信不要と判断" if declined else ""))
            return replies, log, declined
        log.append(f"[!] {spec['name']}: 出力を解析できず（フォールバック）")
    return {}, log, set()
