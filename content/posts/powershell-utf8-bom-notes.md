---
title: "PowerShell 5.1がBOMなしUTF-8の.ps1を読み違えるとき、消えるのは引用符と改行だった"
description: "PowerShell 5.1はBOMのない.ps1を日本語環境ではShift_JISとして読む。閉じ引用符や改行が消える仕組みをバイト単位で追い、BOM付与・ASCII化・PowerShell 7移行の3つの対策を手順にまとめた備忘録。"
images: ["/images/og/powershell-utf8-bom-notes.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-10-12T07:30:00+09:00
categories: ["notes"]
tags: ["PowerShell", "文字コード", "UTF-8", "BOM", "Shift_JIS", "Windows"]
draft: false
scheduled_time: "07:30"
---

タスクスケジューラから毎朝動かしているPowerShellスクリプトが、ある日いきなり構文エラーで止まった。前日に直したのは、日本語のメッセージを1行足しただけだ。エディタで開くと文字化けもなく、どこにも問題は見えない。原因は文字コードで、Windows PowerShell 5.1が、BOM(バイト順マーク)の付いていないUTF-8のファイルをUTF-8として読んでくれないことにあった。

同じことで二度つまずかないように、仕組みと対策をまとめておく。手元のWindows 11に入っているWindows PowerShell 5.1(5.1.26100)で症状を再現し、どの文字列で壊れ、どの文字列なら通るのかも確かめた。対策は3つある。ファイルにBOMを付ける、スクリプトをASCII文字だけで書く、PowerShell 7へ移る、の3つで、それぞれの手順と向き不向きを最後に表にしている。

## 何が起きているのか、5.1はBOMが無ければShift_JISで読む

<figure class="photo photo--left">
<img src="/images/ps-encoding/mojibake-ja.png" alt="日本語のライセンス表示ページが、文字コードを取り違えて記号の羅列になった画面" width="220" height="172" loading="lazy">
<figcaption>文字コードを取り違えると、日本語は意味のない記号の列になる。これはUTF-8を西欧向けの文字コードで読んだ例<span class="credit">Photo: My own work as derivative of text available under CC 3.0 attrib / <a href="https://commons.wikimedia.org/wiki/File:Mojibake_Japanese_CC_Licence.png" target="_blank" rel="noopener">CC BY 3.0</a></span></figcaption>
</figure>

テキストファイルには、自分がどの文字コードで書かれているかを示す欄がない。読む側が推測するしかなく、その手がかりになるのがファイル先頭のBOMだ。UTF-8なら先頭3バイトが`EF BB BF`、UTF-16LEなら`FF FE`になっていて、これがあればどの文字コードかは迷わずに決まる。

問題はBOMが無いときの扱いだ。Windows PowerShell 5.1は、BOMの無いスクリプトをシステムの既定の文字コード(ANSIコードページ)で読む。日本語版Windowsでは、これがコードページ932、いわゆるShift_JISになる。手元の環境で`[Text.Encoding]::Default`を確かめると、`shift_jis`、コードページ`932`と返ってきた。

一方、いまのエディタの多くは、新しく作ったファイルをBOMなしのUTF-8で保存する。Visual Studio Codeの既定もそうだし、GitやLinux由来の道具もBOMなしを前提にしている。英数字だけのスクリプトなら、UTF-8とShift_JISはどちらも同じバイトになるので何も起きない。日本語のコメントや文字列を1つ入れた瞬間に、書いた側はUTF-8、読む側はShift_JISというすれ違いが表に出てくる。エディタ上では正しく見えるのに実行すると壊れる、という分かりにくさは、ここから来ている。

## 閉じ引用符が消える仕組みを、バイト単位で追う

文字化けだけなら、表示がおかしくなるだけで済みそうに思える。実際には構文エラーになるのは、Shift_JISとして読み直す途中で、日本語の直後にある半角の記号まで巻き込まれることがあるからだ。

UTF-8の日本語は、ひらがな・カタカナ・漢字のほとんどが1文字3バイトになる。Shift_JISは日本語を2バイトで表し、1バイト目(先行バイト)に使う範囲が`81`〜`9F`と`E0`〜`FC`と決まっている。さらに`A1`〜`DF`は1バイトの半角カナとして読まれる。UTF-8の3バイトの並びを、この規則で頭から2バイトずつ、ときどき1バイトずつ切っていくと、文字の切れ目がずれていく。そして日本語の最後のバイトが「先行バイト」として余ったとき、その次にある半角の`"`が2バイト文字の後半として飲み込まれてしまう。

手元でいくつかの言葉を、UTF-8のバイト列のままコードページ932で文字列に戻し、直後に置いた`"`が残るかどうかを見た。

| 文字列 | UTF-8のバイト数 | 末尾の数バイト | 直後の`"`は |
|---|---|---|---|
| ログを保存しました | 27 | `E3 81 9F` | 残る |
| 表示 | 6 | `E7 A4 BA` | 残る |
| 次の行 | 9 | `E8 A1 8C` | 消える |
| 完了 | 6 | `E4 BA 86` | 消える |

「次の行」の場合、`E6 AC`で1文字、`A1`が半角カナで1文字、`E3 81`で1文字、`AE`が半角カナ、`E8 A1`で1文字と切れていき、最後の`8C`が余る。`8C`は先行バイトの範囲に入るので、次の`22`(つまり`"`)と組にされ、どちらも正しい文字にならないまま「・」のような代わりの文字に化ける。文字列を閉じるはずの引用符がここで消えるので、PowerShellは文字列が最後まで閉じていないと判断する。

手元で`Write-Output "次の行"`という1行を含むBOMなしのファイルを5.1に渡すと、`TerminatorExpectedAtEndOfString`(文字列に終端記号がない)という構文エラーで止まった。同じ内容をBOM付きで保存し直すと、何事もなく日本語が表示される。困るのは、壊れるかどうかが文字列の中身しだいで決まることだ。「ログを保存しました」は無事で「完了」は壊れる。昨日まで動いていたスクリプトが、メッセージを1つ書き換えただけで止まる理由はこれだった。

## もっと厄介なのは、エラーにならずに1行消えるケース

<figure class="photo photo--right">
<img src="/images/ps-encoding/winps-commands.png" alt="Windows Terminalで開いた青い背景のWindows PowerShellと、コマンドパレットの一覧" width="220" height="117" loading="lazy">
<figcaption>Windows 11にも、昔ながらの青い背景のWindows PowerShell 5.1が標準で入っている<span class="credit">Photo: Software: Microsoft CorporationScreenshot: PantheraLeo1359531 / <a href="https://commons.wikimedia.org/wiki/File:20231209_19_38_30-PowerShell_Befehlsnamen_crop.png" target="_blank" rel="noopener">MIT</a></span></figcaption>
</figure>

同じことはコメント行でも起きる。コメントの最後のバイトが先行バイトとして余ると、飲み込まれるのは行末の改行コードだ。ここで改行コードがCRLFかLFかで結果が分かれる。

CRLF(`0D 0A`)のファイルなら、飲み込まれるのは`0D`だけで、残った`0A`で行はきちんと終わる。ところがLFだけのファイルでは、唯一の改行がコメントの一部になってしまい、次の行がまるごとコメントの続きとして扱われる。手元で`# 完了`というコメントのあとに`Write-Output`を2行並べたファイルを試すと、CRLF版は2行とも出力されたのに、LF版は1行目が黙って消え、2行目だけが出力された。エラーは一切出ない。

構文エラーで止まってくれるほうが、まだ親切だと思う。変数への代入や、後片付けの処理がこうして消えると、スクリプトは最後まで「正常に」終わったように見える。GitやWSLの道具を経由してファイルを扱っていると、改行コードがいつの間にかLFになっていることも珍しくないので、日本語コメントを入れたスクリプトは特に注意が要る。

## 書き出す側も、コマンドごとに文字コードがばらばら

読み込みの話とは別に、5.1はファイルへ書き出すときの文字コードもコマンドによって違う。同じ「テスト」という文字列をいくつかの方法で書き出し、先頭のバイトを並べた。

| 書き出し方(5.1) | 先頭のバイト | 文字コード |
|---|---|---|
| `Out-File` / `>` リダイレクト | `FF FE C6 30` | UTF-16LE(BOM付き) |
| `Set-Content` / `Add-Content` | `83 65 83 58` | Shift_JIS(BOMなし) |
| `Out-File -Encoding UTF8` | `EF BB BF E3` | UTF-8(BOM付き) |
| `Out-File -Encoding utf8NoBOM` | — | 指定できずエラー |

`>`でログを書いたファイルが、ほかの道具で開くと1文字おきに空白が入ったように見えるのは、UTF-16LEで書かれているからだ。`-Encoding UTF8`を付ければUTF-8にはなるが、5.1では必ずBOMが付く。BOMなしのUTF-8を表す`utf8NoBOM`という値は5.1には無く、指定すると引数の検証で弾かれる。BOMなしで書き出したい場合は、後で触れる.NETのメソッドを直接使うことになる。

## 対策1:スクリプトをBOM付きUTF-8で保存する

いちばん手軽なのはこれだ。BOMがあれば5.1も迷わずUTF-8として読むので、日本語のコメントも文字列もそのまま書ける。Visual Studio Codeなら、画面右下の文字コード表示(「UTF-8」と出ている部分)を押し、「エンコード付きで保存」から「UTF-8 with BOM」を選ぶ。毎回選ぶのが面倒なら、設定ファイル(settings.json)に`"[powershell]": { "files.encoding": "utf8bom" }`と書いておくと、PowerShellのファイルだけ最初からBOM付きで保存されるようになる。

まず、ファイルにBOMが付いているかどうかは、先頭の3バイトを見れば分かる。5.1では次のように確かめられる。

```powershell
Get-Content -LiteralPath .\task.ps1 -Encoding Byte -TotalCount 3
```

`239 187 191`(16進で`EF BB BF`)と返ってくればBOM付きだ。PowerShell 7では`-Encoding Byte`が廃止されているので、代わりに`-AsByteStream`を使う。

既存のファイルをまとめて変換するなら、.NETのメソッドで読み直して、BOM付きのUTF-8で書き戻すのが確実だった。

```powershell
$path = (Resolve-Path -LiteralPath .\task.ps1).Path
$text = [IO.File]::ReadAllText($path, (New-Object Text.UTF8Encoding $false))
[IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $true))
```

`UTF8Encoding`の引数`$true`がBOMを付ける指定で、`$false`なら付けない。`ReadAllText`はBOMがあれば読み飛ばすので、すでにBOM付きのファイルに2回かけてもBOMが二重になることはない。手元でも、変換前は先頭が`23 20 E8`(`# `と日本語の1バイト目)だったファイルが`EF BB BF`で始まるようになり、もう一度かけても変わらないことを確認した。`Get-Content`と`Set-Content -Encoding UTF8`の組み合わせでも変換はできるが、末尾の改行の扱いが変わることがあるので、こちらのほうが差分が少なく済む。

気をつけたいのは、BOMは消えやすいということだ。BOMなしを既定にしているエディタで開いて保存し直したり、テキストを処理する道具を通したりすると、知らないうちに外れる。BOMに頼るなら、先頭3バイトを確かめる上の1行を、テストや保存前のチェックに組み込んでおくと安心できる。

## 対策2:スクリプトはASCIIだけで書く

BOMの有無に左右されたくないなら、スクリプト自体を英数字と記号だけで書いてしまう手もある。ASCIIの範囲は、UTF-8でもShift_JISでも同じバイトになるので、どの読み方をされても壊れようがない。自分の環境では、タスクスケジューラから起動する入口のスクリプトはこの方針にしている。コメントは英語で書き、日本語の処理は呼び出す先の別のプログラムに任せる形だ。

どうしても日本語の文字列を出したい場合は、文字コードの番号から組み立てる。

```powershell
$done = -join ([char[]](0x5B8C, 0x4E86))   # 「完了」
Write-Output $done
```

読みやすさはかなり落ちるので、メッセージが多いスクリプトには向かない。日本語の文言は別のテキストファイルに置き、`Get-Content -Encoding UTF8`で読み込む形にすれば、スクリプト本体はASCIIのまま保てる。ASCII以外の文字が紛れ込んでいないかは、次の1行で行番号つきで洗い出せる。

```powershell
Select-String -Path .\*.ps1 -Pattern '[^\x00-\x7F]'
```

何も表示されなければ、そのスクリプトはどの文字コードで読まれても同じ意味になる。

## 対策3:PowerShell 7へ移る

<figure class="photo photo--left">
<a href="https://learn.microsoft.com/ja-jp/powershell/scripting/install/installing-powershell-on-windows" target="_blank" rel="noopener"><img src="/images/ps-encoding/pwsh-74.png" alt="Windows Terminalで動くPowerShell 7.4.0。$PSVersionTableでバージョンとエディションCoreを表示している" width="220" height="124" loading="lazy"></a>
<figcaption>PowerShell 7は5.1とは別のプログラムとして入り、エディションは「Core」と表示される<span class="credit">Photo: Microsoft Corporation / <a href="https://commons.wikimedia.org/wiki/File:PowerShell_7.4.0_Core_on_Windows_11,_23H2.png" target="_blank" rel="noopener">MIT</a></span></figcaption>
</figure>

根本的に片づけるなら、PowerShell 7へ移るのがいちばん筋がいい。PowerShell 7はBOMの無いファイルをUTF-8として読み、ファイルへの書き出しも既定でBOMなしのUTF-8になる。`Out-File`も`Set-Content`も`>`も同じ`utf8NoBOM`にそろうので、5.1のような「コマンドごとにばらばら」も解消される。今回の問題は、7では最初から起きない。

注意したいのは、PowerShell 7を入れても5.1は置き換わらないことだ。5.1は`powershell.exe`、7は`pwsh.exe`という別のプログラムで、両方が並んで入る。Windows 11でも、スタートメニューの「Windows PowerShell」や、タスクスケジューラの操作に`powershell.exe -File ...`と書いた場合は、相変わらず5.1が動く。タスクスケジューラで7を使うには、操作のプログラム欄に`pwsh.exe`(既定のインストール先なら`C:\Program Files\PowerShell\7\pwsh.exe`)を指定し直す必要がある。手元でも、7を入れたつもりで登録だけ古いまま、という取り違えがいちばん起きやすいと感じた。

もうひとつ、5.1でしか動かないモジュールが残っている環境では、すぐに全部を移せないこともある。その場合は、入口のスクリプトだけ`pwsh.exe`で起動するようにし、5.1が必要な処理は残しておく、という段階的な移り方でも、文字コードの問題はかなり減らせる。

## どれを選ぶか、3つの対策を並べる

最後に、3つの対策を自分なりに比べておく。

| 対策 | 手間 | 日本語の書きやすさ | 壊れにくさ | 向いている場面 |
|---|---|---|---|---|
| BOM付きUTF-8で保存 | 小さい | そのまま書ける | BOMが外れると再発 | 既存の5.1スクリプトをすぐ直したい |
| ASCIIだけで書く | 中くらい | 書きにくい | どの読み方でも壊れない | タスクスケジューラなどの入口のスクリプト |
| PowerShell 7へ移る | 大きい | そのまま書ける | 読み書きともUTF-8で安定 | これから書くもの、長く使うもの |

自分は、無人で動くものは対策2、手で動かす道具は対策3、急ぎの修理は対策1と使い分けることにした。無人のジョブは止まっても誰も気づかないことが多いので、BOMという消えやすい目印に頼らないほうが落ち着く。一方で、手元で使う道具までASCIIに縛ると不便なので、そちらはPowerShell 7で書けばよい。

どの対策を選んでも、日本語が入ったときに先頭3バイトとASCII以外の文字を確かめる2つのコマンドは手元に置いておくと役に立つ。エディタの画面が正しく見えていても、PowerShellがそう読むとは限らない、ということだけは覚えておきたい。

## 関連記事

- [はてなブログ版はこちら](https://kinbro.hatenablog.com/)
- [Amebaブログ版はこちら](https://blog.ameba.jp/)
- [note版はこちら](https://note.com/shining_finger01/n/XXXX)
- 今夜はウイスキー・カルチャーの記事やDTM理論の記事も公開予定です → [note はこちら](https://note.com/shining_finger01)
