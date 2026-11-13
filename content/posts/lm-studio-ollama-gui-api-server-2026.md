---
title: "LM StudioとOllamaは何が違うのか、モデルを画面で選ぶ手軽さと1234番ポートのAPI"
description: "LM StudioはローカルLLMを画面で探して試せる無料アプリ。Ollamaとの違いを、モデル検索とメモリの目安、MacのMLX、チャット機能、OpenAI互換のAPIサーバーの順に整理し、使い分ける場面までまとめた。"
images: ["/images/og/lm-studio-ollama-gui-api-server-2026.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-11-07T20:00:00+09:00
scheduled_time: "20:00"
categories: ["tech"]
tags: ["LM Studio", "Ollama", "ローカルLLM", "OpenAI互換API", "GGUF", "MLX"]
draft: false
---

Ollamaでモデルを1つ動かせるようになると、次に欲しくなるのは「ほかのモデルも気軽に試したい」という手軽さだと思う。ターミナルで `ollama run` と打てば会話は始まるが、どのモデルがあるのか、どの量子化を選べば自分のPCに収まるのかは、ライブラリのページとコマンドを行き来しながら確かめることになる。新しいモデルの名前を見かけるたびにその手順を踏むのは、少し腰が重い。

LM Studioは、その「探して、選んで、試す」までを1つの画面で済ませるためのデスクトップアプリだ。検索欄にモデル名を入れると候補が並び、量子化ごとのファイルサイズと、手元のメモリに収まりそうかどうかの目安が横に表示される。ダウンロードが終わればそのままチャットを始められ、気に入ったモデルは、ボタン1つでOpenAI互換のAPIサーバーとして外のアプリから呼べるようになる。この記事では、Ollamaとの違いを入口・モデル選び・チャット・APIサーバーの順に見ていき、2つをどう使い分けるかまでを整理する。

## 同じGGUFのモデルを動かす2つの道具、違うのは入口

<figure class="photo photo--left">
<a href="https://ollama.com/download" target="_blank" rel="noopener"><img src="/images/lm-studio/ollama-terminal.jpg" alt="Linuxのターミナルでollama run llama3を実行し、モデルが英語で長い回答を返している画面" width="220" height="81" loading="lazy"></a>
<figcaption>ターミナルで `ollama run llama3` を実行したところ。Ollamaはこの1行から始まる道具だ<span class="credit">Photo: MGeog2022 / <a href="https://commons.wikimedia.org/wiki/File:Ollama-running-llama3-in-linux.png" target="_blank" rel="noopener">CC BY 4.0</a></span></figcaption>
</figure>

LM StudioもOllamaも、手元のPCで言語モデルを動かすための道具で、中で扱っているモデルの形式は同じGGUFが中心になる。どちらもllama.cppの流れをくむ推論の仕組みを使っていて、4bit前後に量子化したモデルを、GPUのVRAMと本体のメモリに分けて載せながら動かす。動かせるモデルの大きさがPCのメモリで決まるという点も変わらない。

違いが大きいのは、利用者が最初に触れる部分だ。Ollamaはコマンドから使うことを前提に作られていて、インストールすると裏で常駐し、11434番ポートでAPIを待ち受ける。2025年の夏にはmacOSとWindows向けに公式のチャット画面も加わったが、モデルの取得や設定の中心は、いまもコマンドと環境変数にある。サーバーのように常に動かしておき、ほかのアプリから呼び出す使い方に向いた作りだと感じる。

LM Studioは反対に、画面から入るアプリだ。起動するとチャット画面とモデルの検索画面があり、量子化の選択、GPUにどこまで載せるか、コンテキスト長をいくつにするかといった設定を、スライダーや入力欄で決められる。APIサーバーは必要なときに自分で立ち上げる機能という位置づけで、既定のポートは1234番になる。

料金はどちらも無料で使える。Ollamaはソースコードが公開されたオープンソースのソフトで、ライセンスはMITだ。LM Studioはアプリ本体のソースは公開されていないが、2025年7月から個人でも仕事でも無料で使えるようになり、会社で使うために別途申請する必要はなくなった。コマンドラインツールの `lms` や、PythonとJavaScript向けのSDKはオープンソースで公開されている。

対応する環境には少し差がある。LM StudioはmacOSではApple Silicon搭載のMacが必要で、IntelプロセッサのMacには対応していない。Windowsでは、x64のPCならCPUがAVX2という命令に対応している必要がある。ここ10年ほどのCPUならまず問題ないが、古いPCに入れる場合は確かめておきたい。メモリは16GB以上あると、7Bから8Bのモデルを余裕をもって試せる。

## モデル探しは検索画面から、メモリに収まるかを先に見られる

<figure class="photo photo--right">
<a href="https://www.amazon.co.jp/s?k=GeForce+RTX+4070&tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow"><img src="/images/lm-studio/rtx4070.jpg" alt="白いカバーにGEFORCE RTXとGIGABYTEのロゴが入ったグラフィックボードを斜め上から写した写真" width="220" height="124" loading="lazy"></a>
<figcaption>VRAM 12GBのGeForce RTX 4070。LM Studioでは、モデルの層をこのVRAMにいくつ載せるかをスライダーで決める<span class="credit">Photo: Jacek Halicki / <a href="https://commons.wikimedia.org/wiki/File:2023_Gigabyte_GeForce_RTX_4070_Aero_OC_12GB_(1).jpg" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

LM Studioのいちばんの持ち味は、モデルを探す画面だと思う。虫眼鏡のアイコンから検索画面を開き、「Qwen」や「Gemma」のようにモデル名を入れると、Hugging Faceに公開されているモデルの中から、LM Studioで動かせる形式のものが一覧になる。1つを選ぶと、Q4_K_MやQ5_K_M、Q8_0といった量子化ごとのファイルが並び、それぞれのサイズが表示される。

このとき役に立つのが、手元のPCに収まるかどうかの目安だ。LM StudioはPCのVRAMとメモリの量を読み取っていて、量子化ごとに「GPUにすべて載りそう」「一部だけ載りそう」「このPCには大きすぎる」といった見込みを表示してくれる。ファイルサイズとVRAMの数字を自分で突き合わせなくても、どの量子化から試せばいいかの見当がつく。Q4とQ5の違いが何を意味するのかを知っておくと、ここで迷う時間がさらに短くなる。

モデルを読み込むときには、詳細な設定を開いて、GPUに載せる層の数（GPUオフロード）とコンテキスト長を指定できる。VRAMに収まりきらないモデルでも、層の一部だけをGPUに載せ、残りをCPUと本体のメモリで計算させれば動かせる。Ollamaでは `ollama ps` で結果を確かめ、環境変数やモデルごとの設定で調整していた部分が、LM Studioでは読み込む前の画面で数字を動かしながら決められる。長い文書を読ませたいときだけコンテキスト長を伸ばし、普段の会話では短めにして速さを優先する、といった切り替えも気軽にできる。

ダウンロードしたモデルは、ユーザーフォルダの中にあるLM Studio専用のモデル置き場に保存される。Ollamaはモデルを独自の形で保存しているので、Ollamaで取得したモデルをそのままLM Studioの一覧に出すことはできない。同じモデルを両方で使いたい場合は、それぞれで取得し直すことになり、ストレージの容量はそのぶん必要になる。試すモデルが増えてきたら、マイモデルの画面で使わないものを消していくと、ディスクの空きを保ちやすい。

## Apple SiliconのMacならMLX版のモデルを選べる

<figure class="photo photo--left">
<a href="https://www.amazon.co.jp/s?k=Mac+mini+M4&tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow"><img src="/images/lm-studio/mac-mini-m4.jpg" alt="木の机の上に置かれた銀色のMac mini（M4、2024年モデル）を正面から写した写真" width="220" height="185" loading="lazy"></a>
<figcaption>M4チップを積んだMac mini。CPUとGPUが同じメモリを共有するので、本体のメモリの量がそのまま扱えるモデルの大きさになる<span class="credit">Photo: Seasider53 / <a href="https://commons.wikimedia.org/wiki/File:Mac_mini_2024_M4.jpg" target="_blank" rel="noopener">CC BY 4.0</a></span></figcaption>
</figure>

Macで使う場合、LM StudioにはもうひとつOllamaとの違いがある。GGUFのモデルに加えて、AppleがApple Silicon向けに公開している機械学習の仕組み「MLX」の形式のモデルも動かせることだ。検索画面ではGGUF版とMLX版が区別して表示されるので、同じモデルのMLX版を選んで読み込めばよい。

Apple SiliconのMacは、CPUとGPUが同じメモリを共有している。グラフィックボードのVRAMという区切りがなく、たとえば32GBのメモリを積んだMacなら、OSやほかのアプリの分を除いた大部分をモデルのために使える。WindowsのPCでVRAM 24GBのGPUを用意するよりも、メモリを多めに積んだMacのほうが大きなモデルに手が届きやすい、という逆転が起きるのはこのためだ。MLXはこの仕組みに合わせて作られているので、同じモデルでもGGUF版より文章の出てくる速さが上がることが多い。

MLX版の弱みは、Mac以外では使えないことと、モデルによってはGGUF版より公開されている量子化の種類が少ないことだ。WindowsのPCとMacの両方で同じモデルを使い比べたいならGGUF版、Macで少しでも速く動かしたいならMLX版、と目的で選び分けるとよい。どちらを選んでも、チャット画面やAPIサーバーの使い方は変わらない。

## チャット画面でできること、システムプロンプトから文書の読み込みまで

LM Studioのチャット画面は、モデルを試すための場所であると同時に、日常の道具としても使える作りになっている。画面右側の設定欄で、モデルの役割や口調を決めるシステムプロンプトを書き、温度などの生成の設定と一緒に「プリセット」として保存しておける。歌詞の下書きを手伝わせる設定、英文のメールを日本語で要約させる設定、といった具合に用途ごとのプリセットを作っておけば、会話を始めるたびに同じ指示を書き直さなくて済む。

PDFやテキストファイルを会話に添付すると、その内容を参照しながら答えさせることもできる。長い文書は自動で細かく分けられ、質問に関係する部分だけがモデルに渡される。この処理もすべて手元のPCの中で完結するので、社外に出せない資料や、まだ誰にも見せていない原稿を扱うときにも安心感がある。

2025年の夏からは、外部のツールとモデルをつなぐ仕組みであるMCP（Model Context Protocol）にも対応した。設定ファイルにMCPサーバーを登録すると、モデルが会話の途中でそのツールを呼び出し、ファイルの一覧を調べたり、ウェブのページを取ってきたりできるようになる。ツールが呼ばれるときには確認の表示が出るので、何が実行されるのかを見てから許可できる。Ollamaの公式アプリでもファイルの添付はできるが、プリセットの管理やMCPのつなぎ込みまで画面の中で扱えるのは、LM Studioのほうが一歩進んでいると感じる。

## 1234番ポートで待つAPIサーバーと、lmsコマンド

<figure class="photo photo--right">
<a href="https://docs.openwebui.com/" target="_blank" rel="noopener"><img src="/images/lm-studio/open-webui.jpg" alt="ブラウザで開いたOpen WebUIのチャット画面。左に会話の履歴、上部にllama3:latestのモデル名が表示されている" width="220" height="118" loading="lazy"></a>
<figcaption>Open WebUIからローカルのモデルを呼び出している画面。OpenAI互換のAPIを開けておけば、こうしたアプリが手元のモデルを使えるようになる<span class="credit">Photo: Mattruffoni / <a href="https://commons.wikimedia.org/wiki/File:OllamaOpenwebuiInizio.png" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

LM Studioを、チャットアプリ以上のものにしているのがAPIサーバーの機能だ。開発者向けの画面でサーバーを起動すると、`http://localhost:1234` でリクエストを受け付けるようになる。用意されているのは、OpenAIのAPIと同じ形の `/v1/chat/completions`、`/v1/completions`、`/v1/embeddings`、`/v1/models` といった窓口だ。OpenAIの公式SDKを使って書いたプログラムなら、接続先のアドレスを `http://localhost:1234/v1` に変え、APIキーに適当な文字列を入れるだけで、手元のモデルに向けて動かせる。クラウドのサービスで組んだ仕組みを、料金や送信先を気にせずローカルで試せるのは心強い。

この互換性のおかげで、ブラウザで使うチャット画面のOpen WebUIや、エディタのコード補完の拡張機能など、OpenAI互換のAPIに対応したアプリの多くがLM Studioをそのまま相手にできる。OpenAI互換の窓口のほかに、モデルの一覧や読み込み状態、ダウンロードまで扱えるLM Studio独自のREST APIもあり、最近の版ではAnthropicのAPIと同じ形の窓口も加わっている。

便利なのが、リクエストが来たときにモデルを読み込む仕組みだ。リクエストの中でまだメモリに載せていないモデルの名前を指定すると、LM Studioがその場でモデルをメモリに載せてから答える。しばらく使われなかったモデルは、決めた時間が過ぎると自動でメモリから外すように設定できる。Ollamaも同じように、呼ばれたモデルを読み込み、既定では5分使われないと外す動きをするので、この点の使い勝手は近い。

サーバーの設定には「ローカルネットワークで公開する」という項目があり、これを有効にすると、同じ家の中のほかのPCやスマートフォンからもLM Studioのモデルを呼べるようになる。GPUを積んだデスクトップPCでモデルを動かし、ノートPCから使う、という分担ができる。ただし、ネットワークの外に開くことは想定されていないので、ルーターでポートを転送するような使い方はしないほうがよい。

画面を開かずに操作したいときは、`lms` というコマンドが使える。`lms server start` でサーバーを起動し、`lms get` でモデルを取得、`lms load` で読み込み、`lms ls` で手元のモデルの一覧、`lms ps` で読み込み中のモデルを確かめる。2026年に入ってからは、画面なしで常駐させるための仕組みも用意され、LM Studioをサーバー専用のPCで動かす使い方もしやすくなった。

## Ollamaを残す場面、LM Studioに任せる場面

ここまでの違いを並べると、2つは競合というより、得意な場面が少しずつずれた道具だと分かる。

| 比べるところ | LM Studio | Ollama |
|---|---|---|
| 主な入口 | アプリの画面（検索・チャット・設定） | コマンドと常駐サービス |
| モデルの探し方 | Hugging Faceを画面内で検索、量子化ごとに選ぶ | 公式ライブラリの名前とタグを指定 |
| メモリの目安 | 量子化ごとに収まるかどうかを表示 | `ollama ps` で読み込み後に確認 |
| Macでの形式 | GGUFとMLXを選べる | GGUF中心 |
| APIの既定ポート | 1234（必要なときに起動） | 11434（常に待ち受け） |
| OpenAI互換API | あり | あり |
| ソースコード | アプリ本体は非公開、CLIとSDKは公開 | MITライセンスで公開 |
| 料金 | 個人・仕事とも無料 | 無料 |

LM Studioに向いているのは、新しいモデルを次々に試して比べたいとき、量子化やコンテキスト長を数字で確かめながら決めたいとき、そしてMacでMLXの速さを活かしたいときだ。プログラムを書かない人でも、検索して、選んで、話しかけるまでを迷わずに進められる。一度気に入ったモデルが決まれば、そのままAPIサーバーとして開き、ほかのアプリの裏方に回せる。

Ollamaに向いているのは、PCを起動したら常にモデルが待ち受けていてほしいとき、Dockerやスクリプトの中に組み込みたいとき、LinuxのサーバーでGUIなしに動かしたいときだ。モデルの取得から実行までがコマンドで完結するので、手順を文章やスクリプトに残しやすい。オープンソースであることを重視する場合も、Ollamaを選ぶ理由になる。

両方を入れておくこともできる。待ち受けるポートが違うので、同時に起動しても衝突はしない。ただし、2つで同じ大きさのモデルを同時に読み込むと、そのぶんVRAMとメモリを取り合うことになる。普段の常駐はOllamaに任せ、新しいモデルを試すときだけLM Studioを開く、という分担にすると、メモリの使い方も見通しやすい。

## まとめ

| やりたいこと | 向いている道具 | ポイント |
|---|---|---|
| 新しいモデルを画面で探して試す | LM Studio | 量子化ごとに、PCに収まるかどうかの目安が出る |
| Macでなるべく速く動かす | LM Studio | MLX版のモデルを選ぶ |
| システムプロンプトを用途ごとに保存 | LM Studio | プリセットとして保存し、会話ごとに切り替える |
| 手元の文書を読ませて質問する | LM Studio | 添付した文書をPCの中だけで処理する |
| 既存のOpenAI向けアプリをローカルで動かす | どちらでも | 接続先を1234番（LM Studio）か11434番（Ollama）に変える |
| 常にモデルを待ち受けさせる | Ollama | インストールすると常駐する |
| スクリプトやサーバーに組み込む | Ollama | 取得から実行までコマンドで完結する |

ローカルで言語モデルを動かす楽しさは、入力した文章がどこにも出ていかない安心感と、気になるモデルをすぐに手元で確かめられる身軽さにあると思う。Ollamaでその入口に立ったなら、LM Studioは、検索画面で新しいモデルを見つけ、スライダーを動かして自分のPCにちょうどいい設定を探す、という時間を加えてくれる。そこで選んだモデルを1234番ポートで開いておけば、普段使っているアプリが、手元のPCの中で静かに答えを返すようになる。

## 関連記事・おすすめメディア
- [OllamaのVRAM目安は「パラメータ数×0.6GB」から、制作PCで7Bから70Bまでを見積もる](/posts/ollama-vram-memory-guide-2026/)
- [ローカルLLMの量子化、GGUFの数字を読む — Q4とQ5が削るもの、残すもの](/posts/gguf-quantization-q4-q5-guide-2026/)
- [Chromeが自動ダウンロードする4GBのGemini Nanoとは何か、オンデバイスAIの仕組みと停止方法](/posts/chrome-gemini-nano-4gb-2026/)
- [Synologyの2ベイNASを自宅サーバーに、DS225+でスマホの写真とPCのバックアップを1台に集める](/posts/synology-ds225plus-photo-backup-nas-2026/)(自宅に常時動かす機器を置く発想として)
- 今夜はウイスキー・カルチャーの記事やDTM理論の記事も公開予定です → [note はこちら](https://note.com/shining_finger01)
- [【本陣】GitHub Pages で全ての専門記事・深掘りデータベースを読む](https://kingsworksub-jpg.github.io/)
- [Amebaブログ版（ドリンク・酒の科学とレシピ）はこちら](https://ameblo.jp/sfd0501/)
- [note版（厳選ノウハウ・裏側）はこちら](https://note.com/shining_finger01)
