# ゼロIMP記事 分類と内部リンク／URL検査計画

- 生成: 2026-11-20 12:49 JST
- 基準: 直近30日 page単位 SC（`scripts/p0-sc.csv`）に載らない公開記事
- 対象: **250本** / 公開記事 271本（IMPあり 21本）
- URL検査: `scripts/sc-inspect-articles.py` / 結果 `data/sc-inspection-results.json`
- sitemap.xml 収録: 271/271件（未収録でも検索に出ない原因にはならない）

## 分類内訳

| 分類 | 件数 |
|---|---:|
| 未インデックス（未検出） | 240 |
| インデックス済み・クエリ無し | 8 |
| 未インデックス（クロール済み） | 2 |

| 優先度 | 件数 | 意味 |
|---|---:|---|
| P1 | 47 | 未インデックス＋内部リンク候補＋商品リンクあり（最初に対応） |
| P2 | 8 | 未インデックス＋内部リンク候補あり |
| P3 | 8 | インデックス済みだがクエリ無し（内部リンクで再活性化） |
| P4 | 0 | 対象外（noindex / リダイレクト / 404） |
| 保留 | 187 | 未インデックスだが関連リンク元候補なし（別途カテゴリ導線が必要） |

## 対応方針

1. P1/P2 の記事へ、IMPのある上位記事から内部リンクを1〜2本追加する（下表の `link_sources` を参照）。
2. 内部リンク追加後、Search Console のURL検査で「インデックスに送信」を手動実行する。
   - Indexing API は `GOOGLE_INDEXING_CREDENTIALS` 未登録のため自動通知は無効。
3. P3 はタイトル／description を page 単位の近縁記事に寄せてから内部リンクを追加する。
4. P4 は sitemap と `aliases` を見直し、必要なら noindex を外す。

## 内部リンク追加計画（P1/P2 上位30件）

| 追加先（ゼロIMP） | 追加元（IMPあり） | 共通トークン | 追加元IMP |
|---|---|---|---:|
| `cafe-jazz-lounge-piano-2026` | `jazz-festivals-2026` | jazz | 21 |
|  | `piano-practice-apps-3choice-2026` | piano | 11 |
| `2026-jazz-new-albums-jon-batiste-chihiro-yamanaka` | `jazz-festivals-2026` | jazz | 21 |
|  | `jazz-style-fashion-revival-2026` | jazz | 7 |
| `hammond-b3-jazz-organ-2026` | `jazz-festivals-2026` | jazz | 21 |
|  | `jazz-style-fashion-revival-2026` | jazz | 7 |
| `jazz-fusion-1970s-weather-report` | `jazz-festivals-2026` | jazz | 21 |
|  | `jazz-style-fashion-revival-2026` | jazz | 7 |
| `jazz-instruments-guide` | `jazz-festivals-2026` | jazz | 21 |
|  | `jazz-style-fashion-revival-2026` | jazz | 7 |
| `jazz-listening-guide-2026` | `jazz-festivals-2026` | jazz | 21 |
|  | `jazz-style-fashion-revival-2026` | jazz | 7 |
| `jazz-masterpieces-beginner` | `jazz-festivals-2026` | jazz | 21 |
|  | `jazz-style-fashion-revival-2026` | jazz | 7 |
| `jazz-style-menswear-2026` | `jazz-style-fashion-revival-2026` | jazz, style | 7 |
|  | `jazz-festivals-2026` | jazz | 21 |
| `jazz-vocal-phrasing-guide-2026` | `jazz-festivals-2026` | jazz | 21 |
|  | `jazz-style-fashion-revival-2026` | jazz | 7 |
| `modern-spiritual-jazz-2026` | `jazz-festivals-2026` | jazz | 21 |
|  | `jazz-style-fashion-revival-2026` | jazz | 7 |
| `nea-jazz-masters-2026` | `jazz-festivals-2026` | jazz | 21 |
|  | `jazz-style-fashion-revival-2026` | jazz | 7 |
| `coca-cola-zero-deep-dive-2026` | `green-cola-deep-dive-2026` | cola | 10 |
|  | `mitsuya-cider-zero-deep-dive-2026` | zero | 2 |
| `sony-ecm-ax10-spatial-mic-2026` | `sony-pslx3bt-deep-dive-2026` | sony | 23 |
|  | `condenser-mic-5choice-2026` | mic | 8 |
| `statement-hat-trend-2026` | `statement-hat-trends-autumn-2026` | hat, statement | 4 |
|  | `jazz-shoes-trend-2026` | trend | 2 |
| `adult-piano-learning-2026` | `piano-practice-apps-3choice-2026` | piano | 11 |
| `bottled-cider-5choice-2026` | `mitsuya-cider-zero-deep-dive-2026` | cider | 2 |
| `budget-whisky-10choice-2026` | `taiwan-india-whisky-climate-2026` | whisky | 6 |
| `canadian-whisky-rye-4choice-2026` | `taiwan-india-whisky-climate-2026` | whisky | 6 |
| `classic-french-style-revival-2026` | `jazz-style-fashion-revival-2026` | style | 7 |
| `craft-cola-spice-syrup-2026` | `green-cola-deep-dive-2026` | cola | 10 |
| `crystal-spark-ramune-deep-dive-2026` | `crystal-spark-grape-deep-dive-2026` | crystal, spark | 2 |
| `dodecamin-zero-sakebitai-deep-dive-2026` | `mitsuya-cider-zero-deep-dive-2026` | zero | 2 |
| `dynamic-mic-5choice-2026` | `condenser-mic-5choice-2026` | mic | 8 |
| `ear-training-one-week` | `one-room-streaming-setup-2026` | one | 1 |
| `fender-studio-pro-8-studio-one-2026` | `one-room-streaming-setup-2026` | one | 1 |
| `guitar-recording-amp-sim-setup` | `one-room-streaming-setup-2026` | setup | 1 |
| `icy-spark-canada-dry-lemon-deep-dive-2026` | `crystal-spark-grape-deep-dive-2026` | spark | 2 |
| `indirect-lighting-room-2026` | `one-room-streaming-setup-2026` | room | 1 |
| `japanese-whisky-distilleries-lineup-2026` | `taiwan-india-whisky-climate-2026` | whisky | 6 |
| `keith-ti9304-titanium-sake-cup-deep-dive-2026` | `arita-enka-sake-set-deep-dive-2026` | sake | 1 |

## URL検査送信計画（P1/P2 上位30件）

1. 上記の内部リンクを追加して公開を待つ。
2. Search Console → URL検査 に以下のURLを1件ずつ入力し、「インデックスに送信」を実行する。

| # | URL | 分類 |
|---:|---|---|
| 1 | https://kingsworksub-jpg.github.io/posts/cafe-jazz-lounge-piano-2026/ | 未インデックス（未検出） |
| 2 | https://kingsworksub-jpg.github.io/posts/2026-jazz-new-albums-jon-batiste-chihiro-yamanaka/ | 未インデックス（未検出） |
| 3 | https://kingsworksub-jpg.github.io/posts/hammond-b3-jazz-organ-2026/ | 未インデックス（未検出） |
| 4 | https://kingsworksub-jpg.github.io/posts/jazz-fusion-1970s-weather-report/ | 未インデックス（未検出） |
| 5 | https://kingsworksub-jpg.github.io/posts/jazz-instruments-guide/ | 未インデックス（未検出） |
| 6 | https://kingsworksub-jpg.github.io/posts/jazz-listening-guide-2026/ | 未インデックス（クロール済み） |
| 7 | https://kingsworksub-jpg.github.io/posts/jazz-masterpieces-beginner/ | 未インデックス（未検出） |
| 8 | https://kingsworksub-jpg.github.io/posts/jazz-style-menswear-2026/ | 未インデックス（未検出） |
| 9 | https://kingsworksub-jpg.github.io/posts/jazz-vocal-phrasing-guide-2026/ | 未インデックス（未検出） |
| 10 | https://kingsworksub-jpg.github.io/posts/modern-spiritual-jazz-2026/ | 未インデックス（未検出） |
| 11 | https://kingsworksub-jpg.github.io/posts/nea-jazz-masters-2026/ | 未インデックス（未検出） |
| 12 | https://kingsworksub-jpg.github.io/posts/coca-cola-zero-deep-dive-2026/ | 未インデックス（未検出） |
| 13 | https://kingsworksub-jpg.github.io/posts/sony-ecm-ax10-spatial-mic-2026/ | 未インデックス（未検出） |
| 14 | https://kingsworksub-jpg.github.io/posts/statement-hat-trend-2026/ | 未インデックス（未検出） |
| 15 | https://kingsworksub-jpg.github.io/posts/adult-piano-learning-2026/ | 未インデックス（未検出） |
| 16 | https://kingsworksub-jpg.github.io/posts/bottled-cider-5choice-2026/ | 未インデックス（未検出） |
| 17 | https://kingsworksub-jpg.github.io/posts/budget-whisky-10choice-2026/ | 未インデックス（クロール済み） |
| 18 | https://kingsworksub-jpg.github.io/posts/canadian-whisky-rye-4choice-2026/ | 未インデックス（未検出） |
| 19 | https://kingsworksub-jpg.github.io/posts/classic-french-style-revival-2026/ | 未インデックス（未検出） |
| 20 | https://kingsworksub-jpg.github.io/posts/craft-cola-spice-syrup-2026/ | 未インデックス（未検出） |
| 21 | https://kingsworksub-jpg.github.io/posts/crystal-spark-ramune-deep-dive-2026/ | 未インデックス（未検出） |
| 22 | https://kingsworksub-jpg.github.io/posts/dodecamin-zero-sakebitai-deep-dive-2026/ | 未インデックス（未検出） |
| 23 | https://kingsworksub-jpg.github.io/posts/dynamic-mic-5choice-2026/ | 未インデックス（未検出） |
| 24 | https://kingsworksub-jpg.github.io/posts/ear-training-one-week/ | 未インデックス（未検出） |
| 25 | https://kingsworksub-jpg.github.io/posts/fender-studio-pro-8-studio-one-2026/ | 未インデックス（未検出） |
| 26 | https://kingsworksub-jpg.github.io/posts/guitar-recording-amp-sim-setup/ | 未インデックス（未検出） |
| 27 | https://kingsworksub-jpg.github.io/posts/icy-spark-canada-dry-lemon-deep-dive-2026/ | 未インデックス（未検出） |
| 28 | https://kingsworksub-jpg.github.io/posts/indirect-lighting-room-2026/ | 未インデックス（未検出） |
| 29 | https://kingsworksub-jpg.github.io/posts/japanese-whisky-distilleries-lineup-2026/ | 未インデックス（未検出） |
| 30 | https://kingsworksub-jpg.github.io/posts/keith-ti9304-titanium-sake-cup-deep-dive-2026/ | 未インデックス（未検出） |

## 優先記事一覧（上位80件）

| 優先度 | slug | 分類 | 内部リンク元候補（IMP） | ASIN/検索 |
|---|---|---|---|---|
| P1 | `cafe-jazz-lounge-piano-2026` / 2026年のカフェジャズとラウンジピアノ、Moonlig | 未インデックス（未検出） | `jazz-festivals-2026`(21), `piano-practice-apps-3choice-2026`(11) | 3/0 |
| P1 | `2026-jazz-new-albums-jon-batiste-chihiro-yamanaka` / Jon Batiste『Black Mozart』と山中 | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 2/0 |
| P1 | `hammond-b3-jazz-organ-2026` / ハモンドB-3の左手はベースを弾く。ジミー・スミスが変え | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 3/2 |
| P1 | `jazz-fusion-1970s-weather-report` / 1970年代のフュージョンでは、ベースが旋律を歌いシンセ | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 3/2 |
| P1 | `jazz-instruments-guide` / リズム隊とホーンから知る、ジャズの楽器入門 | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 4/0 |
| P1 | `jazz-listening-guide-2026` / ジャズの名盤リストはなぜ続かないのか、聴く順番と入門書の | 未インデックス（クロール済み） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 4/0 |
| P1 | `jazz-masterpieces-beginner` / ジャズ名盤入門、最初に聴きたい10枚を時代順に | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 4/0 |
| P1 | `jazz-style-menswear-2026` / Gen-Zが着こなすジャズ・メンズウェア、フォーマルと自 | 未インデックス（未検出） | `jazz-style-fashion-revival-2026`(7), `jazz-festivals-2026`(21) | 3/0 |
| P1 | `jazz-vocal-phrasing-guide-2026` / ジャズヴォーカル入門、歌詞より先に「間」を聴く。ビリー・ | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 0/4 |
| P1 | `modern-spiritual-jazz-2026` / Kamasi WashingtonとDinner Par | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 3/0 |
| P1 | `nea-jazz-masters-2026` / NEAジャズマスターズ2026、カルメン・ランディとアイ | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 1/0 |
| P1 | `coca-cola-zero-deep-dive-2026` / コカ・コーラ ゼロ、罪悪感を引き算したもうひとつの黒い炭 | 未インデックス（未検出） | `green-cola-deep-dive-2026`(10), `mitsuya-cider-zero-deep-dive-2026`(2) | 3/0 |
| P1 | `sony-ecm-ax10-spatial-mic-2026` / ソニーECM-AX10は、スマホを空間オーディオの録音機 | 未インデックス（未検出） | `sony-pslx3bt-deep-dive-2026`(23), `condenser-mic-5choice-2026`(8) | 1/3 |
| P1 | `statement-hat-trend-2026` / 帽子が主役になる秋冬2026、ステートメントハットの選び | 未インデックス（未検出） | `statement-hat-trends-autumn-2026`(4), `jazz-shoes-trend-2026`(2) | 2/0 |
| P1 | `adult-piano-learning-2026` / 大人から鍵盤を始める、指より先に決めることがある | 未インデックス（未検出） | `piano-practice-apps-3choice-2026`(11) | 3/0 |
| P1 | `bottled-cider-5choice-2026` / びんのサイダーはなぜ懐かしい味がするのか。三ツ矢・有馬・ | 未インデックス（未検出） | `mitsuya-cider-zero-deep-dive-2026`(2) | 4/2 |
| P1 | `budget-whisky-10choice-2026` / 千円台の安ウイスキー10本、ハイボールにも水割りにも合う | 未インデックス（クロール済み） | `taiwan-india-whisky-climate-2026`(6) | 37/0 |
| P1 | `canadian-whisky-rye-4choice-2026` / カナディアンウイスキー4本、ライ麦が少なくても「ライ」と | 未インデックス（未検出） | `taiwan-india-whisky-climate-2026`(6) | 7/3 |
| P1 | `classic-french-style-revival-2026` / ゲンスブールの系譜を継ぐ、2026年のクラシック・フレン | 未インデックス（未検出） | `jazz-style-fashion-revival-2026`(7) | 4/0 |
| P1 | `craft-cola-spice-syrup-2026` / クラフトコーラの原液は、割る人が最後の調合を担う | 未インデックス（未検出） | `green-cola-deep-dive-2026`(10) | 2/2 |
| P1 | `crystal-spark-ramune-deep-dive-2026` / CRYSTAL SPARK ラムネで、果汁ゼロの瓶の記憶 | 未インデックス（未検出） | `crystal-spark-grape-deep-dive-2026`(2) | 3/0 |
| P1 | `dodecamin-zero-sakebitai-deep-dive-2026` / 名前は変わっても中身は裏切らない「ドデカミンのゼロが好き | 未インデックス（未検出） | `mitsuya-cider-zero-deep-dive-2026`(2) | 3/0 |
| P1 | `dynamic-mic-5choice-2026` / ダイナミックマイク5本比較、話し声も歌も1本で録るなら必 | 未インデックス（未検出） | `condenser-mic-5choice-2026`(8) | 10/0 |
| P1 | `ear-training-one-week` / 耳コピの1週間で伸びるのは速さで、届く範囲はまだ広がらな | 未インデックス（未検出） | `one-room-streaming-setup-2026`(1) | 1/3 |
| P1 | `fender-studio-pro-8-studio-one-2026` / Studio OneがFender Studio Pro | 未インデックス（未検出） | `one-room-streaming-setup-2026`(1) | 0/3 |
| P1 | `guitar-recording-amp-sim-setup` / アンプを鳴らせない部屋のギター録音：Hi-Z接続・ゲイン | 未インデックス（未検出） | `one-room-streaming-setup-2026`(1) | 6/2 |
| P1 | `icy-spark-canada-dry-lemon-deep-dive-2026` / 「史上最強」の泡は本当か？アイシー・スパーク from  | 未インデックス（未検出） | `crystal-spark-grape-deep-dive-2026`(2) | 3/0 |
| P1 | `indirect-lighting-room-2026` / 間接照明で部屋を広く見せる、天井を照らすか壁を照らすか | 未インデックス（未検出） | `one-room-streaming-setup-2026`(1) | 0/4 |
| P1 | `japanese-whisky-distilleries-lineup-2026` / ジャパニーズウイスキーの蒸溜所を7つ巡る、山崎の霧から余 | 未インデックス（未検出） | `taiwan-india-whisky-climate-2026`(6) | 13/0 |
| P1 | `keith-ti9304-titanium-sake-cup-deep-dive-2026` / KEITH 純チタン おちょこは、白酒のために生まれた旅 | 未インデックス（未検出） | `arita-enka-sake-set-deep-dive-2026`(1) | 3/0 |
| P1 | `laptop-only-dtm-portable-setup-2026` / ノートPC1台でDTMを続けるなら、据え置きから持ち出す | 未インデックス（未検出） | `one-room-streaming-setup-2026`(1) | 1/3 |
| P1 | `loafer-derby-autumn-2026` / ローファーかダービーか。紐一本で変わる秋の装いの幅と、靴 | 未インデックス（未検出） | `statement-hat-trends-autumn-2026`(4) | 5/0 |
| P1 | `masu-sake-cup-hinoki-2026` / 枡で日本酒を冷やで飲む理由、江戸の量り売りの道具が祝いの | 未インデックス（未検出） | `arita-enka-sake-set-deep-dive-2026`(1) | 6/0 |
| P1 | `metronome-rhythm-practice-2026` / メトロノームに合わせて弾けるのに、録音するとずれて聞こえ | 未インデックス（未検出） | `piano-practice-apps-3choice-2026`(11) | 12/0 |
| P1 | `mic-preamp-gain-compare-2026` / マイクプリアンプのゲインを上げると音はどう変わるのか、4 | 未インデックス（未検出） | `condenser-mic-5choice-2026`(8) | 13/0 |
| P1 | `mitsuya-cider-original-deep-dive-2026` / 三ツ矢サイダーの透明な甘さは140年でどう守られてきたか | 未インデックス（未検出） | `mitsuya-cider-zero-deep-dive-2026`(2) | 3/0 |
| P1 | `mix-practice-1month` / ミックス独学の1か月、同じ曲でEQ・コンプ・リバーブを1 | 未インデックス（未検出） | `piano-practice-apps-3choice-2026`(11) | 4/1 |
| P1 | `monitor-placement-room-tuning-6jo-2026` / モニタースピーカーの置き方、6畳なら机を短い壁に向けると | 未インデックス（未検出） | `one-room-streaming-setup-2026`(1) | 3/1 |
| P1 | `odate-akita-sugi-sake-set-deep-dive-2026` / 秋田杉の香りをまとう日本酒、大館工芸社の酒器3点セット | 未インデックス（未検出） | `arita-enka-sake-set-deep-dive-2026`(1) | 5/0 |
| P1 | `scarf-styling-trend-2026` / スカーフ一枚で装いが変わる、2026年のスカーフスタイリ | 未インデックス（未検出） | `jazz-shoes-trend-2026`(2) | 5/0 |
| P1 | `streaming-loudness-normalization-lufs` / ラウドネスノーマライズの検証メモ：-8から-16 LUF | 未インデックス（未検出） | `one-room-streaming-setup-2026`(1) | 4/0 |
| P1 | `toyo-sasaki-carafe-variation-deep-dive-2026` / 氷を閉じ込めて薄めない、東洋佐々木ガラス カラフェ・バリ | 未インデックス（未検出） | `bodum-douro-carafe-deep-dive-2026`(6) | 3/0 |
| P1 | `tsugaru-vidro-mizubasho-sake-set-deep-dive-2026` / 湿地に咲く白い花を青いガラスに、津軽びいどろ みずばしょ | 未インデックス（未検出） | `arita-enka-sake-set-deep-dive-2026`(1) | 3/0 |
| P1 | `tsugaru-vidro-nebuta-sake-set-deep-dive-2026` / ねぶたの夜を盃に閉じ込める、アデリア 津軽びいどろ NE | 未インデックス（未検出） | `arita-enka-sake-set-deep-dive-2026`(1) | 3/0 |
| P1 | `tweed-jacket-street-style-2026` / ツイードジャケットの着こなし、目の粗いヘビーウェイト生地 | 未インデックス（未検出） | `jazz-style-fashion-revival-2026`(7) | 2/0 |
| P1 | `vox-cola-flavor-deep-dive-2026` / VOX 強炭酸水 コーラフレーバーは香りだけのコーラにな | 未インデックス（未検出） | `green-cola-deep-dive-2026`(10) | 2/0 |
| P1 | `whisky-year-end-gift-guide-2026` / ウイスキーを年末に贈るなら、化粧箱の1本とアドベントカレ | 未インデックス（未検出） | `taiwan-india-whisky-climate-2026`(6) | 0/6 |
| P2 | `free-jazz-harmony-meter-listening-2026` / フリージャズの聴き方、オーネット・コールマンが手放した和 | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 0/0 |
| P2 | `japanese-jazz-sadao-watanabe-lineage-2026` / 日本のジャズは輸入盤のコピーからどう抜け出したか、秋吉敏 | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 0/0 |
| P2 | `jazz-kissa-culture-2026` / 大きな音を他者と聴く――日本のジャズ喫茶が育てた「場」と | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 0/0 |
| P2 | `jazz-kissa-speaker-night-2026` / ジャズ喫茶で黙って聴いた大きな音、スピーカーの前の1時間 | 未インデックス（未検出） | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 0/0 |
| P2 | `compass-box-10-year-age-statement-2026` / Compass Boxの「10年物」はなぜ全部10年か、 | 未インデックス（未検出） | `statement-hat-trends-autumn-2026`(4) | 0/0 |
| P2 | `fl-studio-pattern-piano-roll` / FL Studioに移って最初に戸惑うのは、トラックでは | 未インデックス（未検出） | `piano-practice-apps-3choice-2026`(11) | 0/0 |
| P2 | `new-scotch-distilleries-young-whisky-2026` / 新しいスコッチ蒸溜所は12年を待たずに何を売るのか、ハリ | 未インデックス（未検出） | `taiwan-india-whisky-climate-2026`(6) | 0/0 |
| P2 | `shiboritate-sake-winter-namazake-2026` / しぼりたての日本酒は11月から春までしか並ばない。寒造り | 未インデックス（未検出） | `arita-enka-sake-set-deep-dive-2026`(1) | 0/0 |
| P3 | `anime-and-jazz` / 「Tank!」から佐世保の喫茶店まで、アニメーションとジ | インデックス済み・クエリ無し | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 13/0 |
| P3 | `cool-jazz-birth-of-the-cool` / Miles Davis『Birth of the Coo | インデックス済み・クエリ無し | `jazz-festivals-2026`(21), `jazz-style-fashion-revival-2026`(7) | 2/0 |
| P3 | `nousaku-tin-sake-set-deep-dive-2026` / 曲がる錫が酒をやわらげる、能作 本錫100%酒器セット | インデックス済み・クエリ無し | `arita-enka-sake-set-deep-dive-2026`(1) | 3/0 |
| P3 | `peacock-acf38-sake-set-deep-dive-2026` / 温度を止める徳利、ピーコックの真空二重構造 酒器セット | インデックス済み・クエリ無し | `arita-enka-sake-set-deep-dive-2026`(1) | 3/0 |
| P3 | `scotch-whisky-5choice-2026` / スコッチウイスキー5本を飲み比べ、グラスの中のもうひとつ | インデックス済み・クエリ無し | `taiwan-india-whisky-climate-2026`(6) | 15/0 |
| P3 | `suzu-chirori-kanzake-2026` / 錫のちろりで燗をつける。陶器の徳利より熱を速く渡す、大阪 | インデックス済み・クエリ無し | - | 5/0 |
| P3 | `turntable-5choice-2026` / アナログターンテーブル5台比較、針を落とすという儀式のた | インデックス済み・クエリ無し | - | 21/0 |
| P3 | `yosa-soda-deep-dive-2026` / ヨサソーダの飲み切りサイズが正解だった理由 | インデックス済み・クエリ無し | - | 3/0 |
| 保留 | `2026w40-064` / 銀幕に息づく即興の輪郭――『Round Midnight | 未インデックス（未検出） | - | 0/0 |
| 保留 | `ableton-live-12-session-view-2026` / Ableton Live 12のセッションビューが変える | 未インデックス（未検出） | - | 7/0 |
| 保留 | `ace-studio-ai-vocal-synthesis-2026` / ACE Studioの140を超える声に、打ち込んだメロ | 未インデックス（未検出） | - | 0/1 |
| 保留 | `akai-mpk-mini-mk4-deep-dive-2026` / Akai MPK Mini MK4の25鍵でできること、 | 未インデックス（未検出） | - | 6/0 |
| 保留 | `alan-boguslavsky-stage` / Héroes del Silencioの写真から消された | 未インデックス（未検出） | - | 2/0 |
| 保留 | `angels-share-evaporation-essay-2026` / エンジェルズシェアで毎年2%ずつ減る樽、熟成は失う時間で | 未インデックス（未検出） | - | 4/0 |
| 保留 | `audacity-4-guide-2026` / Audacity 4、25年ぶりの全面刷新。Qtエンジン | 未インデックス（未検出） | - | 0/0 |
| 保留 | `audio-interface-5choice-2026` / オーディオインターフェース5台比較、声とパソコンのあいだ | 未インデックス（未検出） | - | 15/0 |
| 保留 | `awk-svg-radar-chart-notes` / awkだけでSVGのレーダーチャートを描く、72度ずつ回 | 未インデックス（未検出） | - | 3/0 |
| 保留 | `background-music-focus-listening-2026` / 作業中のBGMで、耳は何を聞き流しているのか。歌詞が邪魔 | 未インデックス（未検出） | - | 0/0 |
| 保留 | `beaujolais-nouveau-carbonic-maceration-2026` / ボジョレー・ヌーヴォーが軽い理由、ぶどうの粒の中で始まる | 未インデックス（未検出） | - | 0/0 |
| 保留 | `bebop-52nd-street-nights` / Charlie ParkerとDizzy Gillesp | 未インデックス（未検出） | - | 4/0 |
| 保留 | `bizen-guinomi-yakishime-2026` / 備前焼のぐい呑みに釉薬がない理由と、酒がまろやかになると | 未インデックス（未検出） | - | 4/0 |
| 保留 | `black-friday-shopping-plan-2026` / ブラックフライデーの買い物計画は10月から始めたほうがい | 未インデックス（未検出） | - | 4/0 |
| 保留 | `black-nikka-clear-deep-dive-2026` / ブラックニッカ クリアの軽さはどこから来るのか | 未インデックス（未検出） | - | 3/0 |
| 保留 | `bourbon-5choice-2026` / バーボン5本、甘さを決めるのはライ麦の比率と樽の焼き方 | 未インデックス（未検出） | - | 17/0 |
| 保留 | `bw-685-deep-dive-2026` / B&W 685レビュー、黄色いケブラーコーンが鳴らす英国 | 未インデックス（未検出） | - | 3/0 |

全件の詳細は `scripts/zero-imp-plan.json` を参照。
