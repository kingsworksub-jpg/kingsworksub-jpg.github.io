# ブログの改善ループ(Solo Improvement Loop)

**目的**: ユーザーを待たずに、opencode(big-pickle)が単独で毎週回せるブログ改善サイクル。
**対象**: `C:\Users\norio\my-github-blog` のGitHub Pages側。(はてなブログは転載先として同期する場合のみ)

## 1周の手順

1. **監査実行**: `python scripts/seo-audit.py`(全リンク確認は `--check-links` 付き)
2. **結果を読む**: `scripts/seo-audit-report.md` を確認(記事サマリ/孤立/巨大画像/破損リンク/薄い記事)
3. **優先度ルールで対処を1つ決める**(上から順に、該当が無い場合は次へ):
   - **破損外部リンクが1件でもある** → リンク差し替え・削除(まずここ)
   - **孤立記事がある** → 関連記事から内部リンクを追加(＝トピッククラスタを形成)
   - **巨大画像(>250KB or 幅>1600px)が記事の本文画像にある** → `python scripts/compress-images.py` でその画像を再エンコード。**寸法が変わったら、記事内の `<img width height>` を一致させる**(CLS防止)
   - **文字数<1200 or 画像0の記事** → 1500字以上+関連画像入りに拡充、または既存記事へ統合/下書き化
   - **h2が少ない/見出しが無構造** → h2/h3で再構成
4. **適用**: `content/posts/*.md` と `static/images/**` を修正
5. **検証**: `hugo --minify` を実行 → 対象ページのHTMLでリンク・画像が正しいこと(`public/posts/<slug>/index.html`)を確認
6. **公開**: commit & push → GitHub Actionsの完了を `gh run list/watch` で確認 → 公開URLがHTTP 200
7. **記録**: 今周の結果を `scripts/seo-audit-report.md` の末尾ログに追記(日時・実施内容)

## ループ内のルール/注意

- 本文の改稿は原則やらない。ループで触るのは「構造・リンク・画像・見出し・文字数」。(本文リライトは単発の別タスク)
- 画像圧縮はJPEGのみ `quality=82`・`optimize`。PNGは格式変更しない(参照が壊れるため)。
- `hello.md`(定番ページ)や `draft: true` の記事は孤立判定から除外してよい判断をする。
- GA4/Search Console は現状API接続がないため使わない。将来 `google-analytics-data` 等の接続情報を用意できたら「実データ優先ルール」に差し替える。
- 記事の新規執筆は「お題待ち」が基本。ループが提案するのは「既存クラスタの補完記事のアウトライン案」まで(勝手に公開しない)。

## 理想の頻度

- **週1回**(新規記事ができた白はその記事の監査を必ず含める)
- 新しい記事が公開された直後にも1回走らせる(内部リンクは常時最新に)

## 今週(1周目・2026-09-24)の実施

- `scripts/seo-audit.py` 新規作成(UTF-8/BOM考慮・HTML `<img>`/`<a>` 対応・寸法チェック)
- ジャズ4記事(ハードバップ/モーダル/Alan Boguslavsky/ジャズシューズ)を相互に関連記事リンクで接続 → 孤立10→6
- `scripts/compress-images.py` 作成、本文画像9点を再エンコード(例:den-haag 989KB→220KB、bill-evans 1159KB→621KB) → 有名画像40→37
- hugoビルド確認OK
- 残タスク: 楽器ガイド5本(500〜800字・画像0)の拡充/統合、product画像の圧縮、hello.md の扱い、
  ジャズ以外カテゴリへ同様の相互リンク展開、Search Console連携(将来)