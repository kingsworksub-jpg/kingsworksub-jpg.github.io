# -*- coding: utf-8 -*-
"""Xへ送信するテキストのハードガード。

2026-11-23 の事故: 「次アクション（リンク配置をリプライ欄に誘導する実験）」を
LLMに渡したところ、アカウントの運用方針・プロジェクト設計をそのまま投稿してしまった。
内部の設計・自動化・実験は絶対に外部へ出さないための最終防壁。

使い方:
    from x_content_guard import find_unsafe_reasons
    reasons = find_unsafe_reasons(text, strict=True)  # 新規投稿は strict
    if reasons:  # 送信しない
        ...

strict=False（返信用）では、明確に内部設計を漏らす語のみを検査する。
strict=True（新規投稿用）では、さらに「SNS運用・表示数・アルゴリズム実験」系の
メタ投稿も禁止する。
"""
from __future__ import annotations

import re
from typing import Iterable

# どの経路でも絶対に出してはいけない内部情報。
INTERNAL_PATTERNS: list[tuple[str, str]] = [
    ("project_design", r"プロジェクトの設計|設計部分|このプロジェクト|本プロジェクト|内部設計|システム設計|アーキテクチャ"),
    ("automation", r"自動化|自動投稿|自動返信|ボット|botによる|スクリプトが|Pythonで|Playwright|opencode|Claude|Gemini|LLM|モデルチェーン"),
    ("pipeline", r"GitHub Pages|Hugo|AtomPub|はてな|note.com|ameba|供養|パイプライン|デプロイ|commit|コミット|レポジトリ|リポジトリ"),
    ("report", r"コンサルティングレポート|コンサルレポート|managed-limits|stat(e|us)\.json|KPI|ダッシュボード|モニタリング|計測して|追ってみる|追ってみます"),
    ("rule_tuning", r"ルール調整|ルール変更|上限を(引き上げ|引き下げ)|自動調整|投稿数上限|返信上限|いいね上限|hard cap|cooldown|policy_set"),
    ("confidential", r"次アクション|次アクションを実行|運営側|当アカウントの運用|我々の運用|我々の方針|我社の方針|弊社の方針|開発者|実装者"),
]

# 新規投稿でのみ追加するメタ投稿パターン。
# 「SNSの表示数が伸びないので運用方針を変えて実験しています」のような
# 内部施策のつぶやきを塞ぐ。一般読者向けの記事話題ならまず一致しない。
META_SNS_PATTERNS: list[tuple[str, str]] = [
    ("sns_meta", r"インプレッション|エンゲージメント|表示数|表示回数|リーチ|バズ|アルゴリズム|タイムライン"),
    ("sns_strategy", r"運用方針|運用ルール|投稿方針|投稿ルール|運用方法|投稿戦略|SNS運用|X運用|Twitter運用|アカウント運用"),
    ("experiment", r"テスト的に|実験的に|検証的に|試しに|切り替えて(います|みた|ました)|変更してみた|推移を(追う|見る|確認)|様子を見る"),
    ("link_strategy", r"リンク付き投稿|リンク配置|リンクの位置|リプライ欄|返信欄に|ツリー誘導|最初の返信に|本文にURL|ネイティブ完結|ハッシュタグを避け"),
]


def _compile(patterns: Iterable[tuple[str, str]], strict: bool) -> list[tuple[str, re.Pattern[str]]]:
    out = [(label, re.compile(pat, re.I)) for label, pat in patterns]
    if strict:
        out += [(label, re.compile(pat, re.I)) for label, pat in META_SNS_PATTERNS]
    return out


def find_unsafe_reasons(text: str, strict: bool = False) -> list[str]:
    """禁止語に一致したラベルを返す。空なら安全。"""
    if not text:
        return []
    reasons: list[str] = []
    for label, pat in _compile(INTERNAL_PATTERNS, strict):
        if pat.search(text):
            reasons.append(label)
    return sorted(set(reasons))


def is_safe(text: str, strict: bool = False) -> bool:
    return not find_unsafe_reasons(text, strict=strict)
