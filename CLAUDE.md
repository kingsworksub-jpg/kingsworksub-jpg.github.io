# Studio Notes ブログ — プロジェクトメモ

**このブログの本質は特定ジャンル(音響機材等)への特化ではなく、「指定されたキーワード/ジャンルについて海外ソースを中心に調べ倒し、日本語記事に仕上げる」という汎用の記事生成ルーティンである**(2026-09-16、ユーザー確認済み)。音響機材・DTM・音楽制作ソフトは最初にこのルーティンを実行した結果できた柱であって、テーマそのものを音楽に縛る必要はない。今後は「あらゆるジャンル」を対象にしうる前提で動くこと。カテゴリ分類は記事の実態に合わせて事後的・柔軟に見直すもので、最初から固定しない。

Hugo (PaperModテーマ) + GitHub Pages + GitHub Actions で構築した静的サイト。

- 公開URL: https://kingsworksub-jpg.github.io/
- リポジトリ: https://github.com/kingsworksub-jpg/kingsworksub-jpg.github.io
- ローカルパス: `C:\Users\norio\my-github-blog`

## 基本ルーティン(記事生成プロセス)

**記事生成モデルの方針(2026-09-24 → 2026-10-01 改訂、ユーザー指示)**: 自動投稿の実行エンジンは **Claude Code と opencode の big-pickle を1日ごとに切り替える**（下記「自動投稿パイプライン」参照）。ローカルの Ollama は使わない。どちらのエンジンでも、新しい記事は `scripts/validate_post.py` の検査に通ったものだけ公開する。

新しい記事を作るときの標準フロー。ジャンル・キーワードはユーザーがその都度指定する。

1. **お題を受け取る**: ユーザーから「このキーワード/ジャンルで書いて」と指示が来る(例: 「ヘッドホンで」「サンプラーで」「ウイスキーで」)。ロードマップ(下記)に候補があればそこから拾ってもよいが、基本は都度指示待ち。
2. **リサーチ**: そのお題について、**最低15サイト以上**の情報源を横断して調べる。**海外(英語)サイトを優先的に含める**こと — 日本語ソースだけで済ませない。「5製品比較」形式(下記)にする場合は、対象ごとにAgent(general-purpose)を並列起動して1対象あたり8〜10サイト(合計50サイト以上)調べさせるのが実績のあるやり方。単発テーマ記事(比較形式でない)でも、15サイト以上は必ず確保する。
3. **事実確認**: リサーチ中に「trendingとして名指しされた対象が実在しない/旧バージョンだった」というケースが何度も発生している(Battery 5が未発売、Studio One→Fender Studio Pro改名、UR22C→URX22C改名、PS-LX310BT生産終了など)。挙げられた対象は鵜呑みにせず、現行かどうかを都度確認する。
4. **執筆**: 日本語記事として仕上げる。文体・引用形式は下記「文体」セクションの指定に従う。
5. **カテゴリ付け**: 既存カテゴリ(`hugo.toml` の `[menu]`)に合うものがあればそれを使う。無理に既存カテゴリに押し込めず、既存カテゴリの延長で自然に追加できるなら新カテゴリを切ってよい(ウイスキーで前例あり)。記事が増えてきたら、カテゴリ構成全体を見直すタイミングを都度検討すること(固定的に考えない)。
6. **画像レイアウト(2026-09-23、ユーザー指示)**: 記事本文に写真や図を載せる場合は、**センター詰めの独立画像ではなく、文章が画像の周りを回り込む新聞・雑誌風のレイアウト**にする。実装は `<figure class="photo photo--left">`(画像が左、本文が右に回り込む)と `<figure class="photo photo--right">`(その逆)を使い分け、**同じ記事内では左右を交互に配置**して雑誌の見開きのようなリズムを作る。スタイルは `assets/css/extended/figures.css` で定義済み(画像の縦幅は`max-height: 420px`上限(2026-09-27改訂。当初は`100px`で画面上の画像が極端に小さかったため、新規記事にも同じルールを継承させること)・横幅`min(34%, 220px)`以下・キャプションは新聞カットライン風・見出しでフロート解除・スマホでは中央寄せに解除)。**回り込む本文の1行幅は10文字(=約180px)を下回らせない**こと。同セクション内で左右それぞれのフロート画像(左右に向かい合う2枚)が縦に重なると、その間の本文は `コンテンツ幅(720px)−画像幅×2−margin(48px)` に潰れるため、画像幅は220px以下に抑える(現行CSSの制約。将来コンテンツ幅を変えるときは、向かい合う2枚の間に最低180px残るよう画像幅上限を再計算すること)。段落は画像の周りで行が1〜2文字だけになったり、極端に短い行が飛び出したりしないよう、**文章量を見て段落の切れ目を調整する**(画像付きは本文量が多めの段落に置き、画像の直後で段落が終わらないよう前後の段落でバランスを取る)。`width`/`height`/`alt`/`loading="lazy"` と `<figcaption>`(写真の説明)・`<span class="credit">`(撮影・出典クレジット)は省略しない。はてなブログにはサイトCSSが効かないが、`scripts/extract-post-html.sh` が `scripts/hatena_figures.py` を通して figure にインラインの float を付けるので、**はてなでも回り込みが再現される(2026-10-01〜)**。note は float 非対応のため縦積み(既知の挙動でOK)。**figure の配置位置(2026-09-25、ユーザー指示・全面適用済み)**: float はブロック境界(直前の段落の下・`---`や見出しの前)に置くと横にテキストが流れない。**figure は必ずセクション見出し(`##`)の直後、そのセクションの本文段落の直前に置く**(見出し → figure → 段落 の順で、段落のテキストが必ず画像の横を回り込む)。figure の直後に見出し・`---`・画像のみ・30文字未満の短文を置かない(アイキャッチ直後のレーダーチャート等、意図的な画像連続はOK)。
7. **収益化リンク**: 該当する場合はAmazonアフィリエイトリンクを付与(下記「マネタイズ状況」参照)。Amazonに無ければ公式サイトへの通常リンクにする。
8. **公開**: `hugo --minify` でローカルビルド確認 → commit & push → GitHub Actionsのデプロイ完了を確認。
9. **ロードマップ更新**: 下記「ロードマップ」セクションのステータスを更新する(着手/公開済みに変更、次候補があれば追記)。

> **GA4計測(2026-09-24導入済み・同日ID調整)**: GitHub Pages は `layouts/partials/extend_head.html` 冒頭の gtag.js、測定ID `G-ZL0DCF6JXB`(`hugo.IsProduction` のときのみ出力)。はてなブログは 詳細設定→解析ツール→「Google アナリティクス 4 埋め込み」に測定ID `G-EBY0HM3HRM`(初回 `G-24HLBTRFJ7` → `G-ZL0DCF6JXB` → `G-EBY0HM3HRM` と同日中に変更)。いずれも**サイト全体の一度限り設定であり、記事ごとの投稿ルーティンに追加する必要はない**(注意: はてなのGTMは動的読み込みのため静的HTMLにIDは出ないが実ブラウザで読み込み確認済み)。

> **SEO運用ルール(2026-09-26 導入済み・全記事/未来記事に適用)**: 全ての記事の frontmatter に **`description:`(110〜120字・要旨)** と **`images: ["/images/og/<slug>.jpg"]`(1200x630 OG画像)** を必ず書く。自動生成なら `scripts/gen-descriptions.py` / `scripts/og-image-generator.py` を使用。タイトルはキーワードを先頭 30〜35文字に収める。robots はテーマの site override(`layouts/_partials/head.html`)により自動(記事=`index, follow` / タグ・カテゴリ・search・404=`noindex, follow`)、sitemap はタグ/カテゴリ/search が自動除外されている。**新規記事作成時も必ず description / images を付けること**。`hugo list published` で公開判定を確認可能(ビルド後の `public/posts/<slug>/index.html` が alias リダイレクトの可能性あり)。
>
> **SEO監査ルーティン(2026-09-26、`scripts/seo-audit.py` に統合)**: 記事投稿後の定期監査は `python scripts/seo-audit.py --check-links` で行う(下書除外・内部リンク網/孤立記事/巨大画像/破損外部リンク/未参照画像/薄い記事を自動レポート)。破損リンク判定は **HTTP 404/410 と接続失敗のみ**を対象にしている(Amazon・メーカー等のボット拒否 `403/405/429/407/503` と、JSゲートでボットに404を返す `tal-software.com` は誤判定のため除外済み。実ブラウザでは開ける)。**新規記事の外部リンクもこの判定基準で選ぶこと**。破損が出た場合は、公式サイトの正規URL(セクション遷移の有無等)を確認して直す。未参照画像も自動列挙される(`static/images` の全ファイルが記事・frontmatter・レイアウトのどこかで参照されていれば `(なし)` 理想)。
>
> **OG寸法の自動付与(2026-09-26、`scripts/og_dimensions.py`)**: 各記事の og:image 実寸(1200x630 等)を frontmatter の `ogImageWidth:`/`ogImageHeight:` に書き込む(冪等・72記事適用済み)。`layouts/partials/extend_head.html` がこれらを `og:image:width`/`og:image:height` メタとして出力する。**新規記事に og 画像を追加したら `python scripts/og_dimensions.py` を必ず実行してからビルドすること**。Article の JSON-LD(BlogPosting+BreadcrumbList)・OG(`og:title/type/url/image`)・Twitterカード(`summary_large_image`)・rel="canonical" は PaperMod テーマと extend_head で自動出力済みで、記事側での追加設定は不要(検証済み)。

> **Google Search Console 登録(2026-09-26 決定・手動1回・Google Cloud不要)**: インデックス登録は **Search Console で一度だけ手動登録**して運用する。手順: ①[Search Console](https://search.google.com/search-console) に `kingsworksub-jpg.github.io` を「ドメインプロパティ」または「URLプレフィックスプロパティ」で登録し、サイト所有者を認証(HTMLタグ / Google Analytics 等) ②「サイトマップ」欄に `sitemap.xml`(https://kingsworksub-jpg.github.io/sitemap.xml) を提出 ③以後は Google が自動クロールする。`sitemap.xml` はビルドで自動生成済み(タグ/カテゴリ/search/404 除外・robots.txt からも自動発見)。**Indexing API は使わない**: `scripts/indexing/notify_changed.py` / `.github/workflows/indexing.yml` は用意してあるが、GitHub Secret `GOOGLE_INDEXING_CREDENTIALS` を登録しない限り deploy 後に自動スキップで無害。将来使いたくなった時だけ Secret を登録すれば有効化される(要 Google Cloud。公式対応は求人/ライブ動画のみで、通常ブログ記事はエラー/無視される可能性あり)。

## ロードマップ

次に書く記事の候補と進捗を管理する場所。空欄・空リストで始めて、ユーザーからの指示や思いついたアイデアを都度ここに追記していく。新しいセッションはまずここを読んで、指示がなければユーザーに「次は何を書くか」を確認すること。

| キーワード/ジャンル | カテゴリ(想定) | ステータス | 備考 |
|---|---|---|---|
| (まだ候補なし) | | | |

**公開済み記事(参考)**:
- DAW / サンプラー / MIDIキーボード / オーディオI/O / アナログターンテーブル(音響機材・DTM系)
- スコッチウイスキー(音楽と無関係の初のジャンル拡張)
- コスパ重視の安ウイスキー10本+個別深掘り10本(2026-09-17、ウイスキージャンル第2弾)
- 炭酸飲料の個別深掘り(2026-09-18〜2026-09-26、26本。カテゴリ`drink`。【2026-09-27 廃止】)
- 酒器の個別深掘り(2026-09-19〜2026-09-21、17本。カテゴリ`sakeware`。【2026-09-27 廃止】)
- ジャズ/音楽の一般記事(2026-09-24〜、カテゴリ`music`。下記「自動継続タスク: テーマ記事の定期投稿」参照)

## 自動投稿パイプライン（2026-10-01 全面改修、ユーザー指示）

**ネタは自動生成**し、カテゴリーをまんべんなく回す。実行は2段構え（ネタ会議 → 投稿）。1日の公開は**8記事まで**（手動投稿も含む）。
旧方式（`themes.txt` の14テーマを1時間ごとに消化、`theme-covered.json`、`blog-drink.md`）は2026-10-01に廃止。

- **タスク**（`scripts/scheduled/register-tasks.ps1`、3つとも `run-claude-task.ps1` の同じロックで直列化）
  - `blog-automation-task`: 投稿。毎日 07:15〜21:15 の2時間おき8回。指示文 `scripts/scheduled/prompts/blog-post.md`
  - `blog-topic-planning`: ネタ会議。毎週日曜 03:00。承認済みを64件まで補充。指示文 `topic-planning.md`（Mode: weekly）
  - `blog-topic-topup`: 毎日 04:00。承認済みが16件未満のときだけ64件まで補充（Mode: topup）
- **実行エンジンは日替わり**（ユーザー指示）: 2026-10-01 を0日目として偶数日 = Claude Code、奇数日 = opencode big-pickle
  （`run-claude-task.ps1` の `-Engine auto` と `topic_plan.py engine` が同じ規則）。手動の作業はこの規則に関係なく Claude Code で行う。
- **品質の安全装置**: 新しい記事は `scripts/validate_post.py <slug>` に通ったものだけ公開する（本文の長さ、簡体字や他言語の混入、
  禁止表現・廃止したタイトルの型、仮画像〔15KB未満〕、クレジット、未来日付、OGP、アソシエイトタグ）。
  さらに `.git/hooks/pre-push`（原本 `scripts/hooks/pre-push`）が、push に含まれる**新規追加の記事**を同じ検査にかけ、NG なら push を止める。
  連続3回失敗すると投稿ジョブは自動で止まる（`topic_plan.py health`）。
- **管理スクリプト** `scripts/topic_plan.py`: status / allocate / today-count / engine / similar / add / claim / complete / fail / reject /
  sync-skips / images / news / calendar / matrix / gaps / health / bootstrap（使い方は冒頭の docstring）。
- **データ**: `scripts/topics-queue.json`（キュー。status = approved / in_progress / published / failed / rejected / hold / deleted）、
  `scripts/topic-log.json`（全履歴。既存記事も登録済み）、`scripts/category-plan.json`（カテゴリーと重み。均等）、
  `scripts/topic-sources.json`（カテゴリー別RSS）、`scripts/topic-calendar.json`（月ごとの季節ネタ）、`scripts/topic-matrix.json`（定番テーマの軸）、
  `scripts/pipeline-status.json`（アプリ表示用の状態）。
- **配分**: 直近60本に占める割合と目標（均等）の差＋最後の投稿からの日数で優先度を出し、1件ずつ再計算しながら配る。同じカテゴリーは連続させない。
- **採点**: 重複25／事実確認20／画像20／季節15／検索需要10／Amazon10。60点未満は不採用。画像（ライセンス確認済み2件以上）が無いネタは不採用。
  製品中心でなくてよい（Amazon は加点のみ）。
- **新カテゴリー**: 既存に合わない有力候補が3件以上出るときだけ、週1つまで作ってよい（category-plan.json・hugo.toml・layouts/index.html を更新）。
- **持ち込みネタ**: `scripts/themes.txt` に1行書くと、次のネタ会議で最優先で採用される（取り込んだ行は削除される）。
- **Android アプリ「ブログのネタ」**（`android/topics-app/`、Kotlin + Compose）: キューと状態を GitHub API で表示。ネタを削除すると
  `scripts/topic-skips/<id>.json` を作成し、パイプラインは `sync-skips`（claim 時にも自動実行）で `deleted` にしてスキップする。
  APK は GitHub Actions（`.github/workflows/topics-app.yml`）がビルドし、Release `topics-app-latest` に置く。署名鍵は Secrets
  （`TOPICS_KEYSTORE_*`）と `.secrets/topics-app.jks`（git管理外の控え）。削除には fine-grained トークン（Contents 読み書き）をアプリに入力する。
  `hugo.yml` はアプリ・スキップファイルだけの push ではデプロイしない。
  - **アプリからのネタ追加**（2026-10-01）: 右下の＋でテーマ（必須）・カテゴリー（おまかせ可）・メモを入力すると `scripts/topic-requests/<日時>.json` を作成。
    `topic_plan.py ingest-requests`（`claim` 時にも自動実行）がキューに `source_of_idea: "user"`・`needs_research: true` で取り込み、**次の投稿で最優先**。
    情報源・画像・キーワードは投稿ジョブが執筆時に集める。カテゴリーが空なら投稿ジョブが決め、`complete --category` で記録する。
  - **アプリの自己更新**（2026-10-01）: メニュー「アプリを更新」。Release `topics-app-latest` の `version.json`（versionCode = ビルド番号）と
    インストール済みの versionCode を比べ、新しければ APK をダウンロードしてインストール画面を開く（起動時にも確認してバナー表示）。
    同じ署名鍵で署名しているので上書き更新できる。初回のみ「このアプリからのインストールを許可」が必要。
  - **実行状況の自動同期**（2026-10-02）: `run-claude-task.ps1` がジョブの開始時と終了時に `topic_plan.py run-status` で
    `pipeline-status.json` の `current_job` / `last_run` / `recent_runs` を更新して push する（モデルが起動に失敗しても記録される）。
    アプリは開いた時・前面に戻った時・表示中は1分ごと（トークン未設定なら3分ごと）に読み直し、「実行中」「前回の実行（完了／失敗／時間切れ）」を表示する。
- **停止方法**: 「止めて」と言われたら `Disable-ScheduledTask -TaskName blog-automation-task`（ネタ会議は止めなくてよい）。
  カテゴリー単位で止めるなら category-plan.json の weight を 0 にする。

## 自動続続タスク: 海外ジャズ記事のXポスト(……**2026-09-29 完全削除**、再開禁止)

ユーザー指示: 既にバランド自動化じゃないとして、完全に要ないとして「宏全に実行しないと判断し、3時間前に以下を全部停止し、コードも削除した。

- **Windowsタスクシューラーの`KingsWork-X-Jazz`を`Unregister-ScheduledTask`で削除済み**。再登録は`scripts/scheduled/register-tasks.ps1`に`KingsWork-Blog-Drink`のみを残している。
- **`scripts/x-autopost/`ディレクトリ全体を削除**。`poster.py`/`post_jazz_tweet.py`/`jazz-posted.json`(ジャズポスト用)と、前回のフログプランスト(`db.py`/`feed_check.py`/`generate.py`/`scraper.py`/`main.py`/`seed_baseline.py`/`README.md`)、更に確認済みの若干の口道レストファイル(`amazon_search_fetch.py`/`parse_amazon_html.py`/`fetch_carbonation.py`/`fetch_sakeware.py`/`fetch_bodum_image.py`)をまとめ除外。
- **Pythonヴィンツュークルートの位置を`scripts/x-autopost/.venv/`から`scripts/.venv/`に移動**。`extract-post-html.sh`のPython取得先と`の`allowedTools`はこの新パスに更新済み。なお、`pyautogui`/`pygetwindow`/`pyperclip`/`feedparser`は无要になったが、実装は`playwright`と`greenlet`/`pyee`のみで十分。
- **以降のこのセクションは全部復徑引用**(旧チュートプロクト‘ハートバンナーの修正’の`fix-hatena-banners.py`使用コマンドなど)。X自動化を使用していた記述は下記の「Python自前パイプラインによるX自動投稿」の章のから御除されている。
- **このセクションの再開しない**。ヘードフドのログヨードトと相拥して以下が残っている。

## 拡散投稿(SNS/ブログサイトへの転載)

記事を公開するたびに、この表の「有効」な投稿先へ自動投稿する運用にする(2026-09-17〜検討開始)。SNSは記事へのリンク+一言、ブログサイトは記事本文そのものを転載する。**2026-09-27、記事公開に伴うXへの自動投稿は廃止した**(下表のXの行はブログフローの一部ではなくなった)。

| 媒体 | 投稿内容 | 自動化 | 必要な準備 | 状態 |
|---|---|---|---|---|
| X (Twitter) | — | — | — | **完全媳殈(2026-09-29、ユーザー指示)**。記事公開に伴うX自動投稿は2026-09-27に媳殈し、海外ジャズ記事のXポスト(`KingsWork-X-Jazz`)も2026-09-29にタスク削除・コード別除。相関するコードとトラフステックはすべて削除済み。取材方法の履歴は「はてなブログ→X自動投稿パイプライン」の章に移した。 |
| Threads | リンク+一言 | Threads API(Meta)で可能、無料 | Meta for Developersでアプリ作成、Threads/Instagramアカウント連携、アクセストークン取得(ユーザー本人が登録) | 未着手 |
| はてなブログ | 記事本文を転載(タイトル・本文・出典として元記事へのリンクを添える) | 公式AtomPub APIで可能(WSSE認証)。GitHub Actions連携の実装例も多数あり安定 | はてなID作成、対象のはてなブログ開設、ブログ詳細設定からAtomPub用APIキー取得 | **環境構築済み(2026-09-16)** — 下記参照 |
| Facebook Page | リンク+一言 | Graph APIで可能 | Facebook Page作成 + Meta for Developersでアプリ作成、アクセストークン取得 | 優先度低・保留 |
| note.com | 記事本文 | **公式APIなし(2026年時点でも非公開・時期未定)**。はてなブログと異なりAtomPubも無い。`scripts/post-to-note.py` + Playwright で **Chromium永続プロファイルにログイン状態を保存し、エディタへのキー入力だけ自動化する**(2026-09-28 実装・検証済み) | — | **有効(2026-09-28)** — はてなブログと同じく、記事公開ごとに自動投稿する。下記「note.com への投稿」参照 |
| Instagram | リンク+一言 | フィード投稿の本文にリンクを貼れない仕様のため、記事拡散用途にはそもそも不向き | — | **対象外** |

**セキュリティ上の注意**: このリポジトリ(`kingsworksub-jpg/kingsworksub-jpg.github.io`)は公開リポジトリ。APIキー・アクセストークンの類は**絶対にコード/コミットに直書きしない**。ローカル実行時は環境変数、GitHub Actionsで動かす場合はリポジトリの Encrypted Secrets を使うこと。

**進め方**: ユーザーが各媒体のアカウント作成・アプリ登録・トークン発行を行い、そのトークンをClaude Codeに渡す→Claude Code側で投稿スクリプト(`scripts/post-to-*.sh` 想定、curlでAPI叩く)を作成・実行する分担。アカウント登録そのものは代行できない(本人確認・支払い情報・規約同意が必要なため)。

### はてなブログ連携(構築済み)

- 認証情報: `.secrets/hatena.env`(gitに含まれない。`HATENA_ID` `HATENA_BLOG_DOMAIN` `HATENA_API_KEY` を定義)。新しいセッションでは `source .secrets/hatena.env` してから使う。ファイルが無い場合はユーザーにはてなブログの詳細設定→AtomPubのAPIキーを再度聞くこと。
- `scripts/extract-post-html.sh <slug> [出力ファイル]` — `content/posts/<slug>.md` を非minifyビルドしてレンダリング済みHTML本文を取り出し、画像等の相対パス(`/images/...`)を `https://kingsworksub-jpg.github.io/...` の絶対URLに変換して出力する。**「※この記事はStudio Notesからの転載です」のような転載元注釈は付けない(2026-09-17、ユーザー指示で削除・今後も禁止)**。
- **はてなでの画像の回り込み(2026-10-01、ユーザー指示で永続化)**: `extract-post-html.sh` は抽出した本文を `hatena_banner.py`(商品バナーのインライン化)→ `scripts/hatena_figures.py` の順に通す。`hatena_figures.py` は `<figure class="photo photo--left|right">` に `float:left|right;width:220px;max-width:42%` などのインラインstyleを付け、img を幅100%、figcaption・credit を小さい文字にし、図版がある記事だけ h2/h3 に `clear:both` を付けて本文末尾に clear 用の div を足す(図版の無い記事は無変更)。はてなはインラインstyleを保持することを確認済み。冪等(style付きの figure は触らない)なので、新規投稿(`post-to-hatena.sh`)でも更新(`update-hatena-post.sh`)でも `extract-post-html.sh` の出力をそのまま渡せばよい。 **2026-10-01 に既存のはてな記事も全件対応済み**: 写真はあるが回り込みの無かった11件はインラインstyleだけを追加、はてな側に写真が1枚も無かった古い本文の83件(ウイスキー・飲料・酒器・機材・比較記事など)は `extract-post-html.sh` で現行の記事から本文を作り直してPUT更新(タイトル・公開状態は維持)。以後、はてなの本文はGitHub Pagesの記事と同じ内容・同じ回り込みになっている。
- **重大バグ修正(2026-09-17)**: この抽出スクリプトのawkロジックが「`post-content md-content`直後の最初の`</div>`で抽出終了」という単純設計だったため、各製品セクション内に`<div class="product-links">...</div>`(入れ子div)を差し込むようになった時点で、**最初の製品セクション(=最初のproduct-linksのdivが閉じた時点)で記事が丸ごと打ち切られる**という致命的なバグを踏んだ(はてなブログの全7記事が症状: 2番目以降のセクション・まとめ表・結論が消えていた)。さらに、開始マーカー行に本文の第一段落が同居している(`<div class="post-content md-content"><p>...`のように同一行)ため、旧ロジックでは**冒頭の第一段落も欠落**していた。修正版はdivのネスト深度を追跡し(`<div`出現で+1、`</div>`出現で-1)、深度が0に戻った時点(=post-content自身の閉じタグ)でのみ抽出を止める。開始マーカー行の残り部分も正しく本文として取り込む。修正後、`scripts/extract-post-html.sh daw-5choice-2026`で全7つの`<h2>`・divバランス(開閉数一致)を確認済み。**今後 `.product-links` のような入れ子divを本文に追加する変更をするときは、必ずこのスクリプトで抽出テストしてから投稿すること**。
- 2026-09-17: マニュファクチャラー視点の序文への書き換え・`.product-links`写真ギャラリーの追加・所持アピール表現の削除を全7記事に適用し、はてなブログ側も`update-hatena-post.sh`で再同期済み。**注意**: `.product-links`のCSS(`assets/css/extended/product-links.css`)はメインブログにしか効かない。はてな側では画像・リンクはそのまま表示されるがレイアウト(横並びグリッド)は当たらず、縦積みの通常の画像+リンクとして表示される(機能的には問題ないが見た目は簡素)。
- `scripts/post-to-hatena.sh "タイトル" 本文HTMLファイル [draft|publish]` — AtomPub APIへWSSE認証でPOST。`draft` を渡すと下書き、省略(または`publish`)で即時公開。**投稿後にHatenaのレスポンスXMLから実際の`app:draft`値を読み直して、意図通りかを検証してから成功と表示する**(初回テストで`true`/`false`ではなく`yes`/`no`でないと無視される仕様に気づかず誤って即時公開してしまった教訓を反映)。
- 典型的な使い方: `source .secrets/hatena.env && scripts/extract-post-html.sh <slug> /tmp/<slug>.html && scripts/post-to-hatena.sh "記事タイトル" /tmp/<slug>.html publish`
- 2026-09-16に疎通テスト済み(DAW記事を下書き投稿→内容確認→**ユーザー承認後に本公開するか判断**、という運用。デフォルトでは`draft`でテストしてから`publish`に切り替えるのが安全)。
- **GA4導入済み(2026-09-24)**: はてなブログは設定→詳細設定→「解析ツール」→「Google アナリティクス 4 埋め込み」に測定ID `G-EBY0HM3HRM` を保存済み(初回 `G-24HLBTRFJ7` → `G-ZL0DCF6JXB` → `G-EBY0HM3HRM` と同日中に変更)。静的なページHTMLには出ないが(はてなのGTMが動的読み込み)、実ブラウザで `googletagmanager.com/gtag/js?id=G-EBY0HM3HRM` の読み込みを確認済み。**変更はAPI不可なのでダッシュボードから。再設定不要のサイト全体設定・投稿ルーティンへの追加は不要**。
- **2026-09-16、既存6記事を一括で本公開済み**(ユーザー指示「一気に公開しちゃって」)。以後、新しい記事を公開する際は都度この2スクリプトで はてなブログにも転載すること(ロードマップの「拡散投稿」欄も更新する)。
- **重要な教訓**: `post-to-hatena.sh` は常に**新規エントリを作成する**(POST)。すでに投稿済みの記事の内容やタイトルを直しただけのつもりで再度 `post-to-hatena.sh` を叩くと、**同じ記事がもう1本増えて重複投稿になる**(実際に2026-09-16、DAW記事をこれで重複させてしまい、後から気づいてエントリ一覧をAtomPubで取得し直し、古い方を`DELETE`で削除した)。既存記事の内容・タイトルを直したときは、必ず `scripts/update-hatena-post.sh <entry_id> "新タイトル" 新本文.html` で**その記事のentry IDを指定してPUT更新**すること。entry IDが分からない場合は、コレクションのAtomPubフィード(`GET .../atom/entry`)を取得し、`<link rel="edit">` と `<title>` をペアで見て該当記事のIDを特定する。

| 記事 | はてなブログURL | Entry ID(更新に必要) |
|---|---|---|
| DAW | https://kinbro.hatenablog.com/entry/2026/09/16/200310 | 14945776032078440540 |
| サンプラー | https://kinbro.hatenablog.com/entry/2026/09/16/175527 | 14945776032078470402 |
| MIDIキーボード | https://kinbro.hatenablog.com/entry/2026/09/16/175531 | 14945776032078470419 |
| オーディオI/O | https://kinbro.hatenablog.com/entry/2026/09/16/175534 | 14945776032078470431 |
| アナログターンテーブル | https://kinbro.hatenablog.com/entry/2026/09/16/175537 | 14945776032078470439 |
| スコッチウイスキー | https://kinbro.hatenablog.com/entry/2026/09/16/175540 | 14945776032078470450 |
| Focusrite Scarlett 2i2 深掘り(単発テーマ記事の初回) | https://kinbro.hatenablog.com/entry/2026/09/16/201704 | 14945776032078510345 |
| Technics SL-1200MK7 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/094413 | 14945776032078691372 |
| Audio-Technica AT-LP120XUSB 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/094433 | 14945776032078691454 |
| Rega Planar 3 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/094443 | 14945776032078691554 |
| Pro-Ject Debut Carbon EVO 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/094453 | 14945776032078691593 |
| Sony PS-LX3BT 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/094503 | 14945776032078691636 |
| コスパ重視の安ウイスキー10選 | https://kinbro.hatenablog.com/entry/2026/09/17/223231 | 14945776032078925432 |
| サントリー角瓶 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223226 | 14945776032078925412 |
| ブラックニッカ クリア 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223235 | 14945776032078925462 |
| トリスウイスキー 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223244 | 14945776032078925505 |
| ジムビーム ホワイト 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223241 | 14945776032078925498 |
| フォアローゼズ イエロー 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223224 | 14945776032078925392 |
| バランタイン ファイネス 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223238 | 14945776032078925486 |
| カティサーク 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223228 | 14945776032078925420 |
| ホワイトホース ファインオールド 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223219 | 14945776032078925366 |
| デュワーズ ホワイトラベル 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223233 | 14945776032078925440 |
| ジョニーウォーカー レッドラベル 深掘り | https://kinbro.hatenablog.com/entry/2026/09/17/223222 | 14945776032078925374 |
| ウィルキンソン タンサン 深掘り(炭酸飲料シリーズ1本目) | https://kinbro.hatenablog.com/entry/2026/09/18/075054 | 14945776032079085104 |
| ヨサソーダ 深掘り(炭酸飲料シリーズ2本目) | https://kinbro.hatenablog.com/entry/2026/09/18/084248 | 14945776032079097508 |
| OZA SODA 深掘り(炭酸飲料シリーズ3本目) | https://kinbro.hatenablog.com/entry/2026/09/18/104300 | 14945776032079242804 |
| CRYSTAL SPARK グレープソーダ 深掘り(炭酸飲料シリーズ4本目) | https://kinbro.hatenablog.com/entry/2026/09/18/124252 | 14945776032079352661 |
| カナダドライ ジンジャーエール 深掘り(炭酸飲料シリーズ5本目) | https://kinbro.hatenablog.com/entry/2026/09/18/144205 | 14945776032079413222 |
| 伊藤園 ミネラルストロング 深掘り(炭酸飲料シリーズ6本目) | https://kinbro.hatenablog.com/entry/2026/09/18/164514 | 14945776032079524762 |
| 富士山の強炭酸水 深掘り(炭酸飲料シリーズ7本目) | https://kinbro.hatenablog.com/entry/2026/09/18/184231 | 14945776032079558940 |
| 三ツ矢サイダーZERO 深掘り(炭酸飲料シリーズ8本目) | https://kinbro.hatenablog.com/entry/2026/09/18/221832 | 14945776032079620987 |
| キリンレモン 炭酸水 深掘り(炭酸飲料シリーズ9本目) | https://kinbro.hatenablog.com/entry/2026/09/18/224858 | 14945776032079629572 |
| 能作 本錫100%酒器セット 深掘り(酒器シリーズ1本目) | https://kinbro.hatenablog.com/entry/2026/09/19/132413 | 14945776032079837776 |
| サンペレグリノ 深掘り(炭酸飲料シリーズ10本目) | https://kinbro.hatenablog.com/entry/2026/09/19/142329 | 14945776032079851655 |
| 柳宗理デザイン 清酒グラス 深掘り(酒器シリーズ2本目) | https://kinbro.hatenablog.com/entry/2026/09/19/152635 | 14945776032079869167 |
| CRYSTAL SPARK ラムネ 深掘り(炭酸飲料シリーズ11本目) | https://kinbro.hatenablog.com/entry/2026/09/19/172227 | 14945776032079902024 |
| BODUM DOURO 徳利/カラフェ 深掘り(酒器シリーズ3本目) | https://kinbro.hatenablog.com/entry/2026/09/19/182858 | 14945776032079920491 |
| コカ・コーラ ゼロ 深掘り(炭酸飲料シリーズ12本目) | https://kinbro.hatenablog.com/entry/2026/09/19/192204 | 14945776032079935473 |
| KEITH 純チタン おちょこ 酒器 深掘り(酒器シリーズ4本目) | https://kinbro.hatenablog.com/entry/2026/09/19/213034 | 14945776032079974862 |
| ドデカミン 深掘り(炭酸飲料シリーズ13本目) | https://kinbro.hatenablog.com/entry/2026/09/19/223514 | 14945776032079996485 |
| アデリア 津軽びいどろ NEBUTA 酒器セット 深掘り(酒器シリーズ5本目) | https://kinbro.hatenablog.com/entry/2026/09/20/024441 | 14945776032080063857 |
| green cola(グリーンコーラ) 深掘り(炭酸飲料シリーズ14本目) | https://kinbro.hatenablog.com/entry/2026/09/20/032817 | 14945776032080069533 |
| 東洋佐々木ガラス カラフェ・バリエーション 深掘り(酒器シリーズ6本目) | https://kinbro.hatenablog.com/entry/2026/09/20/043212 | 14945776032080073637 |
| リアルゴールド 深掘り(炭酸飲料シリーズ15本目) | https://kinbro.hatenablog.com/entry/2026/09/20/102323 | 14945776032080138929 |
| 田島硝子 金箔富士 冷酒杯(桜) 深掘り(酒器シリーズ7本目) | https://kinbro.hatenablog.com/entry/2026/09/20/133555 | 14945776032080203720 |
| ポッカサッポロ 北海道富良野ホップ炭酸水 深掘り(炭酸飲料シリーズ16本目) | https://kinbro.hatenablog.com/entry/2026/09/20/142138 | 14945776032080215135 |
| 和座の蔵 九谷焼 ぐい呑み 白粒鉄仙 深掘り(酒器シリーズ8本目) | https://kinbro.hatenablog.com/entry/2026/09/20/154055 | 14945776032080237666 |
| モンスターエナジー パイプラインパンチ 深掘り(炭酸飲料シリーズ17本目) | https://kinbro.hatenablog.com/entry/2026/09/20/162418 | 14945776032080259968 |
| ピーコック 真空二重構造 酒器セット 深掘り(酒器シリーズ9本目) | https://kinbro.hatenablog.com/entry/2026/09/20/174248 | 14945776032080283668 |
| サンガリア きれいな炭酸水 深掘り(炭酸飲料シリーズ18本目) | https://kinbro.hatenablog.com/entry/2026/09/20/182254 | 14945776032080296748 |
| 廣田硝子 ちろり(青・中子付き) 深掘り(酒器シリーズ10本目) | https://kinbro.hatenablog.com/entry/2026/09/20/202113 | 14945776032080333833 |
| キレートレモン Wレモン 深掘り(炭酸飲料シリーズ19本目) | https://kinbro.hatenablog.com/entry/2026/09/20/212123 | 14945776032080351881 |
| 高岡漆器 螺鈿ガラス 金杯(万華鏡)桜 深掘り(酒器シリーズ11本目) | https://kinbro.hatenablog.com/entry/2026/09/20/222215 | 14945776032080370631 |
| 神戸居留地 スパークリングウォーター 深掘り(炭酸飲料シリーズ20本目) | https://kinbro.hatenablog.com/entry/2026/09/20/232111 | 14945776032080388905 |
| 大館工芸社 秋田杉 酒器3点セット 深掘り(酒器シリーズ12本目) | https://kinbro.hatenablog.com/entry/2026/09/21/002105 | 14945776032080405656 |
| 三ツ矢サイダー(通常版)深掘り(炭酸飲料シリーズ21本目) | https://kinbro.hatenablog.com/entry/2026/09/21/012339 | 14945776032080416495 |
| 東洋佐々木ガラス 片口 冷酒カラフェ 深掘り(酒器シリーズ13本目) | https://kinbro.hatenablog.com/entry/2026/09/21/022656 | 14945776032080423161 |
| コカ・コーラ アイシー・スパーク from カナダドライ レモン 深掘り(炭酸飲料シリーズ22本目) | https://kinbro.hatenablog.com/entry/2026/09/21/032810 | 14945776032080428751 |
| 国産美濃焼 黒千代香 深掘り(酒器シリーズ14本目) | https://kinbro.hatenablog.com/entry/2026/09/21/042359 | 14945776032080433323 |
| 大塚食品 MATCH(マッチ) 深掘り(炭酸飲料シリーズ23本目) | https://kinbro.hatenablog.com/entry/2026/09/21/052233 | 14945776032080452514 |
| アデリア 津軽びいどろ 片口あじさい 深掘り(酒器シリーズ15本目) | https://kinbro.hatenablog.com/entry/2026/09/21/062443 | 14945776032080467143 |
| カナダドライ ザ・タンサン ストロング 深掘り(炭酸飲料シリーズ24本目) | https://kinbro.hatenablog.com/entry/2026/09/21/072220 | 14945776032080477449 |
| 有田焼 炎華 酒器セット 深掘り(酒器シリーズ16本目) | https://kinbro.hatenablog.com/entry/2026/09/21/082202 | 14945776032080490287 |
| ドデカミンのゼロが好きだと叫びたい 深掘り(炭酸飲料シリーズ25本目) | https://kinbro.hatenablog.com/entry/2026/09/21/092244 | 14945776032080505882 |
| 津軽びいどろ みずばしょう 酒器セット 深掘り(酒器シリーズ17本目) | https://kinbro.hatenablog.com/entry/2026/09/21/112806 | 14945776032080547620 |
| アート・ブレイキーとブルー・ノート黄金時代、ハードバップの熱を名盤でたどる(ジャズ特集3本目) | https://kinbro.hatenablog.com/entry/2026/09/24/124117 | 14945776032081757676 |
| モーダルジャズという挑戦、『Kind of Blue』から『A Love Supreme』へ(ジャズ特集4本目) | https://kinbro.hatenablog.com/entry/2026/09/24/124123 | 14945776032081757708 |
| リズム隊とホーンから知る、ジャズの楽器入門(ジャズ特集5本目) | https://kinbro.hatenablog.com/entry/2026/09/24/232320 | 14945776032081943034 |
| ジャズ名盤入門、最初に聴きたい10枚を時代順に(ジャズ特集6本目) | https://kinbro.hatenablog.com/entry/2026/09/24/233736 | 14945776032081946518 |
| VOX 強炭酸水 コーラフレーバー 深掘り(炭酸飲料シリーズ26本目) | https://kinbro.hatenablog.com/entry/2026/09/26/200122 | 14945776032082692111 |
| Miles Davis『Birth of the Cool』からChet Bakerの西海岸へ、クール・ジャズの時代(ジャズ特集7本目) | https://kinbro.hatenablog.com/entry/2026/09/27/192115 | 14945776032083085599 |
| Charlie ParkerとDizzy Gillespie、ビバップが生まれた1940年代ニューヨークの5年間(ジャズ特集8本目) | https://kinbro.hatenablog.com/entry/2026/09/28/184241 | 14945776032083484010 |
| 「Tank!」から佐世保の喫茶店まで、アニメーションとジャズが出会う場所(テーマ記事「アニメーションとjazz」) | https://kinbro.hatenablog.com/entry/2026/09/29/133345 | 14945776032083816100 |
| Jon Batiste『Black Mozart』と山中千尋25周年、2026年のジャズ新作を聴く | https://kinbro.hatenablog.com/entry/2026/09/30/005218 | 14945776032084075516 |
| Kamasi WashingtonとDinner Partyが拓く、スピリチュアルジャズの新潮流（テーマ記事「モダンジャズの新潮流」） | https://kinbro.hatenablog.com/entry/2026/09/30/092501 | 14945776032084177549 |
| スカーフ一枚で装いが変わる、2026年のスカーフスタイリング | https://kinbro.hatenablog.com/entry/2026/09/30/112243 | 14945776032084327276 |
| B&W 685レビュー、黄色いケブラーコーンが鳴らす英国流の開放感 | https://kinbro.hatenablog.com/entry/2026/10/01/083002 | 14945776032084538870 |
| Cubase Pro 15のスコアエディターを読み解く、Doricoの譜面エンジンと15の新機能 | https://kinbro.hatenablog.com/entry/2026/10/01/092148 | 14945776032084553828 |
| 『CUBASE 15 & 15 PRO ユーザーガイド』を手元に、4週間で1曲を仕上げる | https://kinbro.hatenablog.com/entry/2026/10/01/092155 | 14945776032084553845 |
| 5つのアイテムで組むクラシックスタイル：ライトブルーのシャツとブラウンのサスペンダー | https://kinbro.hatenablog.com/entry/2026/10/01/144357 | 14945776032084657450 |

### note.com への投稿（2026-09-28 実装・全記事へ必須化）

> **重要(2026-09-28、ユーザー指示)**: **note.com は「はてなブログ」と並び、記事公開ごとの必須の投稿先になった。**
> これからは **Hugoビルド → commit & push → GitHub Actions デプロイ確認 → はてなブログへ転載 → note.com へドラフト作成 → 公開** の順で必ずセットで行うこと。
> はてなブログへの転載を飛ばさないようにしているのと同時に、**`post-to-note.py` も飛ばさないこと**。
> 1時間に1回のテーマ記事パイプライン(`KingsWork-Blog-Drink`)にもnote投稿のステップを追加してあるので、通常の自動投稿ルートでも必ず走る。
> 手動で記事を書いた場合も同様に note へ投入する。
> **ユーザーが「note には投稿しない」と明示的に指示した場合はこの限りでない。それ以外の既定値は「必ず投稿する」こと。**

note.com には投稿用の公開 API がなく（はてなブログは AtomPub がある）、コマンド1行では投稿できない。
そのため **Chromium の永続プロファイルにログイン状態を保存し、エディタへのキー入力だけを自動化する** 方式で運用する。
**公開まで自動化してするのが既定運用(2026-09-29、ユーザー指示)**。`--publish` で公開まで行い、公開URLが返ったことを確認して完了とする。

- 変換: `python scripts/convert-to-note.py <slug>` → `scripts/note-drafts/<slug>.note.txt`
- 投稿・公開: `python scripts/post-to-note.py --slug <slug> --publish`（`publish_note()` が2段実行し、APIで公開を検証して公開URLを返す）
- ログインの初期化（1回のみ）: `python scripts/post-to-note.py --login`
  - ブラウザが開くので手動でログインする。ログイン状態が `data/note_user_data/` に保存される。**cookie が含まれるので `.gitignore` に追記済み**。
- 主なオプション:
  - `--all` — `note-drafts/` にある全ファイルを順番に処理
  - `--slug <slug>` — 対象スラッグを1つ指定
  - `--save` — 「下書き保存」まで自動で押す
  - `--publish` — 公開まで自動で押す（既定は押さない）
  - `--img-scale 1` — 画像を「縮小」ボタンで620px→372pxにする（**既定で1**。0指定は全幅）
  - `--no-images` — 画像を挿入せずテキストのみ
  - `--fast` — `insertText` で一括入力（高速だが **Markdown変換が効かない**ので緊急時のみ）
  - `--hold` / `--no-wait` — ブラウザを開いて確認する時間の制御

#### noteエディタの仕様（2026-09-28 実測。修正時に必ず参照すること）

以下はすべて実測値であり、**すべて `post-to-note.py` にコードとして実装済み**。推測でDOMや操作を変えると壊れるので、まずこの節を読むこと。

- **本文は `.ProseMirror[contenteditable="true"]`、幅620px固定**。初期値は `text-align: start`（＝左寄せ）。中央/右揃えは**明示的に選んだときだけ**付く。
- **タイトル欄は `textarea[placeholder="記事タイトル"]`**（`input` ではない）。`fill()` が効く。
- **Enter 1回**は **同じ `<p>` の中に `<br>` が入る**（＝段落が分かれない）。**Enter 2回**で**兄弟の新しい `<p>`** ができる。ブロック境界は必ず **Enter 2回**。
- **`## `（h2）/ `### `（h3）/ リスト / `**x**`（太字）は実キー入力でしか変換されない**。`insertText`（`--fast`）では効かない。
- **`#tag` は実キー入力**（`page.keyboard.type`、delay付き）でチップ化する。
- **`*斜体*` / `_斜体_` は非対応**（「*」が残る）。`convert_italics` で `**ボールド**` に変換して回避している。`# `（h1）と `> `（引用）も非対応。
- **画像は必ず新しい段落の中に貼り付ける**。既存 `<p>` の末尾に貼ると、**後続のテキストがすべて `<figcaption>` の中に入り**、その部分だけ中央寄せになる（`figcaption` の既定が `text-align: center` のため）。
- **画像直後の脱出シーケンス（これ一択）**: `Escape` → `Enter`×2 → `Backspace`。`ArrowDown` は効かない。`Backspace` を落とすと図版直下に空 `<p>` が1個残る。
- **画像前は Enter 1回でよい**。2回にすると図版の前に空 `<p>` が残る。
- **見出し直後の空 `<p>`** は `Enter`×2 → `Backspace` で潰す。
- **画像ツールバーは画像をクリックしないと出ない**。クリック → `button[aria-label="縮小"]` で **620px → 372px**。
- **画像の float（回り込み）は非対応**。`figure` に style を JavaScript で当てても破棄され、「画像の配置」メニューは選択肢が空。**GitHub Pages 側の `photo photo--left/right` による回り込みレイアウトは note では再現できない**ので、note では縦積みのままにする（`assets/css/extended/figures.css` の `max-width` は効かない）。
- **間隔は note の標準余白に任せる**（画像と段落の間36px、見出しの直後18px）。CSS で詰める手段はないので、**空 `<p>`（`<br>`だけ/空白だけ）を残さないこと**だけが間隔対策になる。`remove_empty_paragraphs()`（空段落をクリック → `Backspace`）で入力後に掃除する。

#### 保存前の自動検証（`validate_body()` / `print_validation()`）

投稿処理の最後に自動で走り、NGが出たら `[検証][NG]` を表示する。**公開前に必ず確認すること。**

- **`figcaption` が60文字を超える** → 画像後の本文が `figcaption` に流れ込んでいる
- **`text-align` が `start`/`left` 以外の要素が残存** → 中央/右寄せが混ざっている
- **空 `<p>` が3個以上** → 画像と文字の間隔が異常に広い

`set_text_align()` は「中央/右になっている要素だけ」を1ブロックずつ三クリックして「指定なし（左）」を適用する修復関数。
**全ブロックに一括で適用するとメニューを誤クリックして逆に `center`/`right` を作ってしまう**（実測）ので、**NG として検出されたときだけ修復する**こと。問題がなければ0回で終わる。

#### 下書きの管理（重複防止）

- **`post-to-note.py` は新規下書きを作るコマンド**。既存下書きを修正したいときにそのまま使うと**下書きが複製される**ので、既存下書きは `https://editor.note.com/notes/<key>/edit/` に直接アクセスして編集する。
- **生成した下書きの key は必ず下の表に記録する**。
- **下書きの確認**: `https://note.com/notes?type=draft` に一覧が出る（`button[aria-label$="を編集"]` を持つ行が下書き1件）。**「自分の記事」の件数が想定より多いならテスト書きの残骸が残っているので削除する。**
- **下書きの削除は UI 経由でしかできない**。行の「⋮」メニュー → `削除` → 確認ダイアログの `削除`、または編集画面の「その他」→「削除」→ 確認ダイアログ。**記事 key は `…を編集` を押したときの遷移先 URL**（`https://editor.note.com/notes/<key>/edit/`）から取得する（一覧の行は `a[href]` を持たないため、セレクタでは取れない）。**直接削除 API（`/api/v1/text_notes/<key>`、`/api/v3/text_notes/<key>`、`/api/v1/drafts/<key>`、`/api/v1/text_notes/<key>/destroy`）はすべて CloudFront 403 で拒否される**。行のメニューは `aria-label` 空・`svg` ありの2つ目のボタンなので**行の `button[aria-label]` を数えて「編集」以外のものを押す**（「公開ステータス」や「下書きを保存」は別要素で誤クリックしやすい）。
- **削除の進め方**: 保持したい下書きの key を固定してから、それ以外を下書き一覧から1件ずつ消して、最後に件数とタイトルを再確認する。**タイトルが空の下書きは一覧に現れない**ので、編集画面の「その他」→「削除」で消す（上記「公開の手順に注意点」7番）。
- **2026-09-29 時点の整理結果**: 下書きは **0件**。`アニメーションとジャズ`(n0893de9eb19f) を公開し、残っていた重複下書き3件（ビバップ ×2・クールジャズ ×1）と空下書き `n2b8ea38ece88` を削除済み。公開済4本はすべて `is_published: true` を確認。

| 記事 | note 公開URL | 下書きkey | 状態 |
|---|---|---|---|
| ハードバップとブルー・ノート黄金時代 | https://note.com/shining_finger01/n/n4551a5b4bb6d | `n4551a5b4bb6d` | **公開済(2026-09-29)** |
| ビバップの夜明け — Charlie Parker | https://note.com/shining_finger01/n/n3c57c2555f9a | `n3c57c2555f9a` | **公開済(2026-09-29)** |
| クール・ジャズの時代とChet Bakerの西海岸 | https://note.com/shining_finger01/n/n5cb685647f38 | `n5cb685647f38` | **公開済(2026-09-29)** |
| 2026年ジャズ新作アルバムの現在地 — Jon Batiste『Black Mozart』と山中千尋25周年 | https://note.com/shining_finger01/n/n289ad3de1b0b | `n289ad3de1b0b` | **公開済(2026-09-30)** |
| 「Tank!」から佐世保の喫茶店まで、アニメーションとジャズが出会う場所 | https://note.com/shining_finger01/n/n0893de9eb19f | `n0893de9eb19f` | **公開済(2026-09-29)** |
| Jon Batiste『Black Mozart』と山中千尋25周年、2026年のジャズ新作を聴く | https://note.com/shining_finger01/n/n8e7adda7fe72 | `n8e7adda7fe72` | **公開済(2026-09-29)** |
| Kamasi WashingtonとDinner Partyが拓く、スピリチュアルジャズの新潮流 | https://note.com/shining_finger01/n/n4e882973804f | `n4e882973804f` | **公開済(2026-09-30)** |
| スカーフ一枚で装いが変わる、2026年のスカーフスタイリング | https://note.com/shining_finger01/n/ndee7acba7533 | `ndee7acba7533` | **公開済(2026-09-30)** |
| B&W 685レビュー、黄色いケブラーコーンが鳴らす英国流の開放感 | https://note.com/shining_finger01/n/n4b561c4f324a | `n4b561c4f324a` | **公開済(2026-10-01)** |
| Cubase Pro 15のスコアエディターを読み解く、Doricoの譜面エンジンと15の新機能 | https://note.com/shining_finger01/n/ndf382a00e613 | `ndf382a00e613` | **公開済(2026-10-01)** |
| 『CUBASE 15 & 15 PRO ユーザーガイド』を手元に、4週間で1曲を仕上げる | https://note.com/shining_finger01/n/n09c4734ae7b5 | `n09c4734ae7b5` | **公開済(2026-10-01)** |
| 5つのアイテムで組むクラシックスタイル：ライトブルーのシャツとブラウンのサスペンダー | https://note.com/shining_finger01/n/nb2ef40ad13c4 | `nb2ef40ad13c4` | **公開済(2026-10-01)** |

**変換・投稿の追加仕様(2026-10-01)**:
- `convert-to-note.py` は figure のクレジットが `<figcaption>` の内側・直後どちらでも画像を拾う(以前は直後にある形式の図版を丸ごと削除していた)。画像を `<a href="https://www.amazon...">` で包んだ図版は、画像の後に `Amazonで見る: URL` の行を足す(note は画像にリンクを付けられないため)。
- `post-to-note.py` は `Amazonで見る: URL` の行を HTML リンクとしてクリップボード貼付する(`paste_link()`)。note はキー入力した URL を自動リンクしない。
- Markdown の表は note で表示できないので、`convert-to-note.py` が「- 1列目：2列目」(3列以上は「見出し 値 / …」)の箇条書きに変換する。
- ハッシュタグの `&` は除去する(`#B&W` が `#B` になっていた)。一度付いたタグは本文を書き直しても公開設定に残るので、公開設定画面の `[data-has-error] > button`(各タグ)内の `[aria-label="削除"]` で外す。

**noteアカウント**: urlname = `shining_finger01`、nickname = `SF0112`。**公開URLは `https://note.com/shining_finger01/n/<key>`**（nickname ではなく urlname を使う。nickname でアクセスすると404になる）。

**公開状態の確認方法(2026-09-29 実測)**:
- `GET https://note.com/api/v3/notes/<key>` が**ブラウザ内 fetch（`credentials:'include'`）なら取れる**（CORS制約に引っかかるため curl や requests からは不可。Playwright のページ内 evaluate で叩く）。返りの `status` が `published` / `is_published: true` なら公開済み、`note_url` フィールドで公開URLも得られる。
- 自分の記事は `https://note.com/notes` で「公開中」バッジ付き一覧になる。**`?type=draft` は下書き限定に効かない**（公開済みの記事も混ざる）。
- **公開済み記事は「公開に進む」ではなく「更新する」になる**ので、下書きか公開済みかの判定に使える。

**公開の手順に注意点(2026-09-29 実測・重要)**:
1. `公開に進む` を押すと **`/publish/` の公開設定画面に移動するだけ**で、まだ公開されていない。
2. 公開設定画面（`/publish/`）の**右上「投稿する」**を押すのが本番。押すと `note.com/like_reaction_setting?kind=recommend` などに遷移して公開が完了する。
3. **「投稿する」は `get_by_role` だと不安定**（要素が再描画されてdetachedになる）。**JSで要素の座標を取得して `page.mouse.click()` で押す**のが確実。
4. **ハッシュタグ（2026-09-29 実測・訂正）**: 公開した3記事とも、付いているタグは**記事内容を表すものだけ**だった（generic な自動提案タグ `#posts` `#github` 等は**付かなかった**）。実測値:
   - `n4551a5b4bb6d`: `#music` `#BlueNote` `#モダンジャズ` `#ハードバップ` `#artblakey` `#jazzmessengers`
   - `n3c57c2555f9a`: `#music` `#ビバップ` `#CharlieParker` `#DizzyGillespie` `#52ndStreet` `#1940年代のジャズ` `#MintonsPlayhouse`
   - `n5cb685647f38`: `#music` `#MilesDavis` `#ビバップ` `#chetbaker` `#クール・ジャズ` `#BirthOfTheCool` `#WestCoastJazz` `#1950年代のジャズ`

   ただし `#music` は全記事に入るので、記事固有のものを優先したいなら公開前に外す。**API のフィールド名は `title`/`tags` ではない**ので注意（`title` は `name`、タグは `hashtag_notes[].hashtag.name`）。
5. **`post-to-note.py` の `--publish` はこの2段自動化に修正済み(2026-09-29)**。`publish_note()` が「公開に進む」/「更新する」→ `/publish/` 待ち → 「投稿する」の座標クリックまで実行し、最後にブラウザ内 `fetch` で `GET /api/v3/notes/<key>` を叩いて `is_published` を検証してから公開URLを返す。**公開URLが返ってこなければ公開されていない**ので、その場合は手動で公開すること。
   - **下書きkeyの正規表現バグは同日修正済み**: 下書きkeyは `n` 始まり(例 `n0893de9eb19f`)だが `public_note_url()` のURL解析が `r"/notes/([0-9a-f]{12,})"` だったため `--publish` が公開URLを返せなかった。`publish_note()` の `re.search` を `r"/notes/([a-z0-9]{12,})"` に修正し、既存下書き `n0893de9eb19f` の公開 URL 取得を実測確認済み。
   - **既存下書きを公開 liberatingには `--publish` を使わない**: `post-to-note.py` は起動時に `editor.note.com/new` を開くため、下書き公開のために走らせると**新しい下書きがもう1件作られ二重投稿になる**。既存下書きを公開するときは `https://editor.note.com/notes/<key>/edit/` を直接開いて `publish_note(page)` を呼ぶ（2026-09-29、`n0893de9eb19f` の公開はこの経路で実施）。
6. **下書き削除の実測手順(2026-09-29)** — 下書き一覧(`https://note.com/notes?type=draft`)の行は、`…を編集`(`absolute inset-0` の透明オーバーレイ)Besides **`aria-label` を持つ2つ目のボタン(⋮、`aria-label` 空・`svg` あり)** を行メニューを開く。開いたメニューは `role="menuitem"` の `編集` / `複写` / `共有用リンクをコピー` / `削除`。`削除` を押すと **`[role="dialog"]` の確認ダイアログ**が出るので、そこで `削除` を押す。1件消すたびに一覧を再読込し、空になるまで繰り返す。
7. **空の下書きは一覧に出ない**: `editor.note.com/new` を開くと、タイトル・本文が空の下書き（key `n2b8ea38ece88` 等）が作られるが、**タイトルが空なので下書き一覧の行には現れない**。これは編集画面の右上 `その他`(`aria-haspopup="true"`) → `削除`（`class` に `text-text-danger` の `span`）→ 確認ダイアログの `削除` で消す。押すと `https://note.com/notes` に戻る。**`post-to-note.py` を1回動かすたびに空下書きが1件増えるので、作業後に `その他` → `削除` で掃除する**。
8. **削除済み記事キーの API 応答(2026-09-29 実測)**: 削除しても `GET /api/v3/notes/<key>` は HTTP 200 を返し、返りの `status` が **`deleted`** になる(`is_published: false`)。**404 にはならないので、削除判定は「一覧に現れるか」で行う**。


### はてなブログ→X自動投稿パイプライン(……**2026-09-29 完全削除**、再開禁止)

Xに自動投稿する様組は已終了。以下は履歴で、コードとタスクはすべて削除済み。

- **削除したファイル**: `scripts/x-autopost/` 全体。ジャズポスト用(`poster.py`/`post_jazz_tweet.py`/`jazz-posted.json`)、前回のフログプランスト(`db.py`/`feed_check.py`/`generate.py`/`scraper.py`/`main.py`/`seed_baseline.py`/`README.md`/`posts.db`/`requirements.txt`)、更に確認済みの口道レストファイル(`amazon_search_fetch.py`/`parse_amazon_html.py`/`fetch_carbonation.py`/`fetch_sakeware.py`/`fetch_bodum_image.py`)。
- **Pythonヴィンツュクルルートは`scripts/.venv/`に移動**。これは `post-to-note.py`(プレイツョード)と `extract-post-html.sh`(ハテナバンナー入れ)が使うので**残すない**。需要なバッケージは `playwright`/`greenlet`/`pyee` のみ。
- **引き済み元**: バランカーの裁っ紙と `run-claude-task.ps1` の `allowedTools`。
- **本章と同じことを求めてはこそそ**。X API 料金、Bot検知の困るなど、`pyautogui`/`pyperclip` でのOS入力シマュレーションなど、Claude クロードの模型選び(ハイカュ)など、Windows の cp932/`python` スタブの問題などは、**全部別紐として仍あるもので、利用する際には参照するだけ**。

## デプロイの仕組み

`main` に push すると `.github/workflows/hugo.yml` が Hugo でビルドして GitHub Pages に自動デプロイする。
ローカルでの確認は `hugo --minify` でビルド → `public/` を目視確認 → commit & push、の順で行っている。

**注意**: `hugo.toml` に `timeZone = 'Asia/Tokyo'` を設定済み。これが無いと当日日付の投稿がUTC基準で「未来の記事」判定され、`buildFuture = false` によりビルドから静かに除外されるバグを踏んだことがある(修正済みだが、他サイトで再現する可能性があるので記録)。

## サイト構成・カテゴリ(2026-09-16時点、固定ではない)

`hugo.toml` の `[menu]` で管理。カテゴリを追加したら記事の front matter (`categories: [...]`) とメニューの両方を更新すること。**このリストは今後のジャンル拡張に応じて増減・再編される前提**であり、既存カテゴリに合わないジャンルが来たら新カテゴリを切ってよい。

- `gear` — 機材レビュー(ハードウェア)
- `software` — DTMソフト・Tips
- `setup` — 制作環境公開
- `learning` — スクール・学習
- `whisky` — ウイスキー(音楽と無関係のジャンルもユーザー許可のもとで追加した実績あり)

## 記事の型その1:「5製品比較」フォーマット

いま実績があるのはこの形式だが、お題によっては単発テーマ記事など別の形式もありうる(その場合もリサーチ15サイト以上・文体・引用形式は共通ルールとして踏襲する)。

これまで作った記事(いずれも `content/posts/`):
- `daw-5choice-2026.md` — DAW 5本(Logic Pro / FL Studio / Ableton Live / Cubase / Fender Studio Pro)
- `sampler-5choice-2026.md` — サンプラー 5本(Kontakt 8 / Battery 4 / TAL-Sampler / UVI Falcon / Serato Sample)
- `midi-keyboard-5choice-2026.md` — MIDIキーボード 5本
- `audio-interface-5choice-2026.md` — オーディオI/O 5本
- `turntable-5choice-2026.md` — アナログターンテーブル 5本
- `scotch-whisky-5choice-2026.md` — スコッチウイスキー 5本
- `budget-whisky-10choice-2026.md` — コスパ重視の安ウイスキー10本(角瓶/ブラックニッカ クリア/トリスウイスキー/ジムビーム ホワイト/フォアローゼズ イエロー/バランタイン ファイネス/カティサーク/ホワイトホース ファインオールド/デュワーズ ホワイトラベル/ジョニーウォーカー レッドラベル、2026-09-17。5本ではなく10本の回だが型その1のフォーマットをそのまま踏襲)

**単発の製品深掘り記事(「記事の型その2」、下記参照)**:
- `scarlett-2i2-deep-dive-2026.md` — Focusrite Scarlett 2i2(4th Gen)
- `technics-sl1200mk7-deep-dive-2026.md` — Technics SL-1200MK7(ターンテーブル比較記事の特集5機種、2026-09-17追加)
- `at-lp120xusb-deep-dive-2026.md` — Audio-Technica AT-LP120XUSB(同上)
- `rega-planar3-deep-dive-2026.md` — Rega Planar 3(同上)
- `debut-carbon-evo-deep-dive-2026.md` — Pro-Ject Debut Carbon EVO(同上)
- `sony-pslx3bt-deep-dive-2026.md` — Sony PS-LX3BT(旧PS-LX310BT)(同上)
- `suntory-kakubin-deep-dive-2026.md` / `black-nikka-clear-deep-dive-2026.md` / `suntory-trys-deep-dive-2026.md` / `jim-beam-white-deep-dive-2026.md` / `four-roses-yellow-deep-dive-2026.md` / `ballantines-finest-deep-dive-2026.md` / `cutty-sark-deep-dive-2026.md` / `white-horse-fineold-deep-dive-2026.md` / `dewars-white-label-deep-dive-2026.md` / `johnnie-walker-red-deep-dive-2026.md` — `budget-whisky-10choice-2026.md` 特集10本の深掘り(2026-09-17、リスト記事と同時に執筆)。**タイトルは「全機能解剖」ではなく「{製品名}の味と仕様 — {サブタイトル}」にする**(ウイスキーに「機能」は無いため)。新ジャンルでは対象の性質に合わせてこの部分の語彙も調整してよい。**2026-09-29に「隅から隅まで味わい尽くす」形式からは一括で撤退済み(下記タイトル規則7番)**。
- **ニッカ フロム・ザ・バレルはリサーチ済みだが不採用**: 2026-09-17時点で実勢価格が値上がりし500mlで4,000〜6,000円台まで高騰していたため、「安価」を謳う本リストの趣旨と合わず、代わりにジョニーウォーカー レッドラベルを採用した。同様の「トレンドで名前が挙がったが実際に調べたら前提と合わなかった」ケースなので、対象を機械的に採用せず、リサーチ結果を見て都度取捨選択すること。

**2026-09-17、ユーザー指示「比較記事で特集している製品それぞれの詳細レビュー記事を書いて」**: 比較記事1本につき、特集製品ぶんの単発深掘り記事(「記事の型その2」フォーマット)を追加で書く、というパターンが発生した。今後も同様の指示があれば、対象の比較記事から製品名・ASIN・画像パスをそのまま流用し、各製品にAgent(general-purpose)を並列起動して個別に深掘りリサーチ(最低10サイト)した上で執筆する。画像・ASINは使い回すため新規ダウンロードは不要。

各記事は共通のフォーマットで作っている:

1. **リサーチ**: 5製品それぞれについて、Agent(general-purpose)を並列起動して最低8〜10サイトずつ(合計50サイト以上)調査させる。日本語DTM/レビューブログ、海外フォーラム(KVR/Gearspace/Reddit等)、公式サイトを横断。各エージェントに軸別スコア(1〜5)・引用可能な一言(出典URL付き)・トレンド情報を構造化して返させる。
2. **評価軸(5軸)は製品カテゴリに合わせて設計し直すこと**。ソフトウェアの軸をハードウェアにそのまま流用しない(過去にこれをやって「学習コスト」「制作速度」がターンテーブル記事で不自然と指摘されたことがある)。
   - ソフトウェア(DAW/サンプラー): 学習コスト / 打ち込み・編集 / 制作速度 / 拡張性 / 安定性
   - ハードウェア全般: 学習コスト→**セットアップ**、安定性→**耐久性** に読み替える
   - MIDIキーボード: セットアップ / 演奏性 / **DAW連携** / 拡張性 / 耐久性
   - オーディオI/O: セットアップ / 操作性 / **録音開始** / 拡張性 / 耐久性
   - ターンテーブル: セットアップ / 操作性 / **音質**(←「手軽さ」はセットアップと意味が被るため廃止) / 拡張性 / 耐久性
   - ウイスキー(全く別ジャンルなので軸も総入れ替え): 飲みやすさ / 味わいの複雑さ / コストパフォーマンス / 飲み方の幅 / 入手安定性
   - 新しいジャンルをやるときは、この5パターンを機械的に流用せず、対象の性質に合った軸を都度考えること。
   - **評価軸を紹介する一文で「いつもの」「おなじみの」「今回も」「前回と同じ」のような、過去記事との使い回しを匂わせる表現は使わない(2026-09-18、ユーザー指示)**。例:「軸は今回もおなじみの5つを〜」「軸は前回と同じ考え方を踏襲しつつ〜」は禁止。実際には過去記事と似た発想で軸を組み直していても、その記事単体で完結した書き方にする(例:「軸は、〜という発想で5つに整理した」のように、他記事の存在を前提にしない言い方)。
3. **レーダーチャート**: Python/Node.jsがこの環境に入っていない前提で、`scripts/radar-chart.awk` で直接SVGを生成している(bashのawkコマンドで実行可能)。
   ```bash
   awk -v TITLE="製品名" -v COLOR="#4C6EF5" -v SCORES="4,4,4,3,4" \
       -v LAB0="セットアップ" -v LAB1="操作性" -v LAB2="音質" -v LAB3="拡張性" -v LAB4="耐久性" \
       -f scripts/radar-chart.awk > static/images/radar/product-slug.svg
   ```
   色は5製品で被らないカテゴリカルパレットを使う(例: `#4C6EF5` `#F76707` `#2F9E44` `#E03131` `#7048E8`)。出力先は `static/images/radar/`、記事からは `/images/radar/xxx.svg` で参照。
4. **文体(2026-09-16制定 → 2026-09-18マイルド化)**: 旧ルールは「**太宰治型の自嘲 × 夏目漱石型の皮肉**」だったが、**皮肉が鼻につく・きつすぎるとの指摘を受けて全面的にマイルド化した(2026-09-18)**。過去記事も含め全面的にこの新しい文体で統一している。
   - 皮肉・自嘲は**完全に禁止ではないが、量も強度も大幅に控える**。1記事(5製品分)を通して、軽い自虐や軽いユーモアは1〜2箇所程度に留め、毎段落・毎製品で入れない。「卑屈すぎて笑える」レベルの強い自己卑下、業界やトレンド・宣伝文句への皮肉たっぷりな観察・慇懃無礼な言い回しは書かない。
   - 基調は**素直で丁寧な一人称レビュー**。「〜だと思う」「〜と感じた」「〜が気に入っている」「〜は少し残念だった」のように、率直でフラットな評価を積み重ねる。良い点はふつうに褒め、弱点もふつうに指摘すればよい——わざわざ皮肉や自虐でオブラートに包む必要はない。
   - 完全に無機質・機械的な文章にする必要はなく、多少の人間味・親しみやすさは残してよい(「なるほど」「正直ありがたい」「ここは好みが分かれそう」程度の軽い所感はOK)。ただし「情けない自分語り」や「乾いた皮肉で切り込む」ようなスタイルの型として繰り返し使うのはNG。
   - 製品の性能・スペック・実際の使用感は正確に、しっかり伝えることを最優先する。
   - この文体変更は2026-09-18に全7記事へ適用済み(過去記事の皮肉・自嘲表現を薄める修正)。
   - **他サイトの記事への引用リンクは一切貼らない(2026-09-17、ユーザー指示で従来ルールを撤回)**。旧ルールだった「「」で挟んでmarkdownリンクを貼る」引用形式(`「[引用文](URL)」`)は**廃止**。かつてはこの形式で外部レビュー記事の一言を出典付きで引用していたが、これをやめる。
   - **「あるレビューでは〜」「海外フォーラムでは〜という声も」「〜と評されている」のような、他の記事・レビュー・第三者の声を引き合いに出す言い回しも禁止(2026-09-17)**。record/研究過程を連想させるだけでなく、他人の意見を借りてくる姿勢そのものが「主観的レビュー」というこの記事の建て付けと矛盾するため。
   - 代わりに、**筆者自身の一人称の主観的な感想・評価として書く**。「〜と感じた」「〜だと思う」「〜には正直がっかりした」のように、リンクや出典なしで、自分の体験・印象として言い切る文体に統一する。事実(スペック・仕様・価格等)は出典なしでそのまま地の文で書いてよいが、「良い/悪い」の評価・感想の部分は必ず筆者の主観として書く。
   - **旧ルール(廃止済み・参考): 英語ソースは訳してから引用**というルールがあったが、上記の通り引用形式自体を廃止したため意味を失った。英語の海外情報を参考にすること自体は禁止していないが、それを「引用」の形で出典付きに見せず、あくまで筆者が理解した内容を自分の言葉(日本語)で語ること。
   - 事実誤認に注意 — リサーチで「トレンドとして挙げた製品が実は存在しない/旧モデルだった」というケースが複数回あった(例: 「Battery 5」は2026年時点で未発売→実在する Battery 4 に差し替えて執筆、Studio One→Fender Studio Pro改名、Steinberg UR22C→YAMAHA URX22C改名、Sony PS-LX310BTは生産終了で後継機PS-LX3BT/LX5BTに言及)。こういう「trending」指定は鵜呑みにせず必ず現行モデルかどうか確認する。
   - **「記事を自動生成している」と分かるような表現は使わない(2026-09-16、ユーザー指示)**。「(60以上の)ページを読み込んで」のような、人間の読書行為というよりプログラムのデータ処理を連想させる言い回しが該当。「読みあさって」「目を通して」「読み漁って」のような、人間が実際に読んだと感じられる自然な表現に置き換えること。同様に「情報を収集した」「検索した結果」「エージェント」「生成した」等、AI/自動化を匂わせる語彙全般を避ける。リサーチの量や執念は書いてよいが、あくまで「筆者本人が読んだ」体で書く。
   - **製品の所持について、肯定・否定どちらの方向にも言及しない(2026-09-16制定 → 2026-09-17に改訂)**。記事で取り上げる製品は「筆者が実際に持っている」という前提で書くが、これは暗黙の前提であって、**わざわざ「持っている」「買った」「ライセンスを買い揃えた」のように所持を主張する一文を入れる必要はない**。同様に「買ってもいないのに」「まだどれも買っていない」のような未所持ネタも禁止(こちらは2026-09-16から変更なし)。要するに、所持の話題そのものに触れない。自嘲のネタにしたい場合は所持と無関係な切り口(決断力のなさ、腕前の低さ、時間の使い方等)を使う。
   - **記事の情報源・リサーチ方法に関する記述は一切しない(2026-09-17、ユーザー指示)**。「〜のレビュー・フォーラム・公式資料に目を通して」「〜のページを読みあさって」「調べ方だけは変えなかった」のような、外部サイトを調査・参照したことをほのめかす表現は書かない(導入部・結びとも)。理由は2つ: (1) 上記の「製品は所持している前提」と矛盾する(所有者が今さら60サイトも読み込む必要はない)。(2) 情報源についての言及そのものが「記事を作るプロセス」を意識させてしまう。記事末尾の「本記事の引用は、記事中にリンクした各サイトの記述を参考にしています」のような締めの一文も同様の理由で削除済み・今後も付けない。ただし本文中の個別の引用(「[引用文](URL)」形式でのリンク付き引用)自体は今まで通り使ってよい——禁止なのはあくまで「情報源全体に関するメタ的な言及」。
   - **「実際に◯◯してみた」という言い回しは使わない(2026-09-18、ユーザー指示)**。「実際に使い込んで、その謳い文句がどこまで本当か確かめてみた」「実際に飲み比べて、その謳い文句を確かめてみた」のような、導入部の定型句として毎記事使っていたパターンを禁止する。同様に「〜してみた」で締める体験談風の言い切りも避け、素直に「〜を比較する」「〜を見ていく」のような言い方にする。
5. **まとめ表**: 各記事の末尾、結論(「それで、結局どれを選べばいいのか」)の直前に `## まとめ` という見出し(2026-09-18改訂: 従来の`## まとめ一覧`から「一覧」を削除)で、製品を縦・評価軸を横に並べたMarkdownテーブルを入れる(ユーザー指定のフォーマット)。テーブルが横に長くなるので `assets/css/extended/tables.css` で横スクロール対応済み。**製品名のセルはAmazonアソシエイトリンクにする(2026-09-18、ユーザー指示)**: `| [製品名](https://www.amazon.co.jp/dp/{ASIN}?tag=nakimoto1-22) | 4 | ... |` の形式。Amazonに商品が無い場合(公式サイトのみの製品)は、その製品セクションで使っている公式サイトのURLをリンク先にする。
5b. **アフィリエイト画像リンクの配置場所とデザイン(2026-09-17制定 → 2026-09-18再改訂・必須)**: **記事冒頭にまとめて並べない**。各製品の見出し(`## 製品名 — 一言`)の直後・レーダーチャート画像の前に、その製品1個ぶんだけのリンクを差し込む(5製品比較記事なら記事内5箇所、10製品なら10箇所に分散)。**デザインは固定サイズの横長バナー型リンク`.product-banner`**(2026-09-18改訂: 画像のみのフルワイドリンク`.product-links`から変更。型その2の単発深掘り記事で先に採用した`.product-banner`を型その1の比較記事にも統一適用)。`assets/css/extended/product-links.css`で定義、幅468px×高さ120px固定、左に商品写真・右に商品名+「Amazonで見る」CTAテキスト:
   ```markdown
   ## 製品名 — 一言

   <a class="product-banner" href="https://www.amazon.co.jp/dp/{ASIN}?tag=nakimoto1-22">
   <img src="/images/products/{slug}.png" alt="{製品名}">
   <span class="product-banner-info">
   <span class="product-banner-name">{製品名}</span>
   <span class="product-banner-cta">Amazonで見る →</span>
   </span>
   </a>

   ![{製品名}の使いやすさレーダーチャート](/images/radar/{slug}.svg)

   - 学習コスト 4 / ...
   ```
   - **旧`.product-links`/`.product-link`クラス(画像のみのフルワイドリンク)は型その1・型その2どちらでも新規に使わない**。ただしCSS自体は後方互換のため`product-links.css`に残してある。
   - 画像は `static/images/products/` に保存。各社**公式サイト**のproduct/heroイメージ(og:imageタグや直接のimgタグから取得)を1商品につき1枚ダウンロードして使う。Amazon商品ページの画像は使わない(規約上グレーなため)。
   - Amazonに商品が無い場合は `href` を公式サイトのURLにする(タグなし)。この場合、直後に「(Amazonに単体販売の取り扱いなし)」等の一行注記を添える。
   - **記事末尾の`🛒 [Amazonで見る(...)](...)`という文字だけのリンクは廃止**。バナーリンクが同じ役割を果たすので二重に置かない。
   - 新しい記事を書くたびに、各製品セクションの見出し直後にこのブロックを追加すること。
   - **はてなブログ側のバナー(2026-09-19、ユーザー指示で修正)**: はてなにはこのサイトのCSSが効かず、何もしないと`<img>`が原寸の特大表示になる。対策として、はてなに出すHTMLは`scripts/extract-post-html.sh`が`scripts/hatena_banner.py`を通して、バナーの`<a>`・`<img>`・各`<span>`に**インラインstyleと`width="120" height="120"`**を付与する(サイトと同じ468×120px、画像120×120px。記事のmarkdown側は`.product-banner`のまま変更不要)。**新規投稿・更新では必ず`extract-post-html.sh`経由でHTMLを作ること(手書きのHTMLを`post-to-hatena.sh`に渡さない)**。公開済みのはてな記事を全件まとめて再同期したいときは`scripts/.venv/Scripts/python.exe scripts/fix-hatena-banners.py`(ドライラン)→`--apply`(冪等・タイトル等は変更しない)。2026-09-19に既存40記事を修正済み。
   - **2026-09-18時点で全ての既存記事(型その1の7本・型その2の16本、計40+32=72箇所)にこの`.product-banner`デザインを適用済み**。
6. タイトルに「五番勝負」のような対決煽り文句は**使わない**(ユーザーが明示的に削除を指示した)。
   - **ありきたりな定型句もタイトルに使わない(2026-09-29、ユーザー指示)**。特に**「{対象}を隅から隅まで味わい尽くす」**(および「隅から隅まで」「味わい尽くす」の変形)は全面禁止**。同じ型をそのまま数十本に貼り付けただけ&$%に見え、1本1本に中身が無い。
7. **タイトルは記事ごとに言い回しを変える(2026-10-01、ユーザー指示「タイトルの言い回しが単調」で全面改訂)**。以前は「{製品名}を全機能解剖 — 」「{対象}の味と仕様 — 」「{対象}の仕様と使い方 — 」「{テーマ}の現在地 — 」「{ジャンル}を{数}本徹底比較 — 」という固定の型+「 — 詩的サブタイトル」で統一していたが、数十本並ぶと単調だという指摘を受け、**2026-10-01に公開済み90本すべてのタイトルを刷新した**(OG画像90枚再生成、本文中の旧タイトル参照も置換、はてな・noteも同期)。
   - **上記の固定の型(全機能解剖/味と仕様/仕様と使い方/の現在地/徹底比較)は新規に使わない**。「 — 」で前後に分ける形も多用しない。
   - 1本ごとに、その記事でいちばん伝えたい切り口から書く。書き方は混ぜる: 問いかけ(「バランタイン ファイネスはなぜ世界2位のスコッチになれたのか」)、製品名+一言の主張(「Rega Planar 3が半世紀守る「軽さと剛性」の設計思想」)、情景から入る(「禁酒法時代を生き延びた甘口、カナダドライ ジンジャーエール」)、数字を入れる(「Newportは72年目、Montreuxは60年目。2026年のジャズフェスティバルを巡る」)、使い方を示す(「廣田硝子のちろりで燗をつける、大正の灯りを写した耐熱ガラス」)。
   - **直近の記事のタイトルと同じ構文を続けない**。書く前に `content/posts/` の最近のタイトルを数本見て、構文が重ならないようにする。
   - 何を扱う記事か(製品名・テーマ)は必ず入れ、検索キーワードは先頭30〜35文字に収める。比較記事は件数(「5台比較」など)を入れる。
   - **2026-09-29 に過去記事54本のタイトルから「隅から隅まで味わい尽くす」を撤去済み**。以后この表現を新規に使わないこと。

## 記事の型その2:「単発製品深掘り」フォーマット

1製品だけを掘り下げる形式。既存の比較記事(型その1)で特集した製品について、後から個別に深掘り記事を追加するケース(2026-09-17、ユーザー指示)と、最初から単発で書くケース(Scarlett 2i2の初回テスト投稿)の両方がある。

これまで作った記事は「ロードマップ」セクション内の「単発の製品深掘り記事」一覧を参照。

1. **リサーチ**: 対象1製品につきAgent(general-purpose)を1体起動し、最低10サイト以上を調査させる。比較記事のときと同様、海外(英語)ソースを優先的に含める。比較記事からの追加執筆であれば、製品名・ASIN・商品画像パス(`static/images/products/`)は使い回してよく、新規ダウンロードは不要。
2. **見出し構成**: 5軸評価やレーダーチャートは使わない(1製品のみのため比較の意味がない)。代わりに、製品の側面ごとに見出しを切る(例: 筐体・外観、駆動方式、操作系、接続性、価格・現行性など、対象に応じて自由に設計する)。
3. **アフィリエイト画像リンク(2026-09-18再改訂)**: 記事全体に**2箇所**分散して配置する(3箇所→2箇所に変更。目安は「序文直後」と「価格・現行性など購入判断に近いセクションの前後」の2箇所)。**デザインも変更**: 型その1で使っている`.product-links`(画像のみのフルワイドリンク)ではなく、**固定サイズの横長バナー型リンク**`.product-banner`(`assets/css/extended/product-links.css`で定義、幅468px×高さ120px固定、左に商品写真・右に商品名+「Amazonで見る」CTAテキスト)を使う。型その1(5/10製品比較記事)の`.product-links`は従来通り画像のみのフルワイドリンクのまま変更しない——**この変更は型その2(単発深掘り記事)限定**。マークアップ:
   ```html
   <a class="product-banner" href="https://www.amazon.co.jp/dp/{ASIN}?tag=nakimoto1-22">
   <img src="/images/products/{slug}" alt="{製品名}">
   <span class="product-banner-info">
   <span class="product-banner-name">{製品名}</span>
   <span class="product-banner-cta">Amazonで見る →</span>
   </span>
   </a>
   ```
   ASINと画像パスは冒頭のものを使い回してよい。**2026-09-18時点で全16本の型その2記事(音響機材6本+ウイスキー10本)にこの新デザイン・2箇所配置を適用済み**。
4. **文体・引用ルールは型その1と完全に共通**: 皮肉・自嘲はマイルドに(1記事1〜2箇所まで)、他サイトへの引用リンク・第三者への意見の帰属(「あるレビューでは」等)・特定の媒体名(What Hi-Fi誌、Stereophile誌等)を主観の裏付けとして名指しすることも禁止——リサーチで得た情報は必ず筆者自身の一人称の感想として書き直す。「実際に◯◯してみた」も禁止。所持については触れない。情報源・リサーチ方法への言及もしない。
5. **タイトル**: 型その1の7番を参照(記事ごとに言い回しを変える。「全機能解剖」の型は2026-10-01に廃止)。
6. **後継機・生産終了への注意**: 特集製品がすでに生産終了・後継機に切り替わっている場合(例: Pro-Ject Debut Carbon EVO→Debut EVO 2、Sony PS-LX310BT→PS-LX3BT)は、タイトルや本文で現行モデルとの関係を明記し、比較記事側の表記と矛盾しないようにする。

## トップページ(検索・フィルタ機能)

`layouts/index.html` でテーマの標準ホームページを完全に上書きしている。実装済み機能:
- キーワード全文検索(タイトル+本文、ヒット箇所ハイライト)
- カテゴリ絞り込み(チップボタン、`hugo.toml` の `[menu]` に合わせて `CATEGORY_LABELS` オブジェクトで日本語ラベルに変換)
- 並び替え(新着順/古い順/**閲覧数順**)

データソースは `layouts/index.json`(テーマ標準の `index.json` を上書きし、`date` `categories` `key` フィールドを追加)。`key` は `kingsworksub-jpg-studionotes-{ファイル名スラッグ}` の形式。

**閲覧数カウンター**: 無料の公開カウンターAPI [countapi.mileshilliard.com](https://countapi.mileshilliard.com/)(旧 countapi.xyz の後継、認証・登録不要、名前空間なしでキー文字列のみ)を使用。
- 記事ページ側: `layouts/partials/extend_head.html` で `.../api/v1/hit/{key}` を叩いてカウントを増やし、`.post-meta` に閲覧数を追記。
- トップページ側: `.../api/v1/get/{key}` で現在値を読み取り(インクリメントしない)、一覧の表示・ソートに使用。
- このサービスが将来落ちても、閲覧数が0表示になるだけでサイト自体は壊れない設計。

## マネタイズ状況(進行中)

- **Amazon アソシエイト**: 登録・承認済み。トラッキングID(アソシエイトID)は **`nakimoto1-22`**。リンク形式: `https://www.amazon.co.jp/dp/{ASIN}?tag=nakimoto1-22`。
  - 2026-09-16時点で、全6記事・30商品に商品リンクを挿入済み(各商品セクション末尾、`---` 区切りの直前に `🛒 [Amazonで見る(製品名)](...)` の形式で設置)。
  - うち25本はAmazon.co.jpの実商品ページへのアフィリエイトリンク。残り5本(Logic Pro、Fender Studio Pro、Battery 4、TAL-Sampler、UVI Falcon)はAmazon.co.jpに一致する商品ページが無い/バージョンが古いため、`🛒 [公式サイトで見る(製品名)](...)` として公式サイトへのリンクにしてある(タグなし、アフィリエイト対象外)。
  - ターンテーブルのSony PS-LX310BTは生産終了のため後継機 PS-LX3BT のAmazonリンクに差し替え済み。
  - まだ本承認(180日以内に3件の適格販売)は達成していない可能性がある。ステータスはaffiliate.amazon.co.jpの管理画面で確認。
- **Google AdSense**: 未申請。今後の予定。
- **プライバシーポリシー/運営者情報ページ**: `content/privacy-policy.md` / `content/operator.md` を作成済み、フッターからリンク。Amazonアソシエイト参加者である旨を明記済み(承認後に「予定」→「参加者です」に文言更新済み)。

## サイト運営タスク(コンテンツ以外)

- Amazon アソシエイトの本承認状況(3件の適格販売)を確認
- Google AdSense申請
- 記事数を増やす(記事数が多いほどAmazon審査・AdSense審査に有利)
- 新しい記事を書いたら、その記事にも同じ形式(`🛒 [Amazonで見る(製品名)](https://www.amazon.co.jp/dp/{ASIN}?tag=nakimoto1-22)`)でリンクを追加すること
- 「5製品比較」形式で書く場合は、このドキュメントの「評価軸」セクションの考え方(カテゴリごとに軸を作り直す)を踏襲すること
