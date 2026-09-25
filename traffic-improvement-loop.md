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

## 3周目(フォロー・2026-09-24) — old_posts のアーカイブを取り消し

- ユーザー指摘: 「過去の機材レビュー記事がごっそり消えた」。原因は2周目に実施した `content/old_posts`(65記事+セクション)の一括 draft 化。フォルダ名だけで「アーカイブ済み」と判断したのは誤りで、これらのレビュー記事(DAW/機材/飲料/酒器/ウイスキーなど)は公開中の価値あるコンテンツだった
- **対応**: frontmatter を一括で `draft: true` → `draft: false` に戻し、再ビルド・sitemap 復帰(298 URL)を確認。`content/test.md`(タダのテスト記事)のみ引き続き非公開
- **教訓(重要)**: **コンテンツの公開停止(アーカイブ化・draft化)はフォルダ名やメタデータだけで判断せず、必ずユーザー確認を取る**。SEOループは「孤立リンク・画像・構造」の改善に限定し、既存ページの可視性変更はユーザー承認待ちにする
- 今後は: 旧記事を圧縮・相互リンク・統合(下書き化ではなく新記事導線化)で扱い、draft 化はユーザーが明示的に依頼した場合のみ

## 一括レイアウト整形(2026-09-25) — old_posts 新聞スタイル画像化

- ユーザー依頼: 「過去の飲料・機材レビュー記事など全部含めて、アマゾンアソシエイトリンクごと、新聞のように画像へ文字が回り込むレイアウトに」
- **対応**: `content/old_posts` 全65記事の `<a class="product-banner">` 166個(固定468px・非回り込み)を `<figure class="photo photo--left|right">` + アフィリエイトリンク付きfigcaption(商品名 + `Amazonで見る →` の credit リンク)へ機械変換。左右を記事内で交互配置
- 全 `<img>` に intrinsic width/height + loading="lazy" を付与し、実寸と同期
- 商品画像82個のうち大容量30個を256色パレット量子化+最大1200px化で圧縮(約7.5MB削減、1枚表示でも軽量化)
- **1行10文字ルールの検証**: 本文領域720px − 220px×2 − 余白24px×4 = 対向画像間232px(≥180px) / 単一回り込み時476px → 両条件で「1行10文字以上」を充足
- 残タスク: 未実施の画像はバナー転換のみで本文画像は元のまま(旧記事には本題図以外の写真なし)

## ディレクトリ統合(2026-09-25) — content/posts への一本化

- ユーザー依頼: 「old_posts とそれ以外の記事が整理しづらいので、どこか別のディレクトリへ移してひとまとめで管理したい」
- **対応**(commit `83d26b5`): `content/old_posts/*.md` 65本を `content/posts/` へ移動し、`content/old_posts/`(と `_index.md`)を廃止。全記事ソースが `content/posts/` に一本化
- **旧URL維持**: 移動した各フロントマターに `aliases: [/old_posts/<slug>/]` を自動付与 → `/old_posts/<slug>/` は alias リダイレクトページ(=refresh + canonical /posts/<slug>/)で継続アクセス可能。GitHub Pages 上は meta refresh の 200 応答
- URL: `/old_posts/<slug>/` → `/posts/<slug>/`。sitemap 297 件・重複0・`/old_posts/` の sitemap 残存なし
- 教訓: セクション統合時は **slug 衝突チェック** → **alias 付与** → **sitemap/重複検証** の順。本番で新旧URL・リダイレクト先・sitemap を確認済み

## product figure の回り込み修正(2026-09-25) — ニュース風レイアウトの完成

- ユーザー指摘: 「一部、Amazonアソシエイトリンクの画像の周りに文字が回り込んでいない。全記事直して。これからも」
- **原因**: 前回の変換で `<figure class="photo photo--...">` が「段落区切り(---)や見出しの直前」に置かれていた。CSSの float は直前の段落の下に配置されるため、**画像の横には何も流れず白い余白になる**(ブロック境界では回り込みが成立しない)
- **監査**: 監査スクリプト(`audit_lines.py` 行単位版)で「figure 直後の行が `---` / 見出し / 30文字未満の短文」のパターン(＝回り込み不能)を検出。初回 136件のうち実不備は **10件**(hr直後)+ 多数の見出し直後・短文を機械修正
- **対応**(commit `e0d68b8`): 全 figure を「そのセクションの見出し直後(本文段落の直前)」へ再配置 → 直後の段落のテキストが必ず画像の横を回り込む。左右交互配置を記事内順で再計算
- **完成形**: 見出し → figure(photo--left/right) → 本文段落(回り込み)。deep-dive は principal/価格 の各セクション、5choice は商品ごとのセクションで成立
- **検証**: 0残留(行単位監査)。`hugo --minify` → 本番HTMLで「見出し直後 figure + 直後 paragraph」を確認。commit `e0d68b8`・push・デプロイ済み
- **運用ルール(今後も)**: **figure を置くときは必ず「見出し直後・本文段落の直前」にする。見出し/---/短文の直後に置かない**。figure の直後には必ず段落テキストが来るようにする(5choice ではレーダーチャートが続くのは OK = intended)

## SEO 第1項: メタデータ&記事ヘッダー自動最適化(2026-09-26)

ユーザー指示(SEO対策・項番1)の実装。対象: 全記事(未来記事含む)。

- **meta description 自動生成**(`scripts/gen-descriptions.py`): description 欠落の記事に 110〜120字の `description:` を frontmatter へ付与。複数段落を連結し文境界で切る方式(二重句点「。。」は掃除済み)
- **OG画像自動生成**(`scripts/og-image-generator.py`): 1200x630 の `static/images/og/<slug>.jpg` を全記事分生成(PIL・YuGothic)、frontmatter へ `images: ["/images/og/<slug>.jpg"]` を追加。`hugo.toml` の `params.images` に site-default を設定し、記事以外(トップ/カテゴリ/about等)も og:image を持つ
- **robots制御**(site `layouts/_partials/head.html` に theme head をコピーして改修): 単一記事・固定ページ = `index, follow` / **taxonomy・term・404・search = `noindex, follow`**(`.Params.robotsNoIndex`、`.Kind`、`.Layout=="search"` で判定)
- **sitemap 整理**: `search.md` に `sitemap: {disable: true}`、`content/tags/_index.md`・`content/categories/_index.md` に `cascade: {sitemap: {disable: true}}`。**Hugo 既定の `sitemap.excludedKinds` は本環境(未対応)で効かない**ため、cascade 方式で実装。実行結果: 77 URL(投稿72+固定5)、タグ/カテゴリ/search/404/draft は全て除外
- **検証済み**: ローカルビルド + 本番デプロイで、post=index,follow / tag・search=noindex,follow / og:image / description / canonical / twitter:summary_large_image / robots.txt(sitemap指定) を確認
- **学び**: ビルド後 `public/posts/<draft-slug>/index.html` が存在しても、中身が 345バイトの **alias リダイレクトページ** である場合がある(draft 自体は `hugo list published` に含まれない)。draft 判定は `hugo list published` で行うこと
- 残タスク(ユーザー指示の続き待ち): SEO対策の項番2以降