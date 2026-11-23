# -*- coding: utf-8 -*-
"""X 系ジョブ用のLLM呼び出し層（返信・お礼DMの本文生成）。

モデルは次の順でフォールバックする（すべて失敗/空なら空の dict）:
  1. opencode / google/gemini-3.5-flash-lite   （メイン）
  2. opencode / opencode/longcat-2.5-free     （フォールバック1・無料）
  3. opencode / opencode/iceman-free          （フォールバック2・無料）
  4. opencode / opencode/flint-40b-free       （フォールバック3・無料）

opencode の CLI は1回の呼び出しごとにシステムプロンプト（実測で約8kトークン）を
運ぶため、1投稿ずつ呼ぶと起動オーバーヘッドが支配的になる。そこで複数の候補ツイートを
1回の呼び出しにまとめて処理する（バッチ生成）。これでモデル単価の差はそのままで、
固定費を1/バッチサイズに抑えられる。

Claude は使わない（クレジット消費を避けるため、すべて無料枠の opencode 経由モデル）。
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

# 試行順。engine は "opencode"。すべて無料枠（OpenCode標準）で動作します。
# Claudeはクレジットが必要なため削除し、OpenCode内の無料モデルで代用します。
MODEL_CHAIN = [
    {"name": "gemini-3.5-flash-lite", "engine": "opencode", "model": "google/gemini-3.5-flash-lite"},
    {"name": "longcat-2.5-free", "engine": "opencode", "model": "opencode/longcat-2.5-free"},
    {"name": "iceman-free", "engine": "opencode", "model": "opencode/iceman-free"},
    {"name": "flint-40b-free", "engine": "opencode", "model": "opencode/flint-40b-free"},
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


def build_mention_prompt(items: list[dict]) -> str:
    """自分の投稿への返信に対する返信文を、複数件まとめて生成するプロンプト。

    items: [{id, author, text, topic, context}]（topic/context は任意）
    x-following-reply.py からも同じ関数が使われるため、キーは "replies" のまま。
    """
    lines = ["あなたはX(Twitter)で自然に交流する一般のユーザーです。",
             "以下はあなたの投稿に届いた返信です。各返信に対する返信文を1つずつ作成してください。",
             "",
             "【絶対の禁止事項】",
             "- 相手の文章・フレーズ・固有名詞をそのまま繰り返すのは禁止です。",
             "  話題の本質や自分の視点だけを書き、相手の言葉をなぞらないでください。",
             "- 定型文・お世辞・中身のない抽象的な褒め言葉（「勉強になります」「さすがですね」等）は禁止。",
             "- 煽り・誇張・中傷は禁止。ハッシュタグやリンクは付けない。絵文字は0〜1個。",
             "",
             "【品質】",
             "- 質問には具体的に答える、感想には短く反応する、程度でよい。",
             "- 相手が「お、この人わかってるな」と思う一言の意見や共感の理由を添える。",
             "- 丁寧語（です・ます調）で、爽やかで嫌味のないトーン。",
             "- 返信元の言語に合わせる（日本語の投稿には日本語、明らかに英語なら英語）。",
             "- 1件あたり50〜100字程度。Xの280字加重カウント（全角2字分）を超えない。",
             "- 本文から確認できない固有の事実（年代・製作者・背景など）を断定しない。",
             "- 返信本文だけで、余計な解説や引用符（「」）は付けない。",
             "- 補足に会話の履歴がある場合は、その流れに沿って返す。",
             "",
             "【返信しない判断】",
             "- 宣伝・スパム・荒らし・中傷・意味のない文字列・文脈が掴めない投稿は無理に返信しない。",
             "  その場合は値に null を入れてください（例: {\"replies\": {\"123\": null}}）。",
             "",
             "【出力形式】次のJSONだけを出力する（コードフェンスで囲む）:",
             '{"replies": {"<id>": "<返信文>", "...": "..."}}',
             "",
             "【返信一覧】"]
    for it in items:
        lines.append(f"id: {it['id']}")
        lines.append(f"投稿者: @{it['author']}")
        if it.get("topic"):
            lines.append(f"トピック: {it['topic']}")
        if it.get("context"):
            lines.append(f"補足: {it['context']}")
        lines.append(f"本文: {it['text']}")
        lines.append("")
    return "\n".join(lines)


# 既存呼び出し（x-following-reply.py）互換の別名。
build_prompt = build_mention_prompt


def build_welcome_prompt(items: list[dict]) -> str:
    """新規フォロワーへのお礼DMを複数件まとめて生成するプロンプト。

    items: [{handle, name}]。キーは "dms"。スパム/ボットは null を返させる。
    """
    lines = ["あなたはX(Twitter)のアカウント運用者です。",
             "以下は新しくフォローしてくれたユーザーです。各人へのお礼DM文を1つずつ作成してください。",
             "",
             "【文体のルール】",
             "- 爽やか・丁寧・軽やかを最優先し、相手に重さや義務感を与えない。",
             "- 1〜2文・30〜50字程度。敬体（です・ます）で書く。",
             "- フォローへの感謝＋相手の投稿を楽しみにしている等の軽い一言。",
             "- 絵文字は0〜1個。煽り・誇張は禁止。",
             "",
             "【避ける表現】",
             "- 「これからよろしくお願いします」「今後ともよろしくお願いいたします」",
             "  「末永くよろしくお願いします」「ぜひ仲良くしてください」など、",
             "  今後の関係の継続を強く求める挨拶は禁止（初対面に重く構えさせるため）。",
             "- 自分語り・宣伝・リンク・返信を促す質問は禁止。",
             "",
             "【言語】",
             "- 原則日本語（このアカウントの主な読者層は日本語）。",
             "- 表示名やハンドルが明らかに英語圏のものだけ英語で書く。",
             "",
             "【スキップ判断】",
             "- 表示名やハンドルが明らかにスパム・ボット・詐欺的（暗号資産勧誘、",
             "  意味不明な文字列の羅列、出会い系など）に見える場合はDMを作らず null を入れる。",
             "  例: {\"dms\": {\"spam_account\": null}}",
             "",
             "【出力形式】次のJSONだけを出力する（コードフェンスで囲む）:",
             '{"dms": {"<handle>": "<DM文>", "...": "..."}}',
             "",
             "【フォロワー一覧】"]
    for it in items:
        lines.append(f"handle: {it['handle']}")
        lines.append(f"表示名: {it.get('name') or it['handle']}")
        lines.append("")
    return "\n".join(lines)


def parse_keyed(text: str, key: str, keep_empty: bool = False) -> dict[str, str]:
    """モデル出力から {id: 本文} を取り出す。JSON崩れにも部分的に耐える。

    keep_empty=True のとき、モデルが明示的に null（=対象外と判断）にした id も
    空文字として残す（「解析失敗」と「スキップ判断」を区別するため）。
    """
    if not text:
        return {}
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [m.group(1)] if m else []
    candidates.append(text)
    for cand in candidates:
        try:
            data = json.loads(cand)
            reps = data.get(key) if isinstance(data, dict) else None
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
    pattern = r'"(\d{5,}|[A-Za-z0-9_]{1,15})"\s*:\s*"((?:[^"\\]|\\.)*)"'
    for k, v in re.findall(pattern, text):
        v = v.replace('\\"', '"').replace("\\n", " ").strip()
        if v:
            out[k] = v
    return out


def parse_replies(text: str, keep_empty: bool = False) -> dict[str, str]:
    """既存互換のラッパー。モデル出力から {id: 返信文} を取り出す。"""
    return parse_keyed(text, "replies", keep_empty)


def parse_json_object(text: str) -> dict | None:
    """モデル出力から最初のJSONオブジェクトを取り出す（コードフェンス耐性あり）。"""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [m.group(1)] if m else []
    candidates.append(text)
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def generate_json(prompt: str, label: str = "json") -> tuple[dict | None, list[str], str]:
    """MODEL_CHAIN を順に試し、最初に得られたJSONオブジェクトを返す。

    戻り値: (obj, 試行ログ, 採用モデル名)。全滅時は (None, log, "")。
    投稿文・リンク判断など、構造化出力が必要な自動改善処理で使う。
    """
    log: list[str] = []
    for spec in MODEL_CHAIN:
        ok, payload = run_opencode(prompt, spec["model"])
        if not ok:
            log.append(f"[!] {spec['name']}: {payload}")
            continue
        obj = parse_json_object(payload)
        if obj:
            log.append(f"[✓] {spec['name']}: {label}生成")
            return obj, log, spec["name"]
        log.append(f"[!] {spec['name']}: JSONを解析できず（フォールバック）")
    return None, log, ""


def _generate_keyed(prompt: str, key: str, label: str) -> tuple[dict[str, str], list[str], set[str]]:
    """MODEL_CHAIN を順に試し、(生成物, 試行ログ, スキップと判断した id) を返す。"""
    log: list[str] = []
    for spec in MODEL_CHAIN:
        ok, payload = run_opencode(prompt, spec["model"])
        if not ok:
            log.append(f"[!] {spec['name']}: {payload}")
            continue
        parsed = parse_keyed(payload, key, keep_empty=True)
        if parsed:
            generated = {k: v for k, v in parsed.items() if v}
            declined = {k for k, v in parsed.items() if not v}
            log.append(f"[✓] {spec['name']}: {len(generated)}件{label}生成"
                       + (f" / {len(declined)}件はスキップと判断" if declined else ""))
            return generated, log, declined
        log.append(f"[!] {spec['name']}: 出力を解析できず（フォールバック）")
    return {}, log, set()


def generate_mention_replies(items: list[dict]) -> tuple[dict[str, str], list[str], set[str]]:
    """X返信用のバッチ生成。戻り値は ({id: 返信文}, 試行ログ, スキップした id)。"""
    if not items:
        return {}, [], set()
    return _generate_keyed(build_mention_prompt(items), "replies", "返信")


def generate_replies(items: list[dict]) -> tuple[dict[str, str], list[str], set[str]]:
    """x-following-reply.py 用の互換API（generate_mention_replies と同じ）"""
    return generate_mention_replies(items)


def generate_welcome_dms(items: list[dict]) -> tuple[dict[str, str], list[str], set[str]]:
    """お礼DM用のバッチ生成。戻り値は ({handle: DM文}, 試行ログ, スキップした handle)。"""
    if not items:
        return {}, [], set()
    return _generate_keyed(build_welcome_prompt(items), "dms", "DM")
