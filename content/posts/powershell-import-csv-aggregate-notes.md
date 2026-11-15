---
title: "PowerShellのImport-Csvで集計すると、なぜ「12」が「7」より下に並ぶのか"
description: "PowerShellのImport-Csvは数字をすべて文字列で返す。並べ替えと比較で起きる取り違え、Measure-ObjectとGroup-Objectでの集計、Shift_JISのCSVと書き出しの文字コード、10万行での速さとメモリを手元で確かめた記録。"
images: ["/images/og/powershell-import-csv-aggregate-notes.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-11-15T09:30:00+09:00
categories: ["notes"]
tags: ["PowerShell", "CSV", "Import-Csv", "Group-Object", "Measure-Object", "文字コード", "Windows"]
draft: false
scheduled_time: "07:30"
---

月末になると、売上や作業時間を書き出したCSVを受け取って、店舗ごと・商品ごとの合計を出す作業がある。毎回表計算ソフトを開き、ピボットテーブルを組み直していたが、やることは毎月同じだ。それならPowerShellで数行書いておけば、ファイルを差し替えて実行するだけで済む。

ところが最初に書いた並べ替えで、数量「12」の行が「7」より下に来てしまった。原因は、`Import-Csv` が読み込んだ値をすべて文字列として扱うことにある。この記事では、その仕組みを確かめたうえで、合計・平均・グループごとの集計、文字コード、書き出し、行数が多いときの速さまで、よく使う書き方を手元の環境で一通り試した結果を残しておく。使ったのはWindows 11に標準で入っているWindows PowerShell 5.1(5.1.26100)で、PowerShell 7系との違いはそのつど書き添えている。

## 試したデータ、8行の売上CSV

<figure class="photo photo--left">
<a href="https://en.wikipedia.org/wiki/Comma-separated_values" target="_blank" rel="noopener"><img src="/images/ps-csv/example-csv.png" alt="会社名・姓・名の3列をカンマで区切った、4行だけの簡単なCSVファイルの中身" width="220" height="67" loading="lazy"></a>
<figcaption>CSVは1行が1件、カンマが列の区切り。1行目を見出しにするのが一般的<span class="credit">Photo: Belbury / <a href="https://commons.wikimedia.org/wiki/File:Example_CSV_file.png" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

CSV(カンマ区切り値)は、1行を1件のデータとし、列をカンマで区切っただけのテキストファイルだ。古くから使われてきた形式だが、きちんとした取り決めとして文書になったのは2005年のRFC 4180で、カンマや改行を含む値はダブルクォートで囲む、値の中のダブルクォートは2つ重ねる、といった規則がここで整理されている。`Import-Csv` もこの規則に沿って読むので、住所のようにカンマを含む値でも、クォートで囲まれていれば1つの列として扱ってくれる。

試すために、日付・店舗・商品・数量・単価の5列を持つ、8行だけの小さなCSVを用意した。数字の並べ替えで差が出るように、数量には1桁と2桁を混ぜてある。

```text
日付,店舗,商品,数量,単価
2026-11-01,渋谷,コーヒー豆,3,1200
2026-11-01,新宿,紅茶,12,450
2026-11-02,渋谷,紅茶,5,450
2026-11-02,池袋,コーヒー豆,2,1200
2026-11-03,新宿,コーヒー豆,1,1200
2026-11-03,池袋,マグカップ,4,980
2026-11-04,渋谷,マグカップ,10,980
2026-11-04,新宿,紅茶,7,450
```

読み込みは `$rows = Import-Csv .\sales.csv` の1行で終わる。1行目が見出しとして使われ、2行目以降の各行が「日付」「店舗」などの名前を持つオブジェクトになる。列の名前は日本語のままでよく、`$rows[0].店舗` と書けば「渋谷」が返ってくる。区切りがタブのファイルなら `` -Delimiter "`t" `` を付け、見出し行の無いファイルなら `-Header` で列名を配列として渡す。

## Import-Csvが返すのは、文字列だけを持ったオブジェクト

<figure class="photo photo--right">
<a href="https://learn.microsoft.com/powershell/" target="_blank" rel="noopener"><img src="/images/ps-csv/ps-window.png" alt="Windows Terminalの中で開いた紺色の背景のWindows PowerShell。コマンドの実行結果が色付きの文字で並んでいる" width="220" height="117" loading="lazy"></a>
<figcaption>Windows 11には、紺色の背景のWindows PowerShell 5.1が最初から入っている<span class="credit">Photo: Neofetch: Dylan Araps * Windows Terminal/Windows PowerShell: Microsoft Corporati / <a href="https://commons.wikimedia.org/wiki/File:20231209_12_55_13-Neofetch_PowerShell_crop.png" target="_blank" rel="noopener">MIT</a></span></figcaption>
</figure>

読み込んだ行の型を確かめると、行そのものは `PSCustomObject`、数量の値は `System.String` だった。CSVには「この列は数値」という情報が書かれていないので、`Import-Csv` は見た目が数字でも区別せず、すべてを文字列として持たせる。表計算ソフトのように中身を推測して数値に変えたりはしない。

これを知らずに `Sort-Object 数量 -Descending` と書くと、文字列として辞書順に並ぶ。先頭の1文字から比べるので、「12」と「10」は「1」で始まる値として扱われ、「7」や「5」より後ろに来る。手元での結果を並べると次のようになった。

| 書き方 | 並び(数量の大きい順のつもり) |
|---|---|
| `Sort-Object 数量 -Descending` | 7, 5, 4, 3, 2, 12, 10, 1 |
| `Sort-Object { [int]$_.数量 } -Descending` | 12, 10, 7, 5, 4, 3, 2, 1 |

並べ替えの基準に `{ [int]$_.数量 }` というスクリプトブロックを渡し、比べる前に整数へ変換すれば、期待どおりの順になる。小数を含む列なら `[double]` を使う。

もっと気づきにくいのが、`Where-Object` での絞り込みだ。PowerShellの比較演算子は、左側の値の型に右側を合わせて比べる。`Where-Object { $_.数量 -ge 5 }` と書くと、左が文字列なので右の5も文字列の「5」として比べられ、数量5以上の4行のうち、引っかかったのは「7」と「5」の2行だけだった。左右を入れ替えた `{ 5 -le $_.数量 }` なら数値として比べられて4行になるが、読み手が意図を追いにくい。`{ [int]$_.数量 -ge 5 }` のように、型を明示して書くのがいちばん確実だと思う。エラーが出ないまま件数だけが違うので、集計結果がなんとなく少ないと感じたら、まずここを疑うことにしている。

文字列のまま持ってくれることには、良い面もある。商品コードや郵便番号のように先頭に0が付く値は、表計算ソフトで開くと数値と見なされて0が消えることがあるが、`Import-Csv` なら「0349」は「0349」のまま残る。数として計算したい列だけ、使う場面で型を変えればよい。

## 合計・平均・最大はMeasure-Objectに任せる

合計を出すだけなら、型のことをあまり気にしなくてよい。`Measure-Object` は渡された値を数値として計算してくれるので、`$rows | Measure-Object 数量 -Sum -Average -Maximum -Minimum` と書くと、件数8、合計44、平均5.5、最大12、最小1が返ってきた。最大値の型を見ると `System.Double` になっていて、内部で数値に変換してから比べていることが分かる。並べ替えでは「7」が最大に見えたのに、こちらでは12が最大になる。この違いは覚えておくと役に立つ。

1つ注意したいのは、数値に変換できない値が混ざったときだ。「1,200」のような桁区切りのカンマは解釈してくれて、1,200として合計された。一方で「1200円」のように単位が付いていると、「数値ではない」というエラーで止まる。そうした列は `ForEach-Object { $_.単価 -replace '[,円]', '' }` で余計な文字を取り除いてから `Measure-Object` に渡すとよい。

PowerShell 7系では、`-StandardDeviation`(標準偏差)と、すべての統計値をまとめて出す `-AllStats` も使える。5.1でパラメーターの一覧を確かめると、この2つは存在しなかった。ばらつきまで見たいときは7系を入れておくと楽になる。

## Group-Objectで店舗ごとにまとめる

<figure class="photo photo--left">
<a href="https://en.wikipedia.org/wiki/Spreadsheet" target="_blank" rel="noopener"><img src="/images/ps-csv/sum-formula.png" alt="表計算ソフトの画面で、セルにSUM関数を入力し、右側の関数一覧にSUM・AVERAGE・MIN・MAXが並んでいる" width="220" height="123" loading="lazy"></a>
<figcaption>表計算ソフトのSUMやAVERAGEにあたる処理を、PowerShellではMeasure-Objectが受け持つ<span class="credit">Photo: Arlo Barnes / <a href="https://commons.wikimedia.org/wiki/File:SUM_formula_in_LibreOffice_Calc.png" target="_blank" rel="noopener">CC0</a></span></figcaption>
</figure>

「店舗ごとの合計」のように、グループに分けて集計するには `Group-Object` を使う。`$rows | Group-Object 店舗` と書くと、店舗名ごとに `Count`(件数)・`Name`(グループの値)・`Group`(そのグループに入った行の一覧)を持つオブジェクトが返る。今回のデータでは渋谷3件、新宿3件、池袋2件だった。件数だけ分かればよいときは `-NoElement` を付けると、行の一覧を持たない分だけ軽くなる。

合計まで出すには、グループごとに `Group` の中身を `Measure-Object` に渡し、結果を新しいオブジェクトに組み立てる。表計算でいうピボットテーブルの役目を、次の数行が果たす。

```powershell
$rows | Group-Object 店舗 | ForEach-Object {
    [pscustomobject]@{
        店舗   = $_.Name
        件数   = $_.Count
        数量計 = ($_.Group | Measure-Object 数量 -Sum).Sum
        売上   = ($_.Group | ForEach-Object { [int]$_.数量 * [int]$_.単価 } |
                  Measure-Object -Sum).Sum
    }
} | Sort-Object 売上 -Descending
```

結果は渋谷が数量18・売上15,650円、新宿が数量20・売上9,750円、池袋が数量6・売上6,320円の順になった。数量では新宿がいちばん多いのに、売上では単価の高いコーヒー豆とマグカップが出ている渋谷が上に来る。こうして並べ替えの基準を変えて見比べられるのが、自分で集計を書く面白さだと思う。売上は掛け算をする前に `[int]` で数値にしている。文字列のまま `"3" * "1200"` とすると、文字列の繰り返しになってしまうからだ。

複数の列でまとめたいときは `Group-Object 店舗,商品` のように並べる。このとき `Name` は「渋谷, コーヒー豆」というカンマ区切りの1つの文字列になり、個々の値は `Values` プロパティに配列で入る。今回のデータでは7つの組み合わせに分かれた。あとで特定のグループだけを取り出したいなら、`Group-Object 商品 -AsHashTable -AsString` でハッシュテーブルにしておくと、`$h['紅茶']` のように名前で直接引ける。`-AsString` は5.1でも使えた。

列を足したいだけのときは `Select-Object` の計算プロパティが便利だ。`Select-Object 日付,商品,@{Name='金額';Expression={[int]$_.数量*[int]$_.単価}}` と書けば、元の列に「金額」の列を加えた行が流れていく。`Name` は `n`、`Expression` は `e` と短く書いても通る。

## 文字コード、表計算ソフトで保存したCSVはShift_JISのことが多い

<figure class="photo photo--right">
<a href="https://en.wikipedia.org/wiki/Comma-separated_values" target="_blank" rel="noopener"><img src="/images/ps-csv/csv-import-wizard.png" alt="表計算ソフトのCSV読み込み画面。文字コードにUnicode(UTF-8)、区切りにカンマが選ばれ、下に先頭が0の請求番号の列がプレビューされている" width="220" height="270" loading="lazy"></a>
<figcaption>表計算ソフトのCSV読み込み画面。文字コードと区切り文字を選ぶ欄がある。Import-Csvでは、これを-Encodingと-Delimiterで指定する<span class="credit">Photo: Valerio Bozzolan / <a href="https://commons.wikimedia.org/wiki/File:LibreOffice_6.4_import_CSV_file_wizard.png" target="_blank" rel="noopener">CC0</a></span></figcaption>
</figure>

日本語のCSVでつまずきやすいのが文字コードだ。日本語版のExcelで「CSV(コンマ区切り)」を選んで保存すると、ファイルはShift_JIS(コードページ932)になる。「CSV UTF-8(コンマ区切り)」を選べば、BOM付きのUTF-8になる。受け取ったCSVがどちらなのかで、読み込み方を変える必要がある。

5.1の `Import-Csv` は、BOMが無いファイルをUTF-8として読む。スクリプトファイルそのものはBOMが無いとShift_JISとして読む5.1だが、`Import-Csv` の既定は逆になっていて、ここは混同しやすい。同じ内容のCSVを3種類の文字コードで保存し、`-Encoding` の指定を変えて読んだ結果をまとめた。

| ファイルの文字コード | 指定なし | `-Encoding Default` |
|---|---|---|
| UTF-8(BOMなし) | 正しく読める | 文字化けし、列の区切りまで崩れる |
| UTF-8(BOM付き) | 正しく読める | 正しく読める |
| Shift_JIS | 文字化けする | 正しく読める |

`Default` は、日本語版Windowsでは「システムの既定の文字コード」、つまりShift_JISを意味する。BOM付きのUTF-8はBOMが優先されるので、どちらの指定でも読めた。厄介なのはBOMなしのUTF-8を `Default` で読んだときで、文字化けだけでなく、日本語の直後にあるカンマが2バイト文字の一部として飲み込まれ、5列のはずが3列に減っていた。値がずれた列に入るので、集計すると数字がでたらめになる。

5.1の `-Encoding` に指定できるのは、`UTF8`・`Default`・`Unicode` など8つの名前だけで、`-Encoding 932` と書くと引数の検証で弾かれた。PowerShell 7系では、BOMの無いファイルの既定がBOMなしのUTF-8になり、`-Encoding 932` や `-Encoding shift_jis` のようにコードページの番号や名前で指定できる。7.4以降は `-Encoding Ansi` という書き方もある。5.1でShift_JIS以外の文字コードを読みたいときは、`Get-Content` で文字列として読んでから `ConvertFrom-Csv` に渡すと、同じオブジェクトが得られる。

## Export-Csvで書き出すと、5.1では日本語が「??」になる

集計結果をファイルに残すには `Export-Csv` を使う。ここでも5.1には落とし穴が2つあった。

1つ目は、何も指定しないと先頭に `#TYPE System.Management.Automation.PSCustomObject` という1行が入ること。PowerShellで読み戻すための型の情報だが、表計算ソフトで開くと1行目がこの文字列になってしまう。5.1では `-NoTypeInformation` を付けて消す。7系ではこの行が既定で出なくなった。

2つ目のほうが深刻で、5.1の `Export-Csv` は文字コードを指定しないとASCIIで書き出す。手元で集計結果をそのまま書き出すと、見出しの「店舗」「件数」も、値の「渋谷」も、すべて「??」に置き換わっていた。ASCIIには日本語の文字が無いので、変換できない文字が疑問符になる。エラーは出ず、元に戻す手段もない。

日本語を含むCSVを5.1で書き出すなら、`-NoTypeInformation -Encoding UTF8` の2つを付けるのが基本になる。5.1の `UTF8` は必ずBOMを付けるので、日本語版のExcelでダブルクリックして開いても文字化けしない。7系の既定はBOMなしのUTF-8で、そのまま開くと文字化けしやすいため、Excelで開く前提のファイルは `-Encoding utf8BOM` を指定する。7系には値をクォートで囲むかどうかを選ぶ `-UseQuotes` もあり、`AsNeeded` にすると必要な値だけが囲まれる。既存のファイルに行を足す `-Append` は5.1でも使える。

## 10万行で測った速さとメモリ

8行のデータなら何を書いても一瞬で終わるので、10万行(約3.8MB)のCSVを作って測り直した。店舗5つ、商品4つをランダムに混ぜ、店舗ごとの数量の合計を出す処理を、書き方を変えて比べている。環境はCore i5-1235U、メモリ16GBのノートPCと、Windows PowerShell 5.1だ。

| 処理 | 時間 |
|---|---|
| `Import-Csv` で全行を変数に読み込む | 0.87秒 |
| `Group-Object` と `Measure-Object` で集計 | 0.81秒 |
| `foreach` 文でハッシュテーブルに足し込む | 0.25秒 |
| `ForEach-Object` でハッシュテーブルに足し込む | 0.55秒 |

結果の合計はどの方法でも一致した。`Group-Object` は書きやすい反面、すべての行をグループごとに抱え込むので、単純な合計だけならハッシュテーブルに `$acc[$row.店舗] += [int]$row.数量` と足していくほうが3倍ほど速い。とはいえ10万行でも1秒前後なので、月に一度の集計なら書きやすさで選んでかまわないと思う。

差がはっきり出たのはメモリだ。10万行を変数に読み込むと、それだけで約127MBを使っていた。元のファイルの30倍を超える。1行ごとに列名付きのオブジェクトを作るので、どうしても大きくなる。一方、`Import-Csv .\big.csv | ForEach-Object { ... }` のように変数に入れずパイプラインで1行ずつ流し、その場でハッシュテーブルに足していくと、増えたメモリは1.3MBで済んだ。数百万行のログを扱うなら、全行を変数に入れず、流しながら集計する書き方にしておくのが安全だ。

## よく使う書き方のまとめ

試した書き方を、あとで引けるように並べておく。

| やりたいこと | 書き方 |
|---|---|
| 読み込む | `$rows = Import-Csv .\sales.csv` |
| Shift_JISのCSVを読む(5.1) | `Import-Csv .\sales.csv -Encoding Default` |
| Shift_JISのCSVを読む(7系) | `Import-Csv .\sales.csv -Encoding 932` |
| 数値として並べ替える | `Sort-Object { [int]$_.数量 } -Descending` |
| 数値として絞り込む | `Where-Object { [int]$_.数量 -ge 5 }` |
| 合計・平均・最大・最小 | `Measure-Object 数量 -Sum -Average -Maximum -Minimum` |
| グループごとの件数 | `Group-Object 店舗 -NoElement` |
| 列を足す | `Select-Object *,@{n='金額';e={[int]$_.数量*[int]$_.単価}}` |
| 書き出す(5.1) | `Export-Csv .\out.csv -NoTypeInformation -Encoding UTF8` |
| 書き出す(7系、Excel向け) | `Export-Csv .\out.csv -Encoding utf8BOM` |

覚えておくことは、結局のところ3つに絞れる。値はすべて文字列で届くので、並べ替えと比較では `[int]` を付ける。読み込みは受け取ったCSVの文字コードに合わせて `-Encoding` を選ぶ。5.1で書き出すときは `-NoTypeInformation -Encoding UTF8` を忘れない。この3つを押さえておけば、表計算ソフトを開かずに済む集計はかなり増える。毎月の作業は、ファイル名を差し替えて実行するだけになった。

## 関連記事

- [PowerShell 5.1がBOMなしUTF-8の.ps1を読み違えるとき、消えるのは引用符と改行だった](/posts/powershell-utf8-bom-notes/)
- [Windowsのシンボリックリンクをmklinkで作る、ジャンクションとの違いとrmdirで消す理由](/posts/windows-symbolic-link-mklink-notes/)
- [Windowsの時短はどこから始めるか、標準のショートカットとランチャーを優先度順に並べる](/posts/windows-shortcuts-launcher-guide-2026/)
- [Pythonの仮想環境、venvとuvの違いは「箱」と「記録」の分担にある](/posts/python-venv-uv-first-environment-2026/)
- [はてなブログ版はこちら](https://kinbro.hatenablog.com/)
- [Amebaブログ版はこちら](https://ameblo.jp/sfd0501/)
- [note はこちら](https://note.com/shining_finger01)
