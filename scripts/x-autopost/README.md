# はてなブログ → X 自動投稿パイプライン

はてなブログのRSSフィードで新着記事を検出し、Playwrightで本文を取得、Claude Code CLIで要約とX投稿文(3パターン→最も自然なもの1つを選択)を生成し、**ユーザーの普段のEdge(既定プロファイル、ログイン済み)をOSレベルの入力シミュレーションで操作して投稿する**(X API課金ゼロ、ブラウザ自動化プロトコルも不使用)。処理状況はSQLite(`posts.db`)に記録し、重複投稿を防ぐ。

## なぜこの方式か(方式変遷)

1. **X API v2(tweepy)**: 2026年2月に無料枠が廃止され、URL付き投稿は1件$0.20の完全従量課金。「無料・ローカル完結」という前提に反するため不採用。
2. **Playwright(CDP)でx.comに自動ログイン**: Google経由ログイン・X自身のログインフォームの両方でBot検知にブロックされた(実Chromeに切り替えても改善せず)。CDP/WebDriver経由の自動操作である以上、検知は避けられないと判断し不採用。
3. **【採用】OSレベルのマウス・キーボード入力シミュレーション**: `pyautogui`(キー送信)・`pyperclip`(クリップボード経由のテキスト貼り付け)・`pygetwindow`(ウィンドウのアクティブ化確認)を使い、ユーザーが**普段から使っていてXにログイン済みのEdge**をそのまま起動して操作する。CDP/WebDriverを一切使わないため、Bot検知の対象にならない。ログイン自動化そのものが不要になる(既存のログイン状態をそのまま使うため)。

**既知のトレードオフ(承知の上で採用)**: 公式APIではない自動化は、Xの利用規約上グレーゾーンであり、頻度や挙動によってはアカウント制限のリスクがある。このパイプラインはブログの更新頻度(週数回程度)に合わせた低頻度投稿を想定しており、人間の通常利用に近いペースで動かす前提(`main.py`は複数記事をまとめて投稿する際、1件あたり45秒の間隔を空ける)。

## 構成

```
feed_check.py  -- RSSフィードをポーリングし、新着記事をDBに登録(status='detected')
scraper.py     -- Playwrightで記事ページを開き、本文を抽出(status='scraped')。本文取得専用で、X投稿には使っていない
generate.py    -- Claude Code CLI(haikuモデル)で要約+投稿文3案+選定(status='generated')
poster.py      -- Edgeをosレベルの入力シミュレーションで操作して投稿(status='posted')
db.py          -- SQLiteのスキーマ・CRUDヘルパー
main.py        -- 上記を順に実行するオーケストレーター(これを定期実行する)
```

## セットアップ

### 1. 依存パッケージのインストール

```powershell
cd scripts\x-autopost
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Claude Code CLIの確認

```powershell
claude --version
```

インストール済みでない場合は `winget install --id Anthropic.ClaudeCode -e` でインストールできる。`main.py` を実行するユーザーがClaude Codeにログイン済みである必要がある(`claude` を一度対話モードで起動してログインしておく)。

### 3. Edgeで事前にXにログインしておく

**普段使っている既定プロファイルのEdge**で、Xに手動でログインしておく(すでにログイン済みなら不要)。ログイン自動化のステップは無い——`poster.py`はこの既存セッションをそのまま使う。`poster.py`内の`EDGE_PATH`(`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`)がインストール先と異なる場合は書き換えること。

### 4. 【重要】既存記事のバックログをスキップ登録する(初回のみ・必須)

DBが空の状態で`main.py`をいきなり実行すると、RSSフィードに載っている**既存記事すべて**が「新着」と誤認識され、まとめてXに投稿されてしまう(実際に本プロジェクトのセットアップ時、既存12記事がこの状態になったため、`seed_baseline.py`でスキップ登録して防いだ)。新規に環境を作り直す場合は、以下を実行してから`main.py`を使うこと:

```powershell
cd scripts\x-autopost
python feed_check.py      # 現時点の既存記事をDBに登録(status='detected')
python seed_baseline.py   # それらを 'skipped_baseline' に変更(投稿対象から除外)
```

これ以降にはてなブログへ新規投稿された記事だけが、`main.py`の処理対象(`detected`→`scraped`→`generated`→`posted`)になる。既存記事もまとめてXに投稿したい場合は、`status='skipped_baseline'`の行を`detected`に戻せば処理対象になる。

### 5. 動作確認(1回だけ手動実行)

```powershell
cd scripts\x-autopost
python main.py
```

新着記事があれば、検出→本文取得→文章生成→X投稿、まで一気に走る。`posts.db` の中身をSQLiteビューアで確認すれば、各記事がどの段階まで進んだか(`status`列)が分かる。

### 6. 定期実行の設定(Windowsタスクスケジューラ)

1. タスクスケジューラを開き、「基本タスクの作成」。
2. トリガー: 例えば「15分ごと」「1時間ごと」など、任意の間隔で繰り返す設定にする。
3. 操作: プログラムの開始 →
   - プログラム: `C:\Users\norio\Projects\kingsworksub-jpg.github.io\scripts\x-autopost\.venv\Scripts\python.exe`
   - 引数: `main.py`
   - 開始場所: `C:\Users\norio\Projects\kingsworksub-jpg.github.io\scripts\x-autopost`

タスクスケジューラから実行する場合、ログイン中のセッション(ユーザーのデスクトップにEdgeウィンドウを開ける状態)であることが前提。ロック画面状態や別ユーザーセッションでは動作しない。

## 運用上の注意

- **失敗した記事は`status='error'`のまま止まる**(無限リトライしない)。`error_message`列に原因が入るので、直して`status`を該当する前段階(`detected`/`scraped`/`generated`)に手動で戻せば、次回実行時に再処理される。
- **コスト**: `generate.py` は1記事あたりおよそ$0.05(haikuモデル)。デフォルトのSonnetモデルだと拡張思考が絡んで$0.27〜0.37程度に跳ね上がることを確認済みなので、`generate.py`内の`MODEL`定数は変更しない方が安全。`--max-budget-usd`で暴走時の上限も設定済み。
- **投稿文に自動化を匂わせる語を入れない**: `generate.py`のプロンプトで「テスト」「自動投稿」「AI」「bot」「生成」等の語を明示的に禁止している。過去に一度、テスト用の文言(「【自動投稿テスト中】」)がそのまま実投稿されてしまい、ユーザーに手動削除してもらう事故があった。テスト投稿を行うときは、本文が実際に公開されても違和感のない内容にすること。
- **Windows環境でのエンコーディング**: `claude` CLIの出力をファイルリダイレクト(`>`)経由で読むと文字化けする場合がある(Node.jsのWindows上でのstdout非TTY時のcodepage挙動に起因すると見られる)。`generate.py`は`subprocess.run(capture_output=True, encoding="utf-8")`でパイプ経由の直接読み取りを行っており、この方式では文字化けしないことを確認済み。ファイルリダイレクト方式に変更しないこと。
- **本文取得のセレクタ**: `scraper.py`の`ENTRY_CONTENT_SELECTOR`ははてなブログの標準テーマの`.entry-content.hatenablog-entry`を前提にしている。テーマを変更した場合は要修正。
- **重複投稿防止**: RSSのGUID(記事の一意ID)をSQLiteでユニーク制約管理しているため、同じ記事に対して`main.py`を何度実行しても2重投稿にはならない。ただし「既存記事の内容修整による再投稿」(`update-hatena-post.sh`での更新)はRSSのGUIDが変わらないため、そもそも新着として検出されない(想定通りの挙動)。
- **tweet_idは取得しない**: ブラウザ自動化のため投稿後のツイートURLを確実に取得する手段が無く、`posts.db`の`tweet_id`列は常に空になる(投稿できたかどうかは`status='posted'`で判断する)。
- **ウィンドウ操作中は他の操作を避ける**: `poster.py`実行中はEdgeウィンドウがアクティブになり、そこにキー入力が送られる。実行中にマウス・キーボードで他のウィンドウをアクティブにすると、誤った場所にテキストが入力される可能性がある。
- **投稿後は開いたタブを閉じる(2026-09-18、ユーザー指示)**: `post_tweet()`は毎回新しいcomposeタブを開くだけで閉じない設計だったため、炭酸飲料(2時間おき)・ジャズ(1時間おき)の連続実行でタブが際限なく溜まりメモリを圧迫する問題が発生した。投稿(`Ctrl+Enter`)後、Edgeがまだフォーカスされていることを再確認した上で`Ctrl+W`でそのタブを閉じるようにした。フォーカスが外れていた場合は閉じずに警告を出すだけに留める(誤ったウィンドウにCtrl+Wを送らないため)。
- **他PCへの移設**: `EDGE_PATH`の実行ファイルパスは環境依存。別のマシンで使う場合は`poster.py`内の定数を書き換えること。
