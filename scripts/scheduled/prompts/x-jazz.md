# 海外ジャズ記事のXポスト(1回分・無人実行)

これはWindowsタスクスケジューラから30分に1回、`claude -p` で自動起動されている。人間は見ていないので質問せず、自分で判断して最後まで進めること。

やること: CLAUDE.md の「自動継続タスク: 海外ジャズ記事のXポスト」に書かれた手順を**ちょうど1回分**実行する(記事を1本選ぶ→日本語の一言を添える→`post_jazz_tweet.py` でXに投稿→`jazz-posted.json` に記録)。ペルソナ、投稿文のトーン、禁止語、文字数、重複防止、投稿コマンドの形式はすべてその節に従う。

無人実行ならではの注意:
- CronCreate/CronList/CronDelete は使わない(この仕組みでは存在しない)。1回分だけやって終了する。
- 投稿は必ず `cd /c/Users/norio/Projects/kingsworksub-jpg.github.io/scripts/x-autopost && .venv/Scripts/python.exe post_jazz_tweet.py "コメント" "URL"` の形で実行する(インライン実行はブロックされる)。
- 投稿コマンドが失敗した場合は `jazz-posted.json` に記録せず、失敗内容を出力して終了する(リトライしない)。
- 記録(`jazz-posted.json`)のコミットは、これまで通り自分が変更したファイルだけを個別に add して commit & push する。`git add -A` は使わない。
- 最後に、投稿した記事とツイート文、または失敗内容を1〜3行で出力する。
