# AI-Native Performance Engineering PoC

性能試験結果を、

**Pythonによる決定論的判定**  
＋  
**AIによる分析支援**  
＋  
**人間による最終判断**

に分離したPoCです。

## Quick Overview

```text
Locust
  ↓
FastAPI
  ↓
CSV / manifest
  ↓
Python deterministic analysis
  ↓
JSON / Markdown
  ↓
AI hypothesis generation
  ↓
Human review
```

### 検証シナリオ

| シナリオ | 内容 | 期待結果 |
|---|---|---|
| 正常系 | 閾値内かつbaselineから大きな劣化なし | PASS |
| 性能劣化 | 絶対閾値内でもbaseline比で性能劣化 | FAIL |
| エラー増加 | レスポンスタイム正常でもエラー率超過 | FAIL |

### 設計方針

- p95 / p99 / エラー率 / RPSの数値判定はPythonで実施
- baselineとの性能回帰もPythonで決定論的に判定
- AIはPASS / FAILを決定しない
- AIは原因を断定せず、傾向・仮説・追加確認項目を提示する
- 最終的な原因判断・性能評価・リリース判断は人間が行う
- 閾値はPoC用の暫定値とし、実案件ではSLA/SLO・利用モデル・業務要件から決定する

### Test Status

```bash
pytest -q
```

```text
18 passed
```

---

## これは何か

性能試験の結果分析で、

**「数値的事実」と「原因仮説」を分離する**

ことを目的としたPoCです。

現場で生成AIを利用する場合、

「AIに性能試験結果を渡したところ、根拠が十分でないにもかかわらず原因を断定した」

という問題が起こる可能性があります。

そのため本PoCでは、

- 数値計算
- 閾値判定
- baseline比較
- PASS / FAIL判定

をPythonの決定論的ロジックで行います。

AIはその結果をもとに、

- 性能劣化の傾向
- リスク候補
- 原因仮説
- 追加調査項目

を整理する役割に限定しています。

---

## 背景

「AI × 性能試験」というテーマについて、自分自身で

**AIにどこまで任せてもよいのか**

を検証するために作成しました。

単にLocustを動かすことではなく、

**性能試験 → 機械判定 → AI分析 → Human Review**

という一連のプロセスを検証対象としています。

---

## 分かったこと / 工夫した点

- 閾値判定・baseline差分検出はPythonの決定論的ロジックとして実装
- AIには数値計算やPASS / FAIL判定を任せない
- AIには「数値の解釈」「リスク候補」「原因仮説」「追加調査案」を担当させる
- 証拠のないCPU / DB / ネットワーク等の原因断定を禁止
- Locust実行結果からp95 / p99 / エラー率 / RPSを自動評価
- ウォームアップ区間を評価対象から除外
- ウォームアップ終了時にLocustの累積統計をリセット
- 最終累積エラー率と、一時的な最大エラー率を分離
- baselineと比較対象の条件が異なる場合は回帰判定を抑止
- baseline値が0の場合は無理に変化率を算出せず `NOT_EVALUATED` とする
- 正常系・性能劣化・エラー増加をpytestでテスト
- JSON / Markdownレポートをschema version `1.0` として固定
- 負荷試験そのものの実行成否と、性能基準のPASS / FAILを分離

---

## このPoCで仮設定した標準

| 項目 | 仮設定 | 理由 |
|---|---|---|
| 負荷試験ツール | Locust 2.40.4 / headless | Pythonでシナリオを実装でき、CIから実行しやすい |
| 一次データ | Locust `*_stats_history.csv` | 時系列の応答時間・件数・失敗数を機械処理できる |
| 実行証跡 | `manifest.json` | ツール、対象環境、負荷条件、実行コマンドを残す |
| 機械判定結果 | JSON | CI連携や再分析に利用する |
| 人向けレポート | Markdown | 根拠、リスク、追加確認をレビューしやすい |
| Report Schema | `1.0` | 出力フォーマットを固定する |

これらは実案件での採用決定ではなく、PoCでの検証用の暫定案です。

実案件では、

- 既存基盤
- SLA / SLO
- 業務ピーク
- 監視方式
- セキュリティ制約

などを確認した上で決定します。

---

## 全体像

1. FastAPIの検証用APIを起動する
2. `config/test_plan.json` から負荷条件を読み、Locustを実行する
3. Locust結果をCSVとして保存する
4. Pythonでp95 / p99 / エラー率 / RPSを評価する
5. manifestでbaselineとの比較可能性を確認する
6. baselineとの差分を決定論的に判定する
7. JSON / Markdownレポートを生成する
8. AIが傾向・リスク・原因仮説を整理する
9. 人間が最終判断する

---

## 0. セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShellでは、

```powershell
.venv\Scripts\Activate.ps1
```

を使用します。

---

## 1. FastAPIを起動

```bash
uvicorn app.main:app --reload --port 8000
```

別ターミナルから確認します。

```bash
curl http://127.0.0.1:8000/health

curl \
  "http://127.0.0.1:8000/items?delay_ms=20&fail_rate=0&limit=3"
```

`delay_ms` と `fail_rate` は、意図的に性能劣化やエラー増加を発生させるためのPoC専用パラメータです。

---

## 2. シナリオと判定基準

負荷条件は、

```text
config/test_plan.json
```

判定基準は、

```text
config/thresholds.json
```

に分離しています。

現在のPoCでは、

```text
warmup_seconds = 10秒

p95 <= 250ms
p99 <= 500ms
error rate <= 1%

CPU <= 80%    : WARN
Memory <= 85% : WARN

baseline比
p95悪化 <= 20%
p99悪化 <= 20%
median RPS低下 <= 20%
```

を暫定値として設定しています。

これらは業界標準値を意味するものではありません。

**判定ロジックを再現可能にするためのPoC用固定値**です。

実案件ではSLA / SLO、利用モデル、ピーク負荷、業務要件から決定します。

### シナリオ

- `smoke` : 疎通確認
- `baseline` : 性能比較元
- `regression` : 性能劣化検証
- `stress` : 限界傾向確認

dry-runも可能です。

```bash
python scripts/run_scenario.py \
  baseline \
  --run-id baseline-v1 \
  --dry-run
```

---

## 3. Locustで負荷試験

```bash
python scripts/run_scenario.py \
  baseline \
  --run-id baseline-v1

python scripts/run_scenario.py \
  regression \
  --run-id regression-v1
```

成果物は、

```text
results/runs/<run-id>/
```

以下に保存されます。

主な成果物は、

```text
locust_stats_history.csv
manifest.json
```

です。

`manifest.json` には、

- ツール
- 対象
- シナリオ
- ユーザー数
- spawn rate
- duration
- warm-up設定
- 実行条件

などを記録します。

---

## 4. サンプルデータを分析

```bash
python performance-test-analysis/scripts/analyze_results.py \
  data/degraded.csv \
  --baseline data/baseline.csv \
  --thresholds config/thresholds.json \
  --output-json results/sample-analysis.json \
  --output-md results/sample-analysis.md
```

性能基準を超過した場合、

```text
FAIL
```

となります。

CPU・Memoryについては、単独で性能不合格の根拠とせず、

```text
WARN
```

として原因調査を促します。

---

## 5. 実際のLocust結果を分析

```bash
python performance-test-analysis/scripts/analyze_results.py \
  results/runs/regression-v1/locust_stats_history.csv \
  --baseline results/runs/baseline-v1/locust_stats_history.csv \
  --manifest results/runs/regression-v1/manifest.json \
  --baseline-manifest results/runs/baseline-v1/manifest.json \
  --thresholds config/thresholds.json \
  --output-json results/locust-analysis.json \
  --output-md results/locust-analysis.md
```

比較条件が一致している場合だけbaselineとの回帰判定を行います。

条件が異なる場合は、

```text
NOT_COMPARABLE
```

として回帰判定を抑止します。

---

## ウォームアップ区間の扱い

性能試験開始直後は、

- ユーザー数増加途中
- キャッシュ未形成
- リクエスト件数不足

などにより、一時的な値が性能評価へ大きく影響する可能性があります。

本PoCでは、

```text
evaluation.warmup_seconds
```

で指定した期間を評価対象から除外します。

現在は、

```text
10秒
```

を設定しています。

さらにLocust側でも、ウォームアップ終了後に、

```python
runner.stats.reset_all()
```

を実行します。

これにより、その後の定常区間を新しい測定期間として扱います。

分析レポートには、

```text
## Evaluation window

- Warm-up seconds: 10
- Current rows excluded: ...
- Baseline rows excluded: ...
- Current stats reset detected: True
- Baseline stats reset detected: True
```

のように評価窓を記録します。

---

## エラー率の扱い

Locustのリクエスト数・失敗数は累積値です。

試験開始直後はリクエスト数が少ないため、少数のエラーでも一時的に高いエラー率になります。

そのため本PoCでは、

| 指標 | 用途 |
|---|---|
| 最終累積エラー率 | PASS / FAIL判定 |
| 観測期間中の最大エラー率 | 途中経過・参考情報 |

として分離します。

最終累積エラー率は、

```text
最終累積失敗数
÷
最終累積リクエスト数
× 100
```

で算出します。

一時的なエラー集中についても無視せず、最大値としてレポートに残します。

---

## スループット回帰の扱い

応答性能が悪化すると、同じユーザー数でも単位時間あたりの処理量が低下する可能性があります。

そこで、

```text
baselineのmedian RPS
```

と、

```text
比較対象のmedian RPS
```

を比較します。

計算式は、

```text
RPS低下率 =
（baseline RPS - current RPS）
÷ baseline RPS
× 100
```

です。

現在のPoCでは、

```text
20%
```

を許容上限としています。

ただしRPSは、

- 負荷生成側
- ネットワーク
- 実行環境
- wait time

などにも影響されます。

そのため、RPS低下だけからアプリケーション原因とは断定しません。

---

## baselineが0の場合

相対変化率では、baselineが0の場合に正常な百分率を計算できません。

そのため本PoCでは、

```text
baseline = 0
```

の場合、

```text
0%変化
```

とは扱わず、

```text
NOT_EVALUATED
```

とします。

無理に数値を生成して誤ったPASS判定を行わないための設計です。

---

## 6. 判定の責任分界

本PoCでは、性能試験におけるAIの役割を、

**分析支援**

に限定します。

### Python

Pythonが担当するもの：

- p95 / p99の計算
- エラー率の計算
- RPSの集計
- 閾値比較
- baseline比較
- 回帰率計算
- PASS / FAIL判定

### AI / Codex Skill

AIが担当するもの：

- 性能劣化傾向の整理
- リスク候補の提示
- 原因仮説の整理
- 追加確認項目の提案
- 必要なログ・メトリクスの提示

AIは、

```text
DBが原因です
```

のような原因断定を行いません。

例えば、

```text
DB接続待ちの可能性があります。

確認するためには、
接続プール利用率、
SQL実行時間、
ロック状況、
DB CPUなどの確認が必要です。
```

という仮説・追加調査形式で出力します。

### Human

人間が担当するもの：

- 性能要件の決定
- 閾値の決定
- AI仮説の検証
- 原因の最終判断
- 改善策の決定
- 性能評価の承認
- リリース可否判断

> AIは原因を決定するためではなく、人間の調査・判断を支援するために利用します。

### Principles

1. AIは性能試験のPASS / FAILを決定しない。
2. AIは測定データだけから原因を断定しない。
3. AIが提示する原因は仮説として扱う。
4. 数値判定はPythonによる決定論的ロジックで行う。
5. 最終的な性能評価・原因判断・リリース判断は人間が行う。

---

## 実行成否と性能判定

負荷試験が技術的に完走したことと、

**性能要件を満たしたこと**

は別です。

Locustには、

```text
--exit-code-on-error 0
```

を指定しています。

そのため意図的なHTTP 503などが発生しても、負荷試験自体は最後まで実行できます。

| 判定 | 意味 | 判定主体 |
|---|---|---|
| 実行ステータス | 負荷試験自体が正常終了したか | runner |
| 性能判定 | 性能基準を満たしたか | Python分析 |

例えば、

```text
試験完走
+
p95閾値超過
```

であれば、

```text
manifest = COMPLETED
performance verdict = FAIL
```

となります。

---

## 7. 出力フォーマット

分析結果は、

```text
JSON
Markdown
```

の2形式で生成します。

JSONは機械処理用、

Markdownはレビュー用です。

現在のレポート形式は、

```text
report_schema_version = 1.0
```

として固定しています。

主要フィールドは、

```text
report_schema_version
source
baseline_source
verdict
summary
baseline_summary
policy
evaluation
findings
comparability
limitations
```

です。

`verdict` はAI判断ではなく、

**Pythonの決定論的ロジックによる判定結果**

です。

---

## 8. Codex Skillとして使う

`performance-test-analysis` をCodex Skillとして利用します。

依頼例：

```text
performance-test-analysisを使って、
Locust結果をbaselineと比較してください。

数値的事実と原因仮説を分け、
追加確認項目を示してください。
```

Skill側にも、

- 原因を断定しない
- 数値を勝手に再計算しない
- Python判定を上書きしない
- 事実と仮説を分ける

という制約を持たせます。

---

## 9. テスト

```bash
pytest -q
```

現在、

```text
18 passed
```

を確認しています。

特に以下の3パターンを明示的にテストしています。

### 正常系

```text
絶対閾値：PASS
baseline比較：PASS
↓
PASS
```

### 性能劣化

```text
絶対閾値：PASS
baseline比p95：FAIL
↓
FAIL
```

絶対値では問題がなくても、

**以前より大幅に性能が悪化している**

ケースを検出します。

### エラー増加

```text
p95：正常
error rate：閾値超過
↓
FAIL
```

レスポンスタイムだけを見ることで、エラー増加を見逃さないことを確認します。

---

## PoCの評価観点

- 閾値違反を正しく検出できるか
- baselineからの性能劣化を検出できるか
- 正常系をPASSにできるか
- 性能劣化をFAILにできるか
- エラー増加をFAILにできるか
- 同じ入力に対して同じ判定結果になるか
- 比較不能な値を無理に数値化しないか
- 数値的事実とAIの原因仮説を分離できるか
- AIが原因を断定しないか
- AIがPASS / FAILを上書きしないか
- 最終判断を人間に残しているか
- warm-up区間をbaseline / current双方から同条件で除外できるか
- 最終累積エラー率と最大エラー率を区別できるか
- RPS低下をbaselineと比較できるか

---

## 次に実案件で確認すること

- SLA / SLO
- 通常時のユーザー数
- ピーク時ユーザー数
- TPS / RPS
- 将来の業務量増加率
- ユーザー行動モデル
- APIごとの利用比率
- 実データ量
- キャッシュ条件
- ウォームアップ条件
- Locust採用可否
- 既存の性能試験ツール
- CI/CDとの連携方式
- CloudWatch / Azure Monitor / Prometheus等の監視基盤
- CPU / Memory / Disk I/O
- DB接続数
- SQL実行時間
- ロック状況
- ネットワーク
- 外部API依存
- AIへ渡せる情報
- マスキング要件
- AI分析の再現性
- AIの見逃し / 誤検知
- 人間のレビュー負荷
- 分析時間削減効果

---

## 今後の拡張候補

このPoCでは、まず性能試験結果の判定とAI分析の責任分界に焦点を当てています。

今後の拡張候補としては、

```text
Locust
↓
アプリケーションログ
↓
DBメトリクス
↓
インフラメトリクス
↓
時刻同期
↓
相関分析
↓
AI仮説生成
↓
Human Review
```

のように、観測対象を広げることが考えられます。

ただし、

**AIが原因を自動決定するシステム**

を目標とはしていません。

最終的な目的は、

**人間が性能問題を調査するために必要な情報を、より早く整理できる仕組み**

を作ることです。
