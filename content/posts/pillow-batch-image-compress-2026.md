---
title: "PythonとPillowで画像を効率的に一括圧縮するスクリプトの実装と例外処理のポイント"
description: "Pillowを使いフォルダ内の画像ファイルを一括で効率よく圧縮・リサイズするPythonスクリプトの作成手順を詳しく解説します。EXIFの自動回転やカラーモードの変換、破損ファイルに備える堅牢な例外処理の実装方法をまとめました。"
images: ["/images/og/pillow-batch-image-compress-2026.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: "2026-11-18T07:34:08+09:00"
categories: ["notes"]
tags: ["Python", "Pillow", "画像処理", "自動化"]
draft: false
scheduled_time: "07:30"
---

配布用の画像やウェブサイト用の素材を大量に扱う際、手動で1枚ずつリサイズや形式変換を行うのは非常に手間がかかります。Pythonの画像処理ライブラリであるPillowを利用すれば、ディレクトリ内の画像を自動で走査し、サイズを調整しながら適切なフォーマットで保存するスクリプトを簡単に構築することができます。本記事では、フォルダの走査から画像のオープン、EXIF情報に基づく向きの修正、高品質なリサンプリングによる縮小、カラーモードの変換、各種フォーマットでの保存、そして破損ファイルなどの例外処理に至るまで、一連の流れに沿った実装方法を整理します。

Pythonで本格的な画像一括処理を行うためには、対応バージョンとしてPython 3.11以上が推奨されています。また、ライブラリとしては強力な機能を持つPillowを使用します。スクリプトを組み立てるにあたっては、処理の各段階で発生しうるエラーを想定し、スクリプト全体が途中で止まってしまわないように堅牢な例外処理を組み込むことが重要です。まずは対象となるディレクトリを安全に走査し、処理対象のファイルを一つずつ確実に読み込むための基本構造から確認していきましょう。

## pathlibを活用したフォルダの走査と画像ファイルの抽出

<figure class="photo photo--left">
<a href="https://commons.wikimedia.org/wiki/File:01_JPEG_JPG_compression_image_quality_degradation_-_comparison_of_photo_quality_and_file_size_saved_with_different_quality_settings.png" target="_blank" rel="noopener"><img src="/images/pillow-compress/01_JPEG_JPG_compression_image_quality_degradation_-_comparison_of_photo_quality_and_file_size_saved_with_different_quality_settings.png" alt="JPEGの品質設定ごとの画質とファイルサイズの比較" width="220" height="150" loading="lazy"></a>
<figcaption>JPEGの圧縮設定ごとの画質とファイルサイズ<span class="credit">Photo: Marek Ślusarczyk (Tupungato) Photo portfolio / CC BY 3.0</span></figcaption>
</figure>

画像一括処理スクリプトの第一歩は、対象となるディレクトリを正確に走査し、処理すべき画像ファイルのみを漏れなくリストアップすることです。標準ライブラリの `pathlib` を使用することで、OSに依存しないパス操作が可能になり、可読性の高いコードを書くことができます。例えば、指定したフォルダ内を再帰的に探索し、特定の拡張子を持つファイルだけを効率よく抽出することが可能です。

フォルダ内のファイルを走査する際は、隠しファイルや画像以外のファイルが混入しているケースを考慮する必要があります。また、ファイル名の大文字・小文字の揺れにも対応できるように拡張子の判定を行います。以下に、`pathlib` を用いて指定ディレクトリ内の画像ファイルを走査し、順次処理するための基本的なコード例を示します。この段階では、ファイルが存在するかどうかを確認しつつ、個別の画像処理パイプラインへ引き渡す準備を行います。

```python
from pathlib import Path

def collect_image_files(target_dir: str):
    source_path = Path(target_dir)
    supported_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    
    image_files = []
    for file_path in source_path.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
            image_files.append(file_path)
            
    return image_files
```

このようにして収集したファイルのリストに対して、次は個別の画像ファイルを開き、向きの修正やリサイズを行う処理を組み込んでいきます。フォルダの構造を保ったまま出力先へ保存する設計にしておくと、後から元の構成と照らし合わせる際にも非常に便利です。

## ImageOps.exif_transposeによる向きの自動補正と高品質リサイズ

<figure class="photo photo--right">
<a href="https://commons.wikimedia.org/wiki/File:JPEG_compression_Example.jpg" target="_blank" rel="noopener"><img src="/images/pillow-compress/JPEG_compression_Example.jpg" alt="JPEG圧縮の前後を比較した例" width="220" height="150" loading="lazy"></a>
<figcaption>JPEG圧縮前後を並べた比較画像<span class="credit">Photo: JJ Harrison, side-by-side comparison by Ibrahim.ID / CC BY-SA 3.0</span></figcaption>
</figure>

スマートフォンやデジタルカメラで撮影した画像には、EXIFのOrientationタグに回転情報が含まれていることが多くあります。これをそのまま縮小・保存すると、意図しない向きで画像が処理されてしまう問題が発生します。Pillowの `ImageOps.exif_transpose` メソッドを使用すると、EXIFのOrientationタグに基づいて画像を自動的に回転・反転させ、オリエンテーション情報をクリーンに削除することができます。これにより、どのような向きで撮影された画像であっても、常に正しい方向を向いた状態で後続の処理を進めることが可能になります。

画像を適切な向きに補正した後は、アスペクト比を維持したまま指定のサイズへ縮小します。Pillowでは `Image.open()` で画像を開いた後、`thumbnail()` メソッドを使用することで、アスペクト比を保持したままインプレースでサイズを計算・変更することができます。このとき、リサンプリングフィルタとして `Image.Resampling.LANCZOS` を指定するのが一般的です。ランチョスフィルタを用いることで、縮小時に発生するモアレや画質の劣化を最小限に抑え、シャープで自然な仕上がりを維持することができます。

縮小処理を実装するコードの例を以下に示します。ここでは、画像を開いた直後にEXIFの転置を行い、その後で目標とする最大サイズに向けて `thumbnail` を呼び出す一連の流れを記述しています。

```python
from PIL import Image, ImageOps

def preprocess_and_resize(image_path: Path, max_size=(1920, 1080)):
    with Image.open(image_path) as img:
        # EXIF情報に基づいて画像を正しい向きに回転・反転する
        img = ImageOps.exif_transpose(img)
        
        # ランチョスフィルタを用いてアスペクト比を保持したまま縮小
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        return img.copy()
```

画像のリサイズが完了した段階で、保存先のフォーマットに応じたカラーモードの調整や、圧縮パラメータの最適化を行う工程へと進みます。特に保存時のモード不一致はエラーの原因になりやすいため、事前のチェックと変換が欠かせません。

## カラーモードの変換とJPEG・WebP形式での最適化保存

<figure class="photo photo--left">
<a href="https://commons.wikimedia.org/wiki/File:Test_-_image_size_comparison_(Jpeg_vs_Png_vs_Jpeg_XL_vs_Heic).png" target="_blank" rel="noopener"><img src="/images/pillow-compress/format-size-comparison.png" alt="各種画像フォーマットのサイズ比較テスト" width="220" height="150" loading="lazy"></a>
<figcaption>各種画像フォーマットのサイズ比較テスト<span class="credit">Photo: LucaLindholm / CC BY 4.0</span></figcaption>
</figure>

画像フォーマットによってサポートしているカラーモードや圧縮アルゴリズムは異なります。例えば、透過情報を持つRGBAモードやパレットモード（Pモード）の画像をそのままJPEG形式で保存しようとすると、内部で例外やエラーが発生してしまいます。これはJPEGがアルファチャンネルをサポートしていないためであり、保存前にRGBモードへ変換するか、必要に応じて白背景に合成する処理を挟む必要があります。

保存時のパラメータ設定も、ファイルサイズを効率的に削る上で重要な要素です。JPEG形式で保存する際は、`quality=80` のような品質設定に加えて、`optimize=True` や `progressive=True` を指定することで、見た目の画質を十分に維持しながらファイルサイズをさらに削減することができます。また、次世代フォーマットであるWebP形式で保存する際は、quality設定に加えて `method=6` を指定することが推奨されています。エンコーダーがより時間をかけて圧縮方法を探索するため、よりファイルサイズを小さくすることが可能です。WebP形式は、一般的な傾向としてJPEGと比較してより高い圧縮効率を持つことが知られており、全体の容量を抑えるために有効な選択肢となります。

以下に、カラーモードの補正と、JPEGおよびWebP形式での保存処理をまとめたコード例を示します。入力された画像のモードを判定し、必要に応じた変換を行った上でそれぞれの形式で書き出します。

```python
def save_optimized_image(img: Image.Image, output_path: Path, format_type: str = "JPEG"):
    # RGBAやPモードの場合、JPEG保存のためにRGBへ変換する
    if format_type.upper() == "JPEG":
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(
            output_path,
            format="JPEG",
            quality=80,
            optimize=True,
            progressive=True
        )
    elif format_type.upper() == "WEBP":
        img.save(
            output_path,
            format="WEBP",
            quality=80,
            method=6
        )
```

このように保存処理を作り込むことで、画質の劣化を抑えつつ、ウェブ配信や配布に適した軽量なファイル群を安定して生成することができます。しかし、大量のファイルを処理する環境では、破損したファイルや想定外に巨大なファイルが混入するリスクを常に考慮しなければなりません。

## 堅牢な例外処理によるエラーファイルの記録と継続処理

大量の画像を一括処理するスクリプトにおいて最も避けたいのは、途中で1つの破損ファイルに遭遇したためにスクリプト全体が停止してしまう事態です。そのため、個別のファイル処理ループ全体を `try/except` ブロックで囲み、予期せぬエラーが発生した場合でも失敗したファイル名をログやリストに記録した上で、次のファイルの処理へスムーズに移行する仕組みが不可欠となります。

Pillowにおける代表的な例外としては、ファイルが破損しているか画像として認識できない場合に発生する `PIL.UnidentifiedImageError` が挙げられます。また、セキュリティ上の制限や極端にピクセル数が多いファイルに起因して、デフォルトのしきい値（MAX_IMAGE_PIXELS）を超える場合に発生する `Image.DecompressionBombError` にも注意が必要です。これらの例外を個別に、あるいはまとめて捕捉し、失敗ファイルとして記録する処理を実装します。必要に応じて、画像の整合性を手軽に検証する `Image.verify()` メソッドを事前に呼び出すアプローチも有効です。

例外処理とファイルごとのループ処理を統合した実用的なスクリプトの全体像を以下に示します。

```python
import logging
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import DecompressionBombError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def batch_compress_images(input_dir: str, output_dir: str):
    source_path = Path(input_dir)
    dest_path = Path(output_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    supported_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    failed_files = []
    
    for file_path in source_path.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in supported_extensions:
            continue
            
        relative_path = file_path.relative_to(source_path)
        output_file_path = dest_path / relative_path.with_suffix(".jpg")
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with Image.open(file_path) as img:
                # 簡易的なファイル整合性チェック
                img.verify()
                
            # verify後は画像を再オープンする必要があるため再度開く
            with Image.open(file_path) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
                
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                    
                img.save(
                    output_file_path,
                    format="JPEG",
                    quality=80,
                    optimize=True,
                    progressive=True
                )
            logging.info(f"成功: {file_path.name} -> {output_file_path.name}")
            
        except UnidentifiedImageError:
            logging.error(f"識別不能または破損した画像です: {file_path}")
            failed_files.append((str(file_path), "UnidentifiedImageError"))
        except DecompressionBombError:
            logging.error(f"ピクセル数が制限を超えています（画像爆弾の可能性）: {file_path}")
            failed_files.append((str(file_path), "DecompressionBombError"))
        except Exception as e:
            logging.error(f"予期せぬエラーが発生しました {file_path}: {e}")
            failed_files.append((str(file_path), str(e)))
            
    if failed_files:
        logging.warning(f"処理に失敗したファイル数: {len(failed_files)}")
        for path, err in failed_files:
            print(f"Failed: {path} ({err})")
```

この実装を取り入れることで、数千枚規模の画像群を処理する際でも、エラーで止まることなく安全にバッチ処理を完結させることができます。Pillowの豊富なAPIを活用した堅牢なスクリプト設計は、日々の開発やデータ整理の効率を大きく高めてくれます。

## あわせて読みたい
- [画像の知覚ハッシュをPythonで比べた記録、縮小では動かず左右反転で30ビット変わる](/posts/python-perceptual-hash-image-compare/)：Pillowで縮小した画像が同一と判定されるかを確かめた検証メモ
- [Pythonの仮想環境、venvとuvの違いは「箱」と「記録」の分担にある](/posts/python-venv-uv-first-environment-2026/)：Pillowを入れる環境をどう分けるかの整理
- [Hugoのビルド時間を測ったら、95秒のうちページの描画は1.3秒だった](/posts/hugo-build-time-measure-2026/)：画像を軽くしたあと、サイト全体のビルドで何が効くかを測った記録

## 関連記事・おすすめメディア
- [はてなブログ版（最新コラム）はこちら](https://kinbro.hatenablog.com/)
- [Amebaブログ版（ドリンク・酒の科学とレシピ）はこちら](https://ameblo.jp/sfd0501/)
- [note版（厳選ノウハウ・裏側）はこちら](https://note.com/shining_finger01)
