"""Call the Claude Code CLI (non-interactive) to summarize an article and
produce 3 candidate X post texts, picking the most natural one.

Uses `claude -p --output-format json --json-schema ...` with structured
output. We pin the model to haiku for cost (a $0.27-0.37/call cost was
observed with the default Sonnet model + extended thinking; haiku runs
~$0.05/call with comparable quality for this summarize-and-pick task).
"""

from __future__ import annotations

import json
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

MODEL = "claude-haiku-4-5-20251001"
MAX_BUDGET_USD = "0.30"

SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "candidates": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
        },
        "chosen_index": {"type": "integer", "minimum": 0, "maximum": 2},
    },
    "required": ["summary", "candidates", "chosen_index"],
})


def build_prompt(title: str, body_text: str) -> str:
    # Body is truncated defensively; Hatena articles run long and we only need
    # enough content for a faithful summary, not the whole thing verbatim.
    excerpt = body_text[:4000]
    return (
        "次のブログ記事の要約(100文字程度)と、X(旧Twitter)投稿用の文章を3パターン"
        "(それぞれ80文字以内、絵文字なし、記事URLは含めない)作ってください。"
        "3パターンの中で一番自然で読みたくなる文章をchosen_indexで選んでください(0始まり)。\n\n"
        "重要: 投稿文は、筆者本人が自分の記事を人力で紹介しているかのような、自然な一人称の文章にすること。"
        "「テスト」「自動投稿」「AI」「bot」「生成」など、機械的・自動化を連想させる語は一切使わないこと。\n\n"
        f"記事タイトル: {title}\n\n"
        f"記事本文:\n{excerpt}"
    )


class GenerationError(RuntimeError):
    pass


def generate(title: str, body_text: str) -> dict:
    """Return {"summary": str, "candidates": [str, str, str], "chosen_index": int}."""
    prompt = build_prompt(title, body_text)
    result = subprocess.run(
        [
            "claude", "-p",
            "--output-format", "json",
            "--json-schema", SCHEMA,
            "--model", MODEL,
            "--max-budget-usd", MAX_BUDGET_USD,
            "--", prompt,
        ],
        capture_output=True,
        encoding="utf-8",
        timeout=120,
    )
    if result.returncode != 0:
        raise GenerationError(f"claude CLI exited {result.returncode}: {result.stderr}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise GenerationError(f"claude CLI returned non-JSON output: {result.stdout[:500]}") from e

    if payload.get("is_error"):
        raise GenerationError(f"claude CLI reported an error: {payload}")

    structured = payload.get("structured_output")
    if not structured:
        raise GenerationError(f"claude CLI did not return structured_output: {payload.get('result')}")

    candidates = structured.get("candidates") or []
    if len(candidates) != 3:
        raise GenerationError(f"expected 3 candidates, got {len(candidates)}: {structured}")

    return structured


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python generate.py <title> <body_text_file>")
        raise SystemExit(1)
    title = sys.argv[1]
    with open(sys.argv[2], encoding="utf-8") as f:
        body = f.read()
    out = generate(title, body)
    print(json.dumps(out, ensure_ascii=False, indent=2))
