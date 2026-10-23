---
title: "Max for Liveの使い方は、自作より先にLFOのMapボタンから覚える"
description: "Ableton Live 12 SuiteのMax for Liveを、自作に進む前の段階から整理する。3種類のデバイスの置き場所、LFOとMapボタンでつまみを揺らす方法、付属パックの探し方、Editで開いた中身まで順に見ていく。"
images: ["/images/og/max-for-live-device-guide-2026.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-10-21T12:00:00+09:00
scheduled_time: "12:00"
categories: ["software"]
tags: ["Max for Live", "Ableton Live", "Ableton Live 12", "Max", "DTM", "モジュレーション"]
draft: false
---

Ableton Live の上位版である Suite を使っていると、ブラウザの一角に「Max for Live」という項目があるのに気づく。名前からして、自分でプログラムを組むための難しい機能だろうと思って素通りしている人は少なくないと思う。私も最初の半年ほどは、その項目をほとんど開かなかった。

けれど中身を見ていくと、Max for Live は「自作のための道具」である前に、「すでに出来上がったデバイスの詰め合わせ」でもある。Suite には、Max for Live で作られた音源やエフェクトが最初から数多く入っていて、ふつうのエフェクトと同じようにトラックへ置くだけで使える。そのなかには、Live の作り方そのものを少し変えてしまうような道具も含まれている。

この記事では、自分でデバイスを組み始める手前の段階に絞って、Max for Live で何ができるかを整理する。3種類のデバイスの置き場所、いちばん出番の多いLFOとMapボタン、付属のパックとコミュニティのデバイス、そして「Edit」を押して中身を開いたときに何が見えるのか。ここまで分かっていれば、自作に進むかどうかを落ち着いて決められると思う。

## Max for Liveは、Liveの中で動くもう一つのソフト

<figure class="photo photo--left">
<a href="https://www.ableton.com/ja/live/max-for-live/" target="_blank" rel="noopener"><img src="/images/max-for-live/moog.jpg" alt="木枠に収められた大型のモーグ・モジュラーシンセサイザー。多数のつまみとジャックが並ぶパネルの下に鍵盤がある" width="220" height="124" loading="lazy"></a>
<figcaption>1973年製のモーグのモジュラーシンセ。機能ごとの箱をケーブルでつなぐ発想は、Maxの画面にそのまま受け継がれている<span class="credit">Photo: Attila Szász / <a href="https://commons.wikimedia.org/wiki/File:1973_Moog_modular_synthesizer.jpg" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

Max for Live を理解するには、まず「Max」というソフトのことを知っておくと話が早い。Max は、1980年代半ばにフランスの音響研究所 IRCAM でミラー・パケットが開発を始めた、音楽のためのビジュアルプログラミング環境だ。文字でコードを書く代わりに、画面上に「オブジェクト」と呼ばれる小さな箱を並べ、それをケーブルでつないで処理の流れを作る。モジュラーシンセのパッチングを画面の上で行うような感覚に近い。

その後、デヴィッド・ジカレリが創業した Cycling '74 が Max を製品として育て、音声処理や映像処理の機能を加えていった。電子音楽や現代音楽の現場、インスタレーション、大学の研究などで長く使われてきたソフトで、音楽制作の世界では「何でも作れるが、何でも自分で作らなければならない道具」という位置づけだったと思う。

この Max を Live の中で動かせるようにしたのが Max for Live で、2009年に Live 8 と組み合わせる形で登場した。2017年には Ableton が Cycling '74 を買収し、両者の結びつきはさらに強くなった。現在の Live 12 Suite には Max 9 が同梱されていて、別途 Max を買ったりインストールしたりしなくても、Max for Live のデバイスをそのまま使えるし、中身を開いて編集することもできる。

ここで押さえておきたいのは、Max for Live のデバイスは Live のトラックに置くかぎり、ふつうの音源やエフェクトとほとんど同じ扱いになる、という点だ。つまみはオートメーションを書けるし、プリセットとして保存でき、コントローラーから操作することもできる。中で Max が動いていることを意識する場面は、作り始めるまではほとんどない。

## 3種類のデバイスと、ブラウザでの置き場所

Max for Live のデバイスには、オーディオエフェクト、MIDIエフェクト、インストゥルメント(音源)の3種類がある。それぞれ Live 標準のオーディオエフェクト、MIDIエフェクト、音源と同じ位置に置き、同じように信号を受け渡す。オーディオエフェクトは音声を受け取って加工した音声を返し、MIDIエフェクトは鍵盤の情報を受け取って書き換えたものを音源に渡し、インストゥルメントはMIDIを受け取って音を鳴らす。ファイルとしてはどれも「.amxd」という拡張子で保存される。

ブラウザでは、左側の「Max for Live」の項目を開くと、この3種類がフォルダーに分かれて並んでいる。ただし、付属のデバイスの多くは「オーディオエフェクト」や「音源」といった通常のカテゴリーのなかにも混ざって表示されるので、意識しないまま使っていることも多い。後で紹介するLFOやGranulator IIIも、ふつうに検索すればそのまま出てくる。

もう一つ覚えておくと便利なのが、Live 12 で加わったMIDIツールとの関係だ。クリップの画面から呼び出す、フレーズを生成したり変形したりする機能のなかには、Max for Live で作られたものがあり、同じ仕組みで自作のツールを足すこともできるようになった。打ち込みの補助を自分で作りたい人にとっては、ここが Max for Live の新しい入り口になっている。

なお、Max for Live が使えるのは Live 12 の3つのエディションのうち Suite だけだ。Intro と Standard には含まれておらず、追加料金で足す仕組みも今はない。2026年10月時点の直販価格は Intro が14,800円、Standard が49,800円、Suite が89,800円で、下位版からの差額アップグレードも用意されている。

<a class="product-banner" href="https://www.amazon.co.jp/dp/B0CYHNLY74?tag=nakimoto1-22">
<img src="/images/products/ableton-live.png" alt="Ableton Live 12 Suite">
<span class="product-banner-info">
<span class="product-banner-name">Ableton Live 12 Suite</span>
<span class="product-banner-cta">Amazonで見る →</span>
</span>
</a>

## LFOとMapボタンで、どのつまみでも揺らせるようになる

<figure class="photo photo--right">
<a href="https://cycling74.com/" target="_blank" rel="noopener"><img src="/images/max-for-live/modular.jpg" alt="ノートパソコンの画面にMaxのパッチが開き、手前のタブレットにタッチ操作用の画面、奥にモジュラーシンセと小型の鍵盤が並んでいる" width="220" height="146" loading="lazy"></a>
<figcaption>パソコンのMaxでタブレットの操作を受け取り、奥のモジュラーシンセへ送っている机。値を作って別の機械に渡すのは、Maxのいちばん得意な仕事だ<span class="credit">Photo: George P. Macklin / <a href="https://commons.wikimedia.org/wiki/File:Lemur_%E2%87%92_MaxMSP_%E2%87%92_Processing_%E2%87%92_Octomod_%E2%87%92_Modular_Synth.jpg" target="_blank" rel="noopener">CC BY-SA 2.0</a></span></figcaption>
</figure>

既製のデバイスのなかで、最初に覚えておきたいのは LFO だと思う。LFO は音を出さない代わりに、ゆっくり上下する波を作って、その波で別のデバイスのつまみを動かす道具だ。フィルターの周波数を少しずつ開け閉めしたり、パンを左右に揺らしたり、リバーブの量を小節ごとに変えたりといった動きを、オートメーションを1本も書かずに作れる。

使い方は単純で、LFO をトラックに置き、デバイスの「Map」ボタンを押してから、動かしたいつまみをクリックするだけだ。これで LFO の波がそのつまみにつながる。つながったつまみには印が付き、どの値の範囲で動かすかを LFO 側で決められる。波の形はサイン波、三角波、のこぎり波、矩形波、ランダムなどから選べ、速さはヘルツで決めることも、曲のテンポに合わせて拍で決めることもできる。

Live 12 では、この仕組みがさらに使いやすくなった。一つの LFO から複数のつまみへまとめてつなぐ「Multimap」が加わり、フィルターの周波数とレゾナンスを同じ波で逆向きに動かすといった組み合わせが一台で済むようになった。また、モジュレーションはつまみの現在の値を基準に上下する形になり、つないだ後でもつまみを手で回して中心の位置を変えられる。昔は LFO につないだ途端につまみが動かせなくなったので、ここは大きな違いだと感じている。

同じ考え方で働くデバイスがあと二つある。Envelope Follower は、入ってくる音の大きさをなぞって値を作る。キックが鳴るたびにベースのフィルターを閉じる、といった動きをサイドチェインなしで作れる。Shaper は、自分で点を打って描いた形を繰り返し再生する道具で、LFO の決まった波では作れない、段のついた動きや跳ねるような動きに向いている。この三つと Map ボタンの組み合わせを覚えるだけで、Live の音作りの幅はかなり広がると思う。

## 付属のパックとコミュニティのデバイスを探す

<figure class="photo photo--left">
<a href="https://www.ableton.com/ja/push/" target="_blank" rel="noopener"><img src="/images/max-for-live/push.jpg" alt="机の上に置かれたAbleton Push 2。8列8行のパッドが淡いピンクと水色に光り、上部につまみと表示部が並ぶ" width="220" height="293" loading="lazy"></a>
<figcaption>Ableton Push 2。Max for Liveのデバイスも、標準のデバイスと同じように上部のつまみと表示部から操作できる<span class="credit">Photo: Audiotecna Música / <a href="https://commons.wikimedia.org/wiki/File:Ableton_Push_(48477280412).jpg" target="_blank" rel="noopener">CC0</a></span></figcaption>
</figure>

LFO の次に試してほしいのが、Suite に付属するパックに入っている Max for Live のデバイスだ。たとえば Granulator III は、音を細かい粒に分けて並べ直すグラニュラー方式の音源で、作曲家のロバート・ヘンケが作ったものだ。声やピアノの短いサンプルを読み込むだけで、元の音からは想像しにくい持続音や、ざらついた質感の音が作れる。ほかに、部屋の響きを録った音を使って残響を付ける Convolution Reverb や、鍵盤を弾く強さやモジュレーションホイールの動きを別のつまみへ送る Expression Control も、Max for Live で作られたデバイスとして入っている。

パック単位でも探してみるとよい。Creative Extensions は、ふだんのエフェクトでは手が届きにくい音を狙ったデバイスを集めたパックで、ゲート付きのディレイや、変わった効き方をするリミッター、ピッチを崩すエフェクトなどが入っている。Inspired by Nature は、跳ねるボールや木の枝の伸び方のような、物理的な動きを音や旋律に置き換えるデバイスのパックで、見ているだけでも楽しい。モジュラーシンセを持っている人なら、Live から電圧の信号を出して外の機械を動かす CV Tools も役に立つ。

付属品で物足りなくなったら、コミュニティのライブラリ maxforlive.com をのぞいてみるとよい。世界中の作り手が公開したデバイスが集まっていて、多くは無料でダウンロードできる。ダウンロードした .amxd ファイルは、Live のブラウザにドラッグするか、ユーザーライブラリの好きなフォルダーに置けば使える。ただし、作り手によって完成度や更新の頻度に差があり、古い版の Live 向けに作られたまま動かなくなっているものもある。使う前に、対応する Live と Max の版を確かめておくと安心だ。

既製のデバイスを使い込んでいくと、「この LFO にもう一つ機能があれば」「このつまみを別のつまみと連動させたい」という小さな不満が出てくる。その不満こそが、自作に進む手前のいちばん良い材料になると思う。

## Editを押すと見える、デバイスの中身

<figure class="photo photo--right">
<a href="https://www.amazon.co.jp/dp/B0CYHNLY74?tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow"><img src="/images/max-for-live/jdopatch.jpg" alt="Maxのパッチ画面。多数の小さな箱が灰色や赤、紫の線で複雑につながれ、ところどころに英語のコメントが書かれている" width="220" height="145" loading="lazy"></a>
<figcaption>Maxのパッチング画面。一つ一つの箱が処理の単位で、線が値の通り道になっている。Live 12 SuiteにはこのMax 9が同梱されている<span class="credit">Image: Nicolight61 / <a href="https://commons.wikimedia.org/wiki/File:Jdopatch.jpg" target="_blank" rel="noopener">CC BY-SA 3.0</a></span></figcaption>
</figure>

Max for Live のデバイスには、タイトルバーの右側に「Edit」のボタンがある。これを押すと Max のエディターが開き、そのデバイスがどう組まれているかを見ることができる。ここが、ふつうのプラグインとの決定的な違いだ。市販のプラグインの中身は見られないが、Max for Live のデバイスは、付属品もコミュニティのものも、基本的には中身がそのまま開く。

開いた直後は、Live で見ていたのと同じつまみの並んだ画面が表示されていることが多い。これは「プレゼンテーションモード」と呼ばれる、使う人向けの見た目だ。表示を「パッチングモード」に切り替えると、裏側にある箱とケーブルの配線が現れる。最初は線の多さに驚くと思うが、一本の線を指でたどるように追っていくと、どの値がどこから来てどこへ行くのかが少しずつ読めてくる。

配線のなかでよく目にするのが、名前が「live.」で始まる箱だ。live.dial や live.slider は Live のつまみとして振る舞う部品で、ここに置いたつまみがオートメーションやコントローラーの対象になる。live.object、live.path、live.observer といった箱は、Live 本体の情報を読み書きするためのもので、テンポや再生位置、トラックの音量、クリップの中身などに手を伸ばせる。Live の内部をこうして扱う仕組みは「Live Object Model」と呼ばれていて、これを使うと、デバイスの外にある Live そのものを操作する道具も作れる。

分からない箱があったら、その箱を選んでヘルプを開くとよい。Max のほとんどの箱には、実際に動かして試せる見本のパッチがヘルプとして用意されている。中身をいじって壊してしまっても、元のデバイスは別名で保存しない限り付属のライブラリに残っているので、気軽に試せる。また、エディターの「Freeze Device」は、デバイスが使っている外部のファイルを .amxd の中にまとめて閉じ込める機能で、自分で作ったものを他の人に渡すときに必要になる。

## 自作に進む前に決めておきたいこと

ここまで来ると、自作に進むかどうかを考える材料はそろっている。私の考えでは、Max for Live の自作を始める理由として一番健全なのは、「既製のデバイスでは作れない、具体的に一つの動きが欲しい」という状態だと思う。たとえば、特定のトラックの音量に合わせて別のトラックのセンド量を変えたい、決まった小節数ごとにエフェクトのオンとオフを切り替えたい、といった用途だ。目的が一つに絞れていれば、必要な箱も数個で済むことが多い。

最初の一歩としては、ゼロから作るより、既製のデバイスを開いて少しだけ書き換えるほうが入りやすい。LFO の速さの選択肢を自分の曲に合わせて減らす、つまみの範囲を変える、といった小さな改造から始めると、プレゼンテーションモードとパッチングモードの行き来や、live. で始まる部品の扱いに自然に慣れていく。書き換えたものは別名で保存しておけば、元のデバイスを壊す心配もない。

反対に、「何でも作れるらしいから何か作ろう」という始め方は、あまりおすすめしない。Max は自由度が高いぶん、目的が曖昧なまま始めると、何を作るか決められないまま時間だけが過ぎてしまう。そういうときは、もう一度 LFO と Map ボタンに戻って、既製のデバイスで曲を一つ仕上げてみるほうが、結果的に自作の近道になると感じている。

Live 12 の作曲の流れそのものについては、[Ableton Live 12のセッションビューが変える作曲の順番](/posts/ableton-live-12-session-view-2026/)にまとめている。セッションビューでループを並べながら、LFO や Shaper でつまみを揺らしていくと、Max for Live の便利さがいちばん分かりやすく見えてくると思う。

## 関連記事
- [DAW 5本を比べる、机の上のオーケストラを誰に任せるか](/posts/daw-5choice-2026/)
- [VocAlign 7のマルチトラック編集でハモリとダブルをまとめて揃える](/posts/vocalign-7-multitrack/)
- 今夜はウイスキー・カルチャーの記事やDTM理論の記事も公開予定です → [note はこちら](https://note.com/shining_finger01)
- [GitHub Pages で技術・理論記事を読む](https://kingsworksub-jpg.github.io/)
