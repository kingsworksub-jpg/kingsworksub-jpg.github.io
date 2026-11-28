# X Accounts Project

## 1. 目的

このサブプロジェクトは、`@100labjtvn` を対象に、Xアカウントの成長（主にフォロワー増加と質の高いエンゲージメント獲得）を継続的に改善する **コンサルティング・デプロイ型の自動運用エコシステム** を定義する。

ブログ自動化システムと同様に、**LLM多段フォールバック**を用いて日次で分析・施策立案・反映・再評価を回し、運用を継続的に最適化する。

## 2. 背景（2026-11-22 時点の初期観測）

公開プロフィールとローカル運用情報から確認できた初期状態:

- フォロワー: **380**
- フォロー中: **1,630**
- 投稿数: **1,313**（2026年9月参加）
- プロフィール: 趣味列挙型Bio、Fan account 表示
- 直近投稿傾向: ブログ/note告知リンク中心。表示・いいね・返信が伸びにくい投稿が多い
- 既存X運用: `post-to-x.py` / `x_llm.py` / `x-following-reply.py` 等による自動投稿・返信・いいね・フォロバ/DM・非相互整理の仕組みが存在

仮説:
- フォロー/フォロワー比率、告知偏重、自動化の量的運用、発信軸の散らばりが成長を抑えている可能性が高い。

## 3. ゴール / KPI

### 北極星指標
- **質の高いフォロワー純増数**（bot/スパムを除く、関心軸に合致したフォロワー）

### 主要KPI
- フォロワー純増（日次/週次/30日）
- プロフィールクリック数、プロフィール経由フォロー転換
- 投稿あたり表示数、エンゲージメント率（いいね・返信・RP・保存相当の観測可能指標）
- 返信率・会話継続率（自分発信→返信→会話成立）
- フォロー/フォロワー比率の健全化
- 自動施策ごとの効果（施策前後比較）

### ガードレール指標（悪化時は自動停止/巻き戻し）
- ネガティブ反応の増加（ブロック、通報、DM拒否、低品質返信の増加）
- 表示数・エンゲージメント率の急落
- 重複投稿/定型投稿率の上昇
- 自動化起因の失敗（投稿失敗、誤返信、ポリシー違反リスク）

## 4. スコープ

### 対象
- Xアカウント `@100labjtvn` の運用最適化
- 日次アカウント分析
- 分析結果に基づく、投稿戦略・生成プロンプト・自動運用パラメータの調整
- 調整結果の再分析と改善ループ
- **現行のX関連自動化システムすべてを本サブプロジェクトの管理対象として統合管理すること**

### 管理対象の現行X運用システム（2026-11-22 時点）

| 区分 | タスク/機能 | 主な実体 | 現行役割 | 備考 |
|---|---|---|---|---|
| 投稿配信 | ブログ公開時のX投稿 | `scripts/post-to-x.py` | ブログ/note公開に連動した告知投稿 | 記事公開フローから利用 |
| 自動返信 | 通知ベース自動返信 | `blog-x-reply-task` / `scripts/scheduled/run-x-reply.ps1` / `scripts/post-to-x.py --auto-replies` / `scripts/x_llm.py` | 自分宛返信への自動返信 | 現行は抑制運用（CLAUDE.md参照） |
| フォロー運用 | 新規フォロワー対応 | `blog-x-follow-task` / `scripts/scheduled/run-x-follow-dm.ps1` / `scripts/post-to-x.py --check-new-followers` | フォローバック（現行は `--no-dm`） | DM方針は高リスク変更 |
| いいね運用 | 自動いいね | `scripts/scheduled/run-x-auto-like.ps1` / `scripts/x-auto-like.py` | タイムライン等への自動いいね | 稼働状態・上限は運用定義で管理 |
| TL返信 | フォロー中TLへの返信・着地いいね | `blog-x-following-reply-task` / `scripts/scheduled/run-following-reply.ps1` / `scripts/x-following-reply.py` / `scripts/x_llm.py` | フォロー中投稿への返信・会話着地 | ループ実行型 |
| フォロー整理 | 非相互フォロー整理 | `blog-x-unfollow-task` / `scripts/schedule-unfollow.ps1` / `scripts/x-unfollow-non-mutual.py` | 非相互候補の抽出・整理 | 共有プロファイル/ミューテックス運用 |
| LLM基盤 | 生成・フォールバック | `scripts/x_llm.py`, `scripts/model_chains.py` | X系生成・モデル多段フォールバック | 用途別チェーンを管理対象に含む |
| ブログ連携投稿 | 記事→X投稿 | `scripts/oc_generate.py`, `scripts/scheduled/prompts/blog-post.md`, `scripts/post-to-x.py` | ブログ公開後に軸適合記事のみX投稿 | 2026-11-22調整: 軸フィルタ必須、定型宣伝禁止、URL毎回禁止（9.4） |
| 共通基盤 | プロファイル/状態/排他 | `data/x_user_data/`, `data/x-*.json`, `Local\kingsworksub-blog-x-jobs` mutex | ログイン状態、状態管理、同時実行制御 | 読み取り/書き込みの監査対象 |
| 日次コンサル | アカウント分析/レポート（Phase 1-2） | `scripts/x_consultant.py`, `scripts/scheduled/run-x-consulting.ps1`, `scripts/schedule-x-consulting.ps1`, `blog-x-consulting-task` | 日次スナップショット収集・KPI算出・レポート/HTML/提案生成（読み取り専用） | LLM診断は多段フォールバック、失敗時fail-safe。deployヒントは指標ベース決定論ルールのみ |
| 限定デプロイ | 安全な手動適用（Phase 3） | `scripts/x_deploy.py`, `data/x-consulting/managed-limits.json`, `data/x-consulting/deployments/` | allowlist対象の低リスク変更を承認後に手動適用 | tighten-only、diff/rollback/cooldown/日次上限あり。自動配線なし（4A） |
| 効果検証 | 採否判定（Phase 4） | `scripts/x_verify.py`, `data/x-consulting/evaluations/`, `run-x-consulting.ps1` | 配信済みdeploymentの前後KPI比較、adopt/hold/rollback判定 | 決定論ルールのみ。既定はrecommend-only、rollback自動適用は明示フラグ時のみ |
| ブログ生成プロンプト自動調整 | ブログ別レポート→canonical_platform別の記事生成LLM（2026-11-28） | `scripts/blog_prompt_config.py`, `scripts/blog_consultant.py`, `scripts/oc_generate.py`, `scripts/scheduled/run-blog-consulting.ps1`, `data/blog-consulting/managed-prompts.json` | 指標ベースの `prompt_set` 提案を allowlist/step/cooldown 付きで適用し、次回記事生成プロンプトへ反映 | 自由文のプロンプト書き換えは禁止。設定はプラットフォーム別で `canonical_platform` の値だけを適用。X と同じ deploy/verify 基盤を使用 |

> 注: 上表は2026-11-22時点でリポジトリから確認できた現行構成の棚卸し。タスクの有効/無効、実行頻度、上限値、実際の稼働状態は **Task Scheduler・実行ログ・状態ファイル** を正として確認し、変更時は本書を更新する。

### 対象コンポーネント（既存/新規）
- 既存: 上表の現行X運用システム一式（スクリプト、スケジュール、状態ファイル、プロンプト、ログ、運用ルール）
- Phase 1 実装済み: `scripts/x_consultant.py`, `scripts/scheduled/run-x-consulting.ps1`, `scripts/schedule-x-consulting.ps1`, `scripts/model_chains.py` の `X_CONSULTING_CHAIN`
- Phase 3 実装済み: `scripts/x_deploy.py`（allowlist/tighten-only/dry-run/diff/rollback/cooldown/日次上限、手動実行のみ）
- Phase 4 実装済み: `scripts/x_verify.py`（決定論KPI比較、adopt/hold/rollback判定、既定recommend-only、直近14日のモデル成功率/施策優先度の決定論最適化ヒント出力）、`run-x-consulting.ps1` から定期評価を実行
- 新規（今後）: LLM/統計ベースの高度な最適化（自動チェーン書き換えは未実装・要承認）、提案承認フローUI/運用、設定・履歴ストアの拡張

### 非対象（初期フェーズ）
- X公式API契約前提の機能
- 有料広告運用の自動最適化
- 他SNSアカウントの横断最適化（将来拡張）

## 5. 設計原則

1. **観測に基づく改善**: 印象ではなく、日次データと施策前後差分で判断する。
2. **小さく試して検証する**: 一度に大きく変えず、変更単位を小さくして効果を測定する。
3. **自動化は品質優先**: 量的な自動反応より、信頼・会話・フォロー転換を優先する。
4. **安全な自動変更**: プロンプト/設定の自動変更は差分記録・上限・ロールバック可能にする。
5. **LLM多段フォールバック**: 単一モデル障害・品質低下時に次段モデルへ自動退避する。
6. **人間の最終責任**: 高リスク変更（プロフィール変更、DM方針、大幅な自動化拡大）は承認ゲートを設ける。
7. **定義の一元管理**: X関連のルール・運用・システム構成を変更した場合は、**必ず本書（`x-accounts-project.md`）を同時に更新**し、現行運用定義との乖離を残さない。

## 6. システム概要（Consulting Deploy Ecosystem）

日次で以下の閉ループを回す。

```text
[Observe]  アカウント/投稿/運用ログを収集
    ↓
[Analyze]  KPI計算・異常検知・勝ち/負けパターン抽出
    ↓
[Diagnose] 課題仮説と優先度付け（コンサルティング）
    ↓
[Plan]     施策案を生成（投稿内容/プロンプト/運用パラメータ）
    ↓
[Deploy]   安全な範囲で自動反映（または承認待ち）
    ↓
[Verify]   翌日以降の効果測定・採用/却下/ロールバック
    ↺
```

## 7. コンポーネント設計

### 7.1 Observer（収集）
- **入力**: Xプロフィール、直近投稿、投稿メトリクス、既存 `data/x-*` 状態、実行ログ
- **方法**: 既存Playwrightプロファイル（読み取り専用）を優先。取得不能時は取得可能範囲で継続。
- **出力**: 日次スナップショットJSON、投稿単位メトリクス、運用ログ要約

### 7.2 Analyzer（分析）
- フォロワー増減、投稿タイプ別パフォーマンス、時間帯/形式/トピック傾向を算出
- 告知投稿 vs ネイティブ投稿、長文 vs 短文、質問型/意見型/比較型などの分類
- 異常検知: 急落、ゼロ反応連続、重複率上昇、自動化失敗増加

### 7.3 Consultant（診断・施策立案）
- LLMが「何が効いた/効いていない/次に試すべきこと」を構造化して出力
- 施策は必ず **根拠データ・期待効果・リスク・検証方法・ロールバック条件** を持つ
- 出力は機械可読（JSON）＋人間可読（Markdown）を併記

### 7.4 Deployer（反映）
- 低リスク施策は自動反映、高リスク施策は承認待ち
- 反映対象は差分パッチとして保存し、即時ロールバック可能にする

### 7.5 Verifier（検証）
- 施策ごとに評価期間（例: 24h/72h/7d）を設定
- 効果が閾値未満なら自動停止・ロールバック・次仮説へ

## 8. LLM多段フォールバック方針

既存の `scripts/model_chains.py` / `scripts/x_llm.py` の思想を踏襲し、用途別チェーンを分離する。

| 用途 | 方針 | 例（初期案） |
|---|---|---|
| 日次分析・要約 | 読み取り・構造化出力重視 | `google/gemini-3.5-flash-lite` → `google/gemini-3.5-flash#high` → `opencode/deepseek-v4.1-flash-free` |
| 施策立案（コンサル） | 推論・比較・優先度付け重視 | `google/gemini-3.5-flash#high` → `google/gemini-3.5-flash-lite` → `opencode/longcat-2.5-free` |
| 投稿/返信文生成 | 文体・安全性・短文品質重視 | 既存 `x_llm.py` チェーンを基準に調整 |
| 設定変更提案のJSON生成 | 厳密なJSON/スキーマ準拠重視 | 構造化出力に強いモデルを優先、失敗時フォールバック |

運用ルール:
- 全段失敗時は **変更を適用しない**（fail-safe）。
- 出力はJSONスキーマ検証を必須化し、不正な出力は採用しない。
- モデル別の成功率・遅延・コスト・品質を記録し、チェーン順を定期見直しする。

## 9. 自動調整の対象

### 9.1 自動調整OK（低リスク）
- 返信/DM生成プロンプトの文体・禁止事項・長さ制約
- 投稿ミックス比率（告知/ネイティブ/質問/比較/失敗談など）
- 投稿候補の優先順位付けルール
- ハッシュタグ数・配置・CTA文言のガイドライン
- 自動いいね/返信/フォロー関連の上限値（**より安全な方向への変更のみ自動可**）

### 9.2 承認必須（高リスク）
- プロフィール文・表示名・アイコン・ヘッダー変更
- DM送信の有効化/方針変更
- 自動化上限の引き上げ
- 外部リンク戦略の大幅変更
- 新しい自動投稿系列の追加

### 9.3 禁止
- 誤認・釣り・炎上誘導・スパム的行為
- 事実確認できない断定の量産
- ポリシー違反やユーザー信頼を損なう自動化
- アカウント軸から外れた汎用記事の自動X投稿（リンク付き定型宣伝の連投）

### 9.4 Xブログ連携投稿ワークライン（2026-11-22調整、1+2採用）

**目的**: フォロワー離脱/低反応を招く「軸ズレ + 定型宣伝投稿」を抑え、@100labjtvn の人柄と軸に合う投稿だけをXへ出す。

**1) 投稿軸フィルタ（必須ゲート）**
- Xへ自動投稿してよい軸: JAZZ/ROCK/音楽鑑賞・演奏・機材、ウィスキー/葉巻/酒/バー文化、オーディオ/DTM/電子機器/ガジェット/工作、服/革靴/小物/スタイル、StudioNotes的な「色気と無駄」。
- 原則スキップ: 汎用PC/スマホセキュリティ手順、汎用家電・節電・生活ハウツー、汎用SNS/配信テクニック、汎用AIニュース要約、アカウントの人柄が見えないSEO汎用記事。
- 境界線上はスキップ。スキップ時は「X skipped: off-pillar (<理由>)」をログに残し、ブログ公開自体は成功扱い。

**2) 文面フォーマット**
- `meta.json` の `x_post` はネイティブ短文（1投稿1視点）。感想・気づき・問いかけ・現場の一言を優先。
- 禁止寄り: 「まとめました」「解説しました」「紹介します」「ガイド」など定型宣伝文の多用。
- ハッシュタグは0〜2個。誇張・煽り（「必見」「永久保存版」等の多用）は避ける。
- **記事URLは毎回入れない**。自然に役立つ場合のみ付与。付与する場合は原則 GitHub Pages URL。

**実装反映先**
- `scripts/oc_generate.py`: `x_post` 生成ルールをネイティブ文面・URL任意へ更新
- `scripts/scheduled/prompts/blog-post.md`: 手順7.4に投稿前ゲート・文面ルール・URL任意を反映
- `scripts/x_consultant.py`: promo判定シグナル（`まとめました/解説/紹介/ガイド`）は監視指標として維持

## 10. 日次実行フロー（1日1回）

1. **00:xx Snapshot**: アカウント/投稿/ログ収集、日次スナップショット保存
2. **Analyze**: KPI算出、前日比・7日比・施策別評価
3. **Diagnose/Plan**: LLMが施策案JSON + レポートMarkdown生成
4. **Deploy**: 低リスク変更は提案/ヒント化。既定は手動承認後に `x_deploy.py` で適用（差分・ロールバック記録あり、自動配線なし）
5. **Report**: `data/x-consulting/reports/YYYY-MM-DD.md` と `xaccounting-reports.html`（KPI/推移グラフ/診断/検証）を出力更新
6. **Verify**: `x_verify.py` が過去deploymentの前後KPIを比較し adopt/hold/rollback を判定（既定recommend-only）

実行基盤は既存の Windows Task Scheduler + PowerShell + Python スクリプト構成に合わせる。

## 11. データ/ファイル設計

```text
x-accounts-project.md                 # 本定義書（正本）
xaccounting-reports.html              # [Phase 1実装] 日次更新の可視化ダッシュボード（KPI/グラフ）
scripts/
  x_consultant.py                     # [Phase 1-2実装] 日次収集・KPI算出・LLM診断・レポート/HTML/提案生成（読み取り専用）
  x_deploy.py                         # [Phase 3実装] 安全な手動反映（allowlist/diff/rollback/cooldown）
  x_verify.py                         # [Phase 4実装] 効果検証・adopt/hold/rollback判定（既定recommend-only）
  x_llm.py                            # 既存: 返信/DM生成（拡張対象）
  model_chains.py                     # 既存: フォールバックチェーン（X_CONSULTING_CHAIN 追加済み）
scripts/scheduled/
  run-x-consulting.ps1                # [Phase 1,4実装] 日次実行ランナー（consulting + verify）
scripts/
  schedule-x-consulting.ps1           # [Phase 1実装] Task Scheduler登録
data/
  x-consulting/                       # .gitignore対象（生成物）
    snapshots/YYYY-MM-DD.json         # 日次観測データ
    analyses/YYYY-MM-DD.json          # KPI・分類・LLM診断
    proposals/YYYY-MM-DD.json         # [Phase 2実装] 施策案（機械可読）
    proposals/YYYY-MM-DD.md           # [Phase 2実装] 施策案（人間可読）
    reports/YYYY-MM-DD.md             # 日次レポート（人間可読）
    deployments/<id>.json             # [Phase 3実装] 適用差分・結果
    managed-limits.json               # [Phase 3実装] 管理対象上限値（tighten-only）
    evaluations/YYYY-MM-DD.json       # [Phase 4実装] 効果検証結果
    state.json                        # 実行状態
```

命名・配置は既存規約に合わせて調整済み。未実装項目はフェーズ進行時に追加する。

## 12. 変更管理と安全装置

- **定義ファースト更新**: X運用に関わるルール、スケジュール、上限値、プロンプト方針、対象スクリプト、タスク構成を変更したら、**実装変更と同じ変更セットで `x-accounts-project.md` を更新**する。運用定義の正本は本書とする。
- **現行構成の棚卸し更新**: 管理対象システムの追加・廃止・改名・有効/無効切替・頻度/上限変更があった場合は、「4. スコープ > 管理対象の現行X運用システム」表を更新する。
- **差分管理**: 自動変更は必ず before/after を保存する。
- **ロールバック**: KPI悪化・失敗時に前版へ戻せる。
- **変更上限**: 1日あたりの自動変更件数・変更幅を制限する。
- **クールダウン**: 同種施策の連続変更を抑制し、評価期間を確保する。
- **ドライラン**: `--dry-run` で収集・分析・提案まで実行し、反映しない。
- **監査ログ**: いつ・何を・なぜ・どのモデル出力で変更したかを記録する。

## 13. 評価サイクル

- **日次**: 収集・異常検知・小施策の実行
- **週次**: 勝ちパターン/負けパターンの棚卸し、チェーン/プロンプト見直し
- **月次**: KPIレビュー、発信軸・プロフィール・運用方針の再定義

施策判定:
- **Adopt**: KPI改善かつガードレール問題なし
- **Hold**: データ不足、継続観測
- **Rollback**: 悪化またはリスク発生

## 14. 初期実装フェーズ

### Phase 0: 定義・計測設計（本ドキュメント）
- KPI、データ項目、変更可能範囲、ガードレールを確定

### Phase 1: 観測・日次レポート（読み取り専用）【初期実装済み】
- `scripts/x_consultant.py` が Playwright（既存 `data/x_user_data`）でプロフィール/直近投稿を収集
- ローカル `data/x-*` 状態から運用シグナルを集計
- `X_CONSULTING_CHAIN` によるLLM診断（失敗時fail-safe）を実施
- `data/x-consulting/{snapshots,analyses,reports}/` に日次成果物を出力
- **`xaccounting-reports.html`** をルートに出力更新し、KPI・推移グラフ・上位投稿・診断/次アクションを可視化
- `scripts/scheduled/run-x-consulting.ps1` + `scripts/schedule-x-consulting.ps1` で日次実行（`blog-x-consulting-task`, 07:10）を登録可能
- **自動変更は行わない**

### Phase 2: 提案型コンサルティング【初期実装済み（提案生成）】
- `scripts/x_consultant.py` が日次で `data/x-consulting/proposals/YYYY-MM-DD.json/.md` を生成
- 各アクションに `risk/metric/horizon_days/requires_approval/auto_apply` を付与
- deployヒントは **指標ベースの決定論ルールのみ**で付与（LLM出力は使用しない）。allowlist/tighten-only/cap内を満たす場合のみ `actions[].deploy` を付与し、`auto_safe=false` を既定とする
- **現時点では提案のみ（自動適用なし）**。承認後の反映は手動で実施

### Phase 3: 限定デプロイ【初期実装済み（手動承認・安全基盤）】
- `scripts/x_deploy.py` を実装（allowlist、dry-run、diff記録、rollback、日次上限、クールダウン）
- 現在の反映対象は **低リスクな上限値の上下調整**（`data/x-consulting/managed-limits.json`）と、
  **ブログ記事生成プロンプトの allowlist ノブ**（`data/blog-consulting/managed-prompts.json`: `BLOG_MIN_BODY_CHARS` /
  `BLOG_HEADING_MIN` / `BLOG_CTA_LEVEL` / `BLOG_DEPTH_STYLE`）。プロンプト設定は
  `github` / `hatena` / `ameba` / `note` ごとに別保持で、cooldown も `platform + key` 単位
- 対応キー: `X_MAX_AUTO_REPLIES_PER_DAY`, `X_MAX_REPLIES_PER_DAY`, `X_FOLLOWUP_MAX_LIKES_PER_DAY`, `X_MAX_LIKES_PER_DAY`
- `post-to-x.py` / `x-following-reply.py` / `x-auto-like.py` は managed-limits を読み取り、**ハードキャップ以下への引き下げのみ**適用
- 提案JSONの `actions[].deploy` ヒントから適用可能（`--auto-safe` は `auto_safe=true` のみ対象）。**既定運用は手動承認後のCLI実行（自動配線なし, 4A）**
- rollback は冪等性を確保（`rolled_back_at` 記録済みは `--force` なしで拒否）。rollback成功時は復元キーの cooldown を監査ログ付きで解除（1A/2A）
- 2026-11-28 ユーザー指示で自動調整対象を拡張: `prompt_set`（`scripts/blog_prompt_config.py` の allowlist ノブ）を適用可能とした。
  `data/blog-consulting/managed-prompts.json` の `prompts/<platform>/` に before/after を保存し、
  `scripts/oc_generate.py` が次回記事生成で **`canonical_platform` の設定だけ**を読み込む。
  これにより1ブログの指標が全ブログのプロンプトを書き換えない。
- **LLMによるプロンプト本文の自由書き換え・DM方針変更・プロフィール変更は自動適用しない**（ノブ単位の切り替えのみ）。

### Phase 4: 閉ループ最適化【初期実装済み（検証基盤）】
- `scripts/x_verify.py` を実装: `data/x-consulting/deployments/*.json` と `analyses/YYYY-MM-DD.json` を比較し、KPI差分から `adopt/hold/rollback` を決定論判定
- 出力: `data/x-consulting/evaluations/YYYY-MM-DD.json`、`state.json` に最新評価サマリを記録
- 既定は **recommend-only**。rollback自動適用は `python scripts/x_verify.py --apply-rollbacks` 明示時のみ（`x_deploy.rollback_deployment()` を使用）
- `scripts/scheduled/run-x-consulting.ps1` で consulting 実行後に verify を自動実行（`-SkipVerify` で無効化可）
- `scripts/scheduled/run-blog-consulting.ps1` は4ブログの提案から `prompt_set` をまとめてデプロイし、
  同verify基盤で `data/blog-consulting/history/<platform>.json` のKPIを **プラットフォーム別・14日窓**で評価する。
  1つでも悪化判定なら deployment 全体を自動ロールバックする（`-SkipDeploy` / `-SkipVerify` で無効化可）
- 日次レポート/HTMLに最新評価サマリを表示
- 決定論的な最適化ヒントを `evaluations/YYYY-MM-DD.json` の `optimization` として出力（直近14日モデル成功率ランキング、推奨チェーン候補、施策優先度）。**自動でチェーン書き換えはしない**

## 15. リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| 自動変更が品質低下を招く | エンゲージメント悪化 | 低リスク限定、差分管理、ロールバック、ガードレール |
| LLMの誤分析/誤生成 | 不適切な施策 | スキーマ検証、多段フォールバック、根拠データ必須 |
| X UI変更で収集失敗 | 分析停止 | 取得失敗を許容する設計、失敗通知、部分データ継続 |
| 過剰最適化 | 短期指標のみ改善 | 北極星指標＋信頼指標を併用、週次/月次レビュー |
| 自動化臭の増加 | フォロワー離脱 | ネイティブ投稿比率、手動レビュー枠、DM/量的反応の抑制 |

## 16. 成功条件

- 日次で観測→分析→施策→検証が止まらず回る
- 施策の採否がデータで説明できる
- フォロワー純増だけでなく、プロフィール転換・会話品質が改善する
- 自動化が「量」ではなく「成長に効く運用」に寄与している
