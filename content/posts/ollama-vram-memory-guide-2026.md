---
title: "OllamaのVRAM目安は「パラメータ数×0.6GB」から、制作PCで7Bから70Bまでを見積もる"
description: "OllamaでローカルLLMを動かすときのVRAMとメモリの目安を、4bit量子化のモデルサイズとコンテキスト長から計算する方法で解説。8GBから24GBのGPU別に動かせる規模と、DAWと同じPCで使うときの注意点もまとめた。"
images: ["/images/og/ollama-vram-memory-guide-2026.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-10-12T12:00:00+09:00
scheduled_time: "12:00"
categories: ["tech"]
tags: ["Ollama", "ローカルLLM", "VRAM", "GPU", "メモリ", "Windows"]
draft: false
---

歌詞の下書きや、曲ごとの作業メモの整理に言語モデルを使いたいとき、気になるのは入力した文章の行き先だ。未発表の歌詞や、まだ誰にも聴かせていない曲の構想を外部のサービスに送るのは、少しためらいがある。Ollamaを使えば、モデルを一度ダウンロードしたあとは手元のPCだけで文章を生成でき、入力した内容が外に出ることはない。

ただ、ローカルで動かすとなると、次に気になるのは「自分のPCで、どの大きさのモデルまで動くのか」という点になる。7B、13B、70Bといったモデルの数字と、手元のグラフィックボードのVRAMや本体のメモリをどう突き合わせればいいのかは、意外と分かりにくい。この記事では、4bit量子化のモデルを前提に、必要なメモリを自分で見積もる方法を整理する。

## 4bit量子化なら「パラメータ数×0.6GB」が出発点

<figure class="photo photo--left">
<a href="https://www.amazon.co.jp/s?k=GeForce+RTX+3090&tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow"><img src="/images/ollama-vram/rtx3090.jpg" alt="3連ファンを備えたGIGABYTE製GeForce RTX 3090 EAGLEのグラフィックボードを正面から写した写真" width="220" height="147" loading="lazy"></a>
<figcaption>VRAM 24GBのGeForce RTX 3090。ローカルLLMでは、演算性能よりもこの容量のほうが効いてくる<span class="credit">Photo: PantheraLeo1359531 / <a href="https://commons.wikimedia.org/wiki/File:Gigabyte_GeForce_RTX_3090_Eagle_OC_24G,_24576_MiB_GDDR6X_Front_20201114_DSC5880.jpg" target="_blank" rel="noopener">CC BY 4.0</a></span></figcaption>
</figure>

モデル名についている「8B」や「70B」は、パラメータ（重み）の数を表している。8Bなら80億個、70Bなら700億個だ。元の16bitの精度のまま読み込むと、1パラメータあたり2バイト必要なので、8Bのモデルでも16GB、70Bなら140GBになる。これでは一般的なPCには載らない。

そこで使われるのが量子化で、重みを4bit前後まで丸めてファイルを小さくする。Ollamaのライブラリでタグを指定せずに取得すると、多くのモデルはQ4_K_Mという4bit系の形式で配られている。この形式では1パラメータあたりおよそ4.5〜5bitになるので、ざっくり「パラメータ数（B）×0.6GB」と考えると、ダウンロードするファイルの大きさにかなり近い値になる。

ライブラリに表示されている既定のタグのサイズを並べると、この目安がよく当てはまることが分かる。Mistral 7Bが4.4GB、Llama 3.1 8Bが4.9GB、Qwen3 8Bが5.2GB、Qwen3 14Bが9.3GB、Qwen3 32Bが20GB、Llama 3.3 70Bが43GBだ。OpenAIが公開したgpt-oss 20Bは別の4bit形式を使っていて14GB、120Bは65GBになる。

ただし、このファイルサイズがそのまま必要なメモリになるわけではない。モデルを動かすには、重みのほかに「会話の文脈を覚えておく領域」と「計算用の作業領域」が要る。見積もりの式にすると、次のようになる。

必要なメモリ ≒ モデルのファイルサイズ ＋ コンテキスト分のKVキャッシュ ＋ 作業領域1〜2GB

重みの部分は上の目安でほぼ決まるので、差が出るのは真ん中のKVキャッシュだ。ここを見落とすと、ファイルサイズだけ見て「載るはず」と思ったモデルが、実際には収まらないということが起きる。

## コンテキスト長がメモリを食う仕組み

<figure class="photo photo--right">
<a href="https://www.amazon.co.jp/s?k=Kingston+FURY+Impact+DDR5+32GB&tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow"><img src="/images/ollama-vram/ddr5-module.jpg" alt="KINGSTON FURY IMPACTのロゴが入った黒いDDR5のSO-DIMMメモリモジュール" width="220" height="220" loading="lazy"></a>
<figcaption>32GBのDDR5モジュール。VRAMに収まらなかった分は、本体のメモリが受け持つことになる<span class="credit">Photo: ITEagle Europe - Sebastiaan Broekhoven / <a href="https://commons.wikimedia.org/wiki/File:Kingston_FURY_Impact_DDR5_SO-DIMM_Laptop_Memory_32GB_Module_-_front_view.jpg" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

言語モデルは、文章を1トークン生成するたびに、それまでの文脈をすべて参照する。毎回最初から計算し直すと遅すぎるので、過去のトークンについての計算結果をKVキャッシュとして保存しておく。このキャッシュはトークン数に比例して大きくなる。つまり、一度に扱える文脈の長さ（コンテキスト長）を伸ばすほど、メモリが必要になる。

どのくらい増えるかは、モデルの層の数などの構造で決まる。Llama 3.1 8Bを例にすると、標準の16bitのキャッシュで1トークンあたり約128KBになる。コンテキスト長が4,096トークンなら約0.5GBで済むが、32,768トークンに伸ばすと約4GB、128,000トークンまで伸ばすと約16GBになり、重みの4.9GBを大きく上回ってしまう。Llama 3.3 70Bなら1トークンあたり約320KBで、32,768トークンでは約10GBが上乗せされる。

ここで注意したいのは、Ollamaのコンテキスト長の既定値が固定ではないことだ。現在のOllamaは使えるVRAMの量を見て、24GB未満なら4,096トークン、24〜48GBなら32,768トークン、48GB以上なら256,000トークンを自動的に選ぶ。VRAMの大きいGPUほど長い文脈が既定になるので、大きなGPUを積んでいるのに、思ったより小さいモデルしか載らないということが起こりうる。

コンテキスト長は、環境変数 `OLLAMA_CONTEXT_LENGTH` で全体の既定値を決められるほか、モデルごとに `num_ctx` で指定することもできる。歌詞の下書きや短いメモの整理なら、8,192トークンもあれば十分なことが多い。長い文書を丸ごと読ませる用途でなければ、まずコンテキスト長を控えめに固定しておくと、見積もりが立てやすくなる。

KVキャッシュそのものを小さくする方法もある。環境変数 `OLLAMA_KV_CACHE_TYPE` を `q8_0` にすると、キャッシュの大きさはおよそ半分、`q4_0` なら4分の1になる。これはFlash Attention（`OLLAMA_FLASH_ATTENTION`）が有効な状態で働く設定だ。`q8_0` なら文章の質への影響は小さいと感じるので、VRAMが少し足りないときの最初の手として試しやすい。`q4_0` まで下げると、長い文脈での精度が落ちやすくなる。

## VRAM 8GB・12GB・16GB・24GBで動く規模

<figure class="photo photo--left">
<a href="https://ollama.com/download" target="_blank" rel="noopener"><img src="/images/ollama-vram/graphics-card.jpg" alt="グラフィックボードの基板上にあるGPUチップと、周囲に並ぶコンデンサを接写した写真" width="220" height="146" loading="lazy"></a>
<figcaption>GPUチップの周りに実装されたメモリがVRAM。モデルの重みとKVキャッシュがすべてここに収まるかどうかで、速度が大きく変わる<span class="credit">Photo: Nick Stathas / <a href="https://commons.wikimedia.org/wiki/File:A_Complex_Graphics_Card.jpg" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

ここまでの式を、よくあるGPUの容量に当てはめてみる。Windowsでは画面の表示にもVRAMが使われるので、搭載量から0.5〜1GBほど引いた値を「使える量」として考えておくと安全だ。

VRAMが8GBのGPU（GeForce RTX 4060やRTX 3060 Tiの8GB版など）なら、7Bから8Bのモデルがちょうど収まる。Llama 3.1 8Bの4.9GBに、4,096トークン分のキャッシュ0.5GBと作業領域を足しても、7GB前後に収まる。14Bの9.3GBは載らないので、一部が本体のメモリにあふれる。

12GB（RTX 3060の12GB版やRTX 4070など）になると、8Bのモデルでコンテキスト長を16,000トークン程度まで伸ばす余裕が出る。14Bのモデルも、コンテキスト長を短めにすれば収まる。日本語の文章を書かせる用途では、8Bと14Bの差は意外と大きく、言い回しの自然さがかなり変わると感じる。

16GB（RTX 4060 Tiの16GB版やRTX 4070 Ti SUPER、RTX 4080など）なら、14Bのモデルを長めの文脈で使える。gpt-oss 20Bの14GBもこのクラスで動かせる大きさだが、余裕はあまりないので、コンテキスト長は控えめにしておきたい。

24GB（RTX 3090やRTX 4090など）は、32Bのモデルを動かせる最初の段階になる。Qwen3 32Bの20GBに、8,192トークン分のキャッシュ約2GBを足せば、ぎりぎり収まる計算だ。ただし前の節で書いたとおり、使えるVRAMが24GB以上と判定されると既定のコンテキスト長が32,768トークンになり、キャッシュだけで8GB前後になって収まらなくなる。このクラスのGPUでは、`OLLAMA_CONTEXT_LENGTH` を明示しておくほうが確実だ。

70Bのモデルは、43GBの重みだけで24GBのGPU1枚を大きく超える。48GB以上のVRAM（業務用のGPUや、24GBのGPUを2枚）があれば収まるが、一般的な制作PCでは、GPUに載らない分を本体のメモリで受け持つ形になる。

## VRAMに収まらないときに起きること

モデルがVRAMに収まらなくても、Ollamaはエラーで止まらずに動く。層の一部をGPUに、残りを本体のメモリに置いて、CPUとGPUで分担して計算する。どう分担されているかは、モデルを動かした状態で `ollama ps` を実行すると、PROCESSORの欄に「100% GPU」や「48%/52% CPU/GPU」のように表示される。

分担になると、生成の速さは目に見えて落ちる。GPUだけで動いているときは文章が読むより速く流れてくるのに、CPU側に半分ほど回ると、1文字ずつ表示されるのを待つような速さになることが多い。CPU側の計算速度は本体メモリの転送速度に縛られるので、高性能なCPUでも大きくは改善しない。短いメモの整理くらいなら我慢できるが、何度もやり取りしながら歌詞を詰めていくような使い方では、待ち時間がかなり気になる。

本体のメモリの目安も、ここから決まる。モデルが全部GPUに載るなら、本体のメモリはそれほど使わない。一方、70Bを24GBのGPUと分担で動かすなら、GPUに載らない約20GB以上を本体のメモリで受け持つことになり、OSやほかのソフトの分を合わせると64GBは欲しくなる。GPUを使わずCPUだけで動かす場合は、モデルのファイルサイズに数GBを足した量の空きが必要で、8Bなら16GB、14Bなら32GBのメモリが一つの目安になる。

Apple Siliconを積んだMacは事情が少し違う。CPUとGPUが同じメモリを共有するので、本体のメモリがそのままVRAMの役目も果たす。ただしGPUに割り当てられるのは全体の3分の2から4分の3ほどで、32GBのMacならGPUが使えるのは20GB強になる。それでも、32Bのモデルを短い文脈で動かせる計算になり、同じ予算のWindows機と比べて大きなモデルを扱いやすいのは、Macの利点だと思う。

## DAWと同じPCで使うときに気をつけたいこと

制作PCでローカルLLMを動かすときにいちばん気をつけたいのは、DAWとのメモリの取り合いだ。サンプル音源を多く読み込むプロジェクトでは、本体のメモリを20GB以上使うことも珍しくない。そこへ分担で動く大きなモデルを重ねると、メモリが足りなくなってPC全体の動作が重くなる。

Ollamaは、一度読み込んだモデルを最後に使ってから5分間はメモリに残しておく。次の質問にすぐ答えられるようにするための仕組みだが、制作に戻ったあともしばらくはVRAMやメモリを占有し続けることになる。録音やミックスに入る前には `ollama stop <モデル名>` でモデルを解放しておくと安心だ。常に短く切り上げたいなら、環境変数 `OLLAMA_KEEP_ALIVE` で残しておく時間を短くできる。

また、CPUと分担して生成している間は、CPUの負荷がかなり高くなる。録音中や、バッファサイズを小さくして演奏しているときに生成を走らせると、音の途切れにつながりかねない。歌詞やメモの作業は、DAWを止めているときにまとめてやるほうが落ち着いて使える。

ストレージも見ておきたい。WindowsではモデルがユーザーフォルダのなかのOllama用フォルダ（`.ollama\models`）に保存され、8Bで5GB前後、70Bなら40GB以上を使う。サンプルライブラリでシステムドライブが埋まりがちな制作PCでは、環境変数 `OLLAMA_MODELS` で保存先を別のドライブに移しておくと扱いやすい。

## 自分のPCに当てはめる手順

最後に、ここまでの内容を手順としてまとめておく。

| 手順 | やること | 目安 |
|---|---|---|
| 1 | GPUのVRAM容量を確認し、表示に使う分を引く | 搭載量から0.5〜1GB引く |
| 2 | 動かしたいモデルのファイルサイズを見る | 4bitならパラメータ数×0.6GB |
| 3 | 使うコンテキスト長のKVキャッシュを足す | 8Bで4,096トークン約0.5GB、32,768トークン約4GB |
| 4 | 作業領域を足す | 1〜2GB |
| 5 | 合計がVRAMに収まるか確かめる | `ollama ps` が「100% GPU」なら収まっている |
| 6 | 足りなければ調整する | コンテキスト長を短く、KVキャッシュを `q8_0` に、一段小さいモデルへ |

VRAMの目安を一つだけ覚えておくなら、「8GBで8B、12GBから16GBで14B、24GBで32B」という対応だと思う。歌詞の言い回しを考えたり、作業メモを整理したりする用途なら、8Bから14Bのモデルでも十分役に立つ。まずは手元のGPUに収まる大きさのモデルから始めて、足りないと感じたら、コンテキスト長とKVキャッシュの設定を見直してから、モデルを一段大きくするか考えるのがいいと思う。

## 関連記事
- [ローカルLLMの量子化、GGUFの数字を読む — Q4とQ5が削るもの、残すもの](/posts/gguf-quantization-q4-q5-guide-2026/)
- [Whisperの日本語文字起こしはどのサイズから実用になるか、tinyからlarge-v3-turboまで](/posts/whisper-model-size-japanese-benchmark-2026/)
- [Windows 11 26H2で減った起動時メモリ、DAWの制作PCで効く設定と効かない設定](/posts/windows-11-26h2-memory-daw-2026/)
- 今夜はウイスキー・カルチャーの記事やDTM理論の記事も公開予定です → [note はこちら](https://note.com/shining_finger01)
- [GitHub Pages で技術・理論記事を読む](https://kingsworksub-jpg.github.io/)
