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
- **日本語記事は必ず frontmatter に `description:` を書く**(重要・2026-09-24発見)。日本語は空白が無いため Hugo の自動サマリーが本文を丸ごと返し、それが meta/og/twitter description と JSON-LD に複数回コピーされる。`description:` を明示すれば1行の要旨になる(SERP向けにも良い)。新規記事作成時は必ず記入する。
- 画像圧縮はJPEGのみ `quality=82`・`optimize`。PNGは形式変更しない(参照が壊れるため)。`compress-images.py` は全画像を走査し、小型化できたものだけ置換する。
- 画像素材はWikimedia Commonsを基本としつつ、**Web上のどのサイトからも取得してよい**(ユーザー指示・2026-09-24)。出典クレジット(撮影者・ライセンス・出典)は `<span class="credit">` に必ず記載。`scripts/commons-search.py` が候補検索+ダウンロード(CCライセンスのみ・クレジット情報出力)を支援。
- **一つのテーマで内容が重複する薄い記事は、1本の充実記事に統合し、旧記事は frontmatter の `draft: true` にする**(または`aliases`で旧URLを新記事へリダイレクト)。下書き化は git で復元可能なので安全。
- `draft: true` はセクションレベルの `cascade` では効かない(実測・2026-09-24)。**各ファイルの frontmatter に直接書く**こと。
- **不要になった記事セクション(`content/old_posts` 等)は放置すると sitemap・検索インデックスに永久に残る**。チェック手段: `public/sitemap.xml` と `public/index.json` に想定外のURLが無いか確認する。
- `hello.md`(定番ページ)や `draft: true` の記事は孤立判定から除外してよい判断をする。
- GA4/Search Console は現状API接続がないため使わない。将来 `google-analytics-data` 等の接続情報を用意できたら「実データ優先ルール」に差し替える。
- 記事の新規執筆は「お題待ち」が基本。ループが提案するのは「既存クラスタの補完記事のアウトライン案」まで(勝手に公開しない)。

## 理想の頻度

- **週1回**(新規記事ができたらその記事の監査を必ず含める)
- 新しい記事が公開された直後にも1回走らせる(内部リンクは常時最新に)

## 今週済み(1周目・2026-09-24)

- `scripts/seo-audit.py` 新規作成(UTF-8/BOM考慮・HTML `<img>`/`<a>` 対応・寸法チェック)
- ジャズ4記事(ハードバップ/モーダル/Alan Boguslavsky/ジャズシューズ)を相互に関連記事リンクで接続 → 孤立10→6
- `scripts/compress-images.py` 作成、本文画像9点を再エンコード(例: den-haag 989KB→220KB、bill-evans 1159KB→621KB) → 巨大画像40→37
- hugoビルド確認OK
- 残タスク: 楽器ガイド5本の拡充/統合、product画像の圧縮、hello.mdの扱い、Search Console連携(将来)

## 2周目(2026-09-24)

- **薄い楽器ガイド5本(重複+誤情報)を1本に統合** → `content/posts/jazz-instruments-guide.md` を新設(4枚のCC画像付き・各楽器のh2構成・関連記事4本・`aliases`で旧5URLをリダイレクト)。旧5本は `draft: true`
- **`content/old_posts` 65ページ+`content/test.md` を非公開化**(sitemap 294→44 URL、検索インデックスから旧セクション/テスト記事を除去)。理由: `old_posts`=アーカイブ意図、`/test/`=放置テスト記事
- **meta description 問題を修正**: 全6記事に `description:` を追加(日本語自動サマリーが本文を丸ごとmeta/og/twitterに複数コピーしていた)、`hugo.toml` のサイト説明も現在の音楽ブログ内容に更新
- **画像圧縮を全画像対象に拡張**: `compress-images.py` を自走査+小型化優先へアップグレード。46枚を圧縮して1.5MB削減、6枚(2000px超)を1600pxへ縮小(参照属性なしで安全・確認済み)
- **新ツール**: `scripts/commons-search.py`(Wikimedia Commons検索+CC画像DL・クレジット出力)
- 監査結果: posts=6 / orphans=1(hello.mdのみ・許容) / big_images=27 / broken=0
- 残タスク: product画像(static/images/products)の整理、`hello.md` から孤孤立解除する場合は関連記事へ追加、Search Console 連携、old_posts の画像ディレクトリ整理(数ラウンド後)

## 3周目(2026-09-24)

- **クラスタの「要(hub)」記事を新規執筆**: `content/posts/jazz-masterpieces-beginner.md`「はじめてのジャズ名盤 — 最初に聴くべき10枚を時代順に」。1925-28のアームストロングから1965のA Love Supremeまで時代順に10枚を案内し、既存記事(ハードバップ/モーダル/楽器ガイド)へ多数の内部リンクを張ってクラスタ全体を強化
- **hubへの被リンクを一気に増強**: 既存5記事(ハードバップ/モーダル/楽器ガイド/Alan/ジャズシューズ)の「関連記事」末尾に新記事へのリンクを1本ずつ追加。クラスタの相互リンクが完全な網になる(6記事すべてが互いに繋がる)
- 画像4点(Wikimedia Commons)を取得・圧縮: アームストロング(VoA/PD)、エリントン(PD)、ビル・エヴァンス 1961(Steve Schapiro/PD)、コルトレーン 1963(Hugo van Gelderen/CC0)。いずれも width/height/alt/lazy + `<span class="credit">` 付き。大型3枚を q70+1200px リサイズで 280→127KB / 621→214KB / 371→197KB に削減
- **学び(新)**: `hugo.toml` に `buildFuture = false` があるため、**未来日時の `date` を書いた記事はビルドされても public に出力されず、ローカルと本番の両方で「消えた」ように見える**(ビルドは成功し sitemap にも出ない)。新規記事の `date` は必ず現在時刻以前にする。`hugo list all` で published 扱いなのに public に出ない場合はまず date を疑う
- 監査結果: posts=7 / orphans=1 / big_images=27 / broken=0(楽器ガイドのはてな転載も実施し、CLAUDE.md のはてな投稿テーブルへ追記)
- 残タスク: product画像の整理、Search Console 連携、次はジャズ以外カテゴリのクラスタ形成