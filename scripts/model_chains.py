"""Shared 4-stage opencode model chains for the blog LLM jobs.

Each chain is ordered by safety for its role.  big-pickle is deliberately absent
from article/research chains because of the 2026-10-02 mixed-language and false
completion incident.  It remains stage 1 only for topic planning (set in
scripts/scheduled/register-tasks.ps1).

Override a whole chain with <PREFIX>_MODEL_CHAIN (semicolon- or comma-separated),
or just stage 1 with <PREFIX>_MODEL / --model at the call site.
"""
from __future__ import annotations

import os
import re

# Blog-post orchestration: needs long instruction following and git/publishing steps.
POST_ORCHESTRATION_CHAIN = [
    "google/gemini-3.5-flash#high",
    "google/gemini-3.5-flash-lite",
    "opencode/deepseek-v4.1-flash-free",
    "opencode/longcat-2.5-free",
]

# Topic meeting / top-up: big-pickle stays first, then safer Gemini/deepseek models.
TOPIC_CHAIN = [
    "opencode/big-pickle",
    "google/gemini-3.5-flash-lite",
    "google/gemini-3.5-flash#high",
    "opencode/deepseek-v4.1-flash-free",
]

# Read-only web research: no big-pickle, no vision-only or tiny free models.
RESEARCH_CHAIN = [
    "google/gemini-3.5-flash-lite",
    "google/gemini-3.5-flash#high",
    "opencode/deepseek-v4.1-flash-free",
    "opencode/longcat-2.5-free",
]

# Article body / title / frontmatter / X post text: generate-only, validated by oc_generate.py.
GENERATE_CHAIN = [
    "google/gemini-3.5-flash-lite",
    "opencode/deepseek-v4.1-flash-free",
    "google/gemini-3.5-flash#high",
    "opencode/longcat-2.5-free",
]


def split_models(value: str | None) -> list[str]:
    """Split a semicolon/comma separated model list, dropping empty entries."""
    if not value:
        return []
    return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]


def resolve_chain(defaults: list[str], chain_env: str, primary_env: str | None = None,
                  primary_override: str | None = None) -> list[str]:
    """Return the model chain to try, honouring env overrides.

    `chain_env` replaces the whole chain; `primary_env` / `primary_override`
    only replace stage 1 and keep the remaining defaults as fallbacks.
    """
    configured = split_models(os.environ.get(chain_env))
    chain = configured or list(defaults)
    primary = primary_override or (os.environ.get(primary_env) if primary_env else None)
    if primary:
        # Move an existing model to stage 1, or replace stage 1 with a new one.
        # Dedupe so a single model is never tried twice in the same chain.
        chain = [primary] + [m for m in chain if m != primary][:len(chain) - 1]
    return chain or list(defaults)
