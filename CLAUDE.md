# Studio Notes ブログ — プロジェクトメモ

音響機材・DTM・音楽制作ソフト(+雑多に音楽以外のジャンルも)のレビューブログ。
Hugo (PaperModテーマ) + GitHub Pages + GitHub Actions で構築した静的サイト。

- 公開URL: https://kingsworksub-jpg.github.io/
- リポジトリ: https://github.com/kingsworksub-jpg/kingsworksub-jpg.github.io
- ローカルパス: `C:\Users\norio\Projects\kingsworksub-jpg.github.io`

## デプロイの仕組み

`main` に push すると `.github/workflows/hugo.yml` が Hugo でビルドして GitHub Pages に自動デプロイする。
ローカルでの確認は `hugo --minify` でビルド → `public/` を目視確認 → commit & push、の順で行っている。

**注意**: `hugo.toml` に `timeZone = 'Asia/Tokyo'` を設定済み。これが無いと当日日付の投稿がUTC基準で「未来の記事」判定され、`buildFuture = false` によりビルドから静かに除外されるバグを踏んだことがある(修正済みだが、他サイトで再現する可能性があるので記録)。

## サイト構成・カテゴリ

`hugo.toml` の `[menu]` で管理。カテゴリを追加したら記事の front matter (`categories: [...]`) とメニューの両方を更新すること。

- `gear` — 機材レビュー(ハードウェア)
- `software` — DTMソフト・Tips
- `setup` — 制作環境公開
- `learning` — スクール・学習
- `whisky` — ウイスキー(音楽と無関係のジャンルもユーザー許可のもとで追加した実績あり)

## 記事の型:「5製品比較」フォーマット

これまで作った記事(いずれも `content/posts/`):
- `daw-5choice-2026.md` — DAW 5本(Logic Pro / FL Studio / Ableton Live / Cubase / Fender Studio Pro)
- `sampler-5choice-2026.md` — サンプラー 5本(Kontakt 8 / Battery 4 / TAL-Sampler / UVI Falcon / Serato Sample)
- `midi-keyboard-5choice-2026.md` — MIDIキーボード 5本
- `audio-interface-5choice-2026.md` — オーディオI/O 5本
- `turntable-5choice-2026.md` — アナログターンテーブル 5本
- `scotch-whisky-5choice-2026.md` — スコッチウイスキー 5本

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
3. **レーダーチャート**: Python/Node.jsがこの環境に入っていない前提で、`scripts/radar-chart.awk` で直接SVGを生成している(bashのawkコマンドで実行可能)。
   ```bash
   awk -v TITLE="製品名" -v COLOR="#4C6EF5" -v SCORES="4,4,4,3,4" \
       -v LAB0="セットアップ" -v LAB1="操作性" -v LAB2="音質" -v LAB3="拡張性" -v LAB4="耐久性" \
       -f scripts/radar-chart.awk > static/images/radar/product-slug.svg
   ```
   色は5製品で被らないカテゴリカルパレットを使う(例: `#4C6EF5` `#F76707` `#2F9E44` `#E03131` `#7048E8`)。出力先は `static/images/radar/`、記事からは `/images/radar/xxx.svg` で参照。
4. **文体**: 小説家・三浦しをん風。製品を「人となり」に例えて語る、温かみとユーモアのある口調。引用は「」で挟んで出典に markdown リンクを貼る形式(`「[引用文](URL)」`)。事実誤認に注意 — リサーチで「トレンドとして挙げた製品が実は存在しない/旧モデルだった」というケースが複数回あった(例: 「Battery 5」は2026年時点で未発売→実在する Battery 4 に差し替えて執筆、Studio One→Fender Studio Pro改名、Steinberg UR22C→YAMAHA URX22C改名、Sony PS-LX310BTは生産終了で後継機PS-LX3BT/LX5BTに言及)。こういう「trending」指定は鵜呑みにせず必ず現行モデルかどうか確認する。
5. **まとめ表**: 各記事の末尾、結論(「それで、結局どれを選べばいいのか」)の直前に `## まとめ一覧` という見出しで、製品を縦・評価軸を横に並べたMarkdownテーブルを入れる(ユーザー指定のフォーマット)。テーブルが横に長くなるので `assets/css/extended/tables.css` で横スクロール対応済み。
6. タイトルに「五番勝負」のような対決煽り文句は**使わない**(ユーザーが明示的に削除を指示した)。「DAW — 2026年、机の上のオーケストラを誰に任せるか」のように「主題 — 詩的なサブタイトル」の形にしている。

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

- **Amazon アソシエイト**: ユーザーが登録手続き済み(2026-09-16時点)。アソシエイトID(トラッキングタグ)発行待ち。IDが分かり次第、以下の商品リンクを各記事に埋め込む予定 — 6記事・約30商品ぶんのAmazon.co.jp商品URL(ASIN)は調査済み(会話ログ参照、または次回リサーチし直し)。リンク形式: `https://www.amazon.co.jp/dp/{ASIN}?tag={アソシエイトID}`。
  - DAW/サンプラーの一部(Logic Pro、Fender Studio Pro、Battery 4、TAL-Sampler)はAmazon.co.jpに直販ページが無いため、公式サイトへのリンクになる(アフィリエイト対象外)。
  - ターンテーブルのSony PS-LX310BTは生産終了のため後継機 PS-LX3BT のAmazonリンクに差し替え済み。
- **Google AdSense**: 未申請。今後の予定。
- **プライバシーポリシー/運営者情報ページ**: `content/privacy-policy.md` / `content/operator.md` を作成済み、フッターからリンク。Amazon審査対策として個人情報を含まない形(ブログ名義・GitHub Issue連絡先)で作成。

## 次にやること候補

- Amazon アソシエイトIDが判明したら、調査済みリンクを全記事に一括挿入
- Google AdSense申請
- 記事数を増やす(Amazonアソシエイトの本承認条件: 180日以内に3件の適格販売。記事数は多いほど有利)
- 新ジャンルの記事を作る場合も、このドキュメントの「評価軸」セクションの考え方(カテゴリごとに軸を作り直す)を踏襲すること
