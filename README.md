# AI-Native Performance Engineering PoC

性能試験結果を、**Pythonによる決定論的な判定**、**AI / Codexによる分析・レビュー支援**、**人間による最終判断**に分離して扱うためのPoCです。

本PoCでは、AIに性能試験の合否や原因をそのまま決めさせるのではなく、再現可能な数値判定はPythonで行い、AIはレビューや仮説整理を支援する役割に限定します。

## Quick Overview

### 性能試験・分析フロー

```text
FastAPI
  ↓
Locust
  ↓
CSV / manifest
  ↓
Python deterministic analysis
  ↓
JSON / Markdown
  ↓
AI-assisted review / hypothesis support
  ↓
Human review
```

### 開発・レビュー支援フロー

```text
PoC固有の設計方針
  ↓
Codex Skills
  ↓
Codexによるコードレビュー
  ↓
問題点・境界値・異常系の抽出
  ↓
Pythonコード修正
  ↓
pytestによる回帰確認
```

現時点では、性能分析ツール内部から外部AI APIを自動実行する構成にはしていません。  
AI / Codexは、性能分析結果の解釈支援や開発時のコードレビュー支援として利用します。

---

## 目的

このPoCの目的は、性能試験結果の分析において、

- 数値的事実
- 判定ルール
- データ品質
- 原因仮説
- 人間による最終判断

を分離することです。

特に、以下を検証しています。

- p95 / p99 / エラー率 / RPSを決定論的に評価できるか
- baselineとの性能回帰を再現可能なロジックで判定できるか
- 比較条件が異なるデータを誤って比較しないか
- API / endpoint単位まで性能劣化箇所を絞り込めるか
- 0件、NaN、Infinityなどの不正・不足データをPASSにしないか
- AIが数値判定や原因断定を上書きしない構成にできるか
- AIレビューで見つけた問題をpytestで再現・検証できるか

---

## 現在実装している機能

- FastAPIによる検証用API
- Locustによる負荷試験
- `config/test_plan.json` による負荷条件管理
- `config/thresholds.json` による判定基準管理
- warm-up区間の除外
- warm-up終了時のLocust統計リセット
- p95 / p99 / エラー率の絶対閾値判定
- median RPSによるシステム全体のスループット回帰判定
- baselineとのp95 / p99性能回帰比較
- manifestによる比較可能性確認
- baselineが0の場合の `NOT_EVALUATED`
- API / endpoint単位の性能分析
- API別RPSの `INFO` 扱い
- 不正・不足データの `INVALID_DATA` 判定
- JSON / Markdownレポート生成
- strict JSON出力
- Codex Skillsを用いたコードレビュー支援
- pytestによる正常系・異常系・境界値・回帰テスト

---

## 検証シナリオ

| シナリオ | 内容 | 期待結果 |
|---|---|---|
| 正常系 | 閾値内かつbaselineから大きな劣化なし | PASS |
| 性能劣化 | 絶対閾値内でもbaseline比で性能劣化 | FAIL |
| エラー増加 | レスポンスタイム正常でもエラー率超過 | FAIL |
| 不正データ | 評価に必要な測定値が不正・不足 | INVALID_DATA |
| 比較不能 | データは有効だが相対比較できない | NOT_EVALUATED |

---

## 設計方針

### Python

Pythonが担当します。

- p95 / p99の集計
- エラー率の計算
- RPSの集計
- データ品質チェック
- 閾値比較
- baseline比較
- 回帰率計算
- PASS / FAIL / INVALID_DATA判定
- JSON / Markdown出力

### AI / Codex

AI / Codexが担当するのは支援です。

- コードレビュー
- 境界値・異常系の指摘
- 性能劣化傾向の整理
- リスク候補の提示
- 原因仮説の整理
- 追加確認項目の提案
- 必要なログ・メトリクスの提示

AIは、測定値だけから、

```text
DBが原因です
```

のような原因断定を行いません。

例えば、

```text
DB接続待ちの可能性があります。

確認には、
接続プール利用率、
SQL実行時間、
ロック状況、
DB CPUなどの追加情報が必要です。
```

のように、仮説と確認事項を分けて扱います。

### Human

人間が担当します。

- 性能要件の決定
- 閾値の決定
- AI仮説の検証
- 原因の最終判断
- 改善策の決定
- 性能評価の承認
- リリース可否判断

> AIは原因を決定するためではなく、人間の調査・判断を支援するために利用します。

---

## 判定ステータス

| status / verdict | 意味 |
|---|---|
| `PASS` | 有効な測定値があり、評価基準内 |
| `FAIL` | 有効な測定値があり、評価基準を超過 |
| `PASS_WITH_WARNINGS` | サービス判定はFAILではないが、リソース警告あり |
| `INVALID_DATA` | 評価に必要な測定値が不正または不足 |
| `NOT_EVALUATED` | データ自体は有効だが、比較・評価を実施できない |
| `INFO` | 判定には使用しない参考情報 |
| `NOT_COMPARABLE` | baselineとcurrentの比較条件が一致しない |

総合verdictの優先順位は以下です。

```text
FAIL
  ↓
INVALID_DATA
  ↓
PASS_WITH_WARNINGS
  ↓
PASS
```

有効な測定によるFAILとINVALID_DATAが同時に存在する場合は、確定している閾値違反を隠さないため `FAIL` を維持し、不正データの内容はfindingsに残します。

---

## 不正・不足データの扱い

測定値の妥当性は、集計・除算・閾値比較・baseline比較の前に確認します。

以下は `INVALID_DATA` とします。

- `requests == 0`
- `requests < 0`
- `failures < 0`
- `failures > requests`
- p95が負数
- p99が負数
- RPSが負数
- NaN
- `+Infinity`
- `-Infinity`
- 有限値から算出した中央値や変化率が非有限になる場合

件数が不正な場合、エラー率を便宜的に0%とは扱いません。  
また、requestsが0の場合はp95 / p99にも有効な測定根拠がないため、PASSにはしません。

任意項目であるCPU / Memoryが未提供の場合は、従来どおり評価を省略します。

### `NOT_EVALUATED` との違い

`INVALID_DATA` は、測定値そのものに問題がある場合です。

一方、`NOT_EVALUATED` はデータ自体は有効でも、評価式を適用できない場合です。

例：

```text
baseline RPS = 0
→ 相対的なRPS低下率を算出できない
→ NOT_EVALUATED
```

### warm-up区間と不正データ

warm-upとして正式に除外された行は、評価対象外です。

一方、評価対象区間に不正な行がある場合は、その行を黙って捨てて残りだけでPASSにはしません。

有効な測定から明確なFAILが確認できる場合、そのFAILは維持します。

---

## このPoCで仮設定した基準

| 項目 | 仮設定 | 理由 |
|---|---:|---|
| 負荷試験ツール | Locust 2.40.4 / headless | Pythonでシナリオを実装できる |
| warm-up | 10秒 | 試験開始直後の過渡状態を除外 |
| p95 | 250ms以下 | PoC用の暫定基準 |
| p99 | 500ms以下 | PoC用の暫定基準 |
| error rate | 1.0%以下 | PoC用の暫定基準 |
| CPU | 80%以下 | 超過時はWARN |
| Memory | 85%以下 | 超過時はWARN |
| baseline比 p95悪化 | 20%以下 | PoC用の暫定基準 |
| baseline比 p99悪化 | 20%以下 | PoC用の暫定基準 |
| median RPS低下 | 20%以下 | システム全体の回帰判定 |
| Report Schema | `1.2` | 出力形式を固定 |

これらは業界標準値ではありません。

**判定ロジックを再現可能にするためのPoC用暫定値**です。

実案件では、SLA / SLO、利用モデル、ピーク負荷、データ量、既存監視基盤などを確認した上で決定します。

---

## セットアップ

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

## FastAPIを起動

```bash
uvicorn app.main:app --reload --port 8000
```

別ターミナルから確認します。

```bash
curl http://127.0.0.1:8000/health

curl \
  "http://127.0.0.1:8000/items?delay_ms=20&fail_rate=0&limit=3"
```

`delay_ms` と `fail_rate` は、意図的に性能劣化やエラー増加を再現するためのPoC専用パラメータです。

---

## 負荷試験シナリオ

負荷条件は、

```text
config/test_plan.json
```

判定基準は、

```text
config/thresholds.json
```

に分離しています。

現在のシナリオは以下です。

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

## Locustで負荷試験

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

主なファイルは、

```text
locust_stats_history.csv
locust_stats.csv
manifest.json
```

です。

`manifest.json` には、例えば以下を記録します。

- 使用ツール
- 対象環境
- シナリオ
- ユーザー数
- spawn rate
- duration
- warm-up設定
- 統計リセット方式
- 実行条件

---

## 性能試験結果を分析

### サンプルデータ

```bash
python performance-test-analysis/scripts/analyze_results.py \
  data/degraded.csv \
  --baseline data/baseline.csv \
  --thresholds config/thresholds.json \
  --output-json results/sample-analysis.json \
  --output-md results/sample-analysis.md
```

### Locust実行結果 + endpoint分析

```bash
python performance-test-analysis/scripts/analyze_results.py \
  results/runs/regression-reset-v2/locust_stats_history.csv \
  --thresholds config/thresholds.json \
  --baseline results/runs/baseline-reset-v1/locust_stats_history.csv \
  --manifest results/runs/regression-reset-v2/manifest.json \
  --baseline-manifest results/runs/baseline-reset-v1/manifest.json \
  --endpoint results/runs/regression-reset-v2/locust_stats.csv \
  --baseline-endpoint results/runs/baseline-reset-v1/locust_stats.csv \
  --output-json results/locust-analysis-endpoint-v1.json \
  --output-md results/locust-analysis-endpoint-v1.md
```

比較条件が一致している場合だけbaseline回帰判定を行います。

条件が異なる場合は、

```text
NOT_COMPARABLE
```

として回帰判定を抑止します。

---

## baseline比較の前提

baselineとcurrentを比較する際は、manifestを用いて比較可能性を確認します。

主に以下の条件を確認します。

- tool
- target
- workload signature
- warm-up duration
- statistics reset mode

比較条件が一致しない場合、数値上の差があっても同一条件での性能回帰とはみなしません。

---

## warm-up区間の扱い

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

現在は10秒です。

さらにLocust側でもwarm-up終了後に、

```python
runner.stats.reset_all()
```

を実行し、その後の定常区間を新しい測定期間として扱います。

レポートには、例えば以下を記録します。

```text
## Evaluation window

- Warm-up seconds: 10
- Current rows excluded: ...
- Baseline rows excluded: ...
- Current stats reset detected: True
- Baseline stats reset detected: True
```

---

## エラー率の扱い

Locustのリクエスト数・失敗数は累積値です。

試験開始直後はリクエスト数が少ないため、少数のエラーでも一時的に高いエラー率になる可能性があります。

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

### 判定値と表示値を分離する

PASS / FAIL判定には、丸め前のraw値を使用します。

例えば閾値が `1.0%` の場合、

```text
0.9996% → PASS
1.0000% → PASS
1.0004% → FAIL
```

です。

JSON / Markdownの表示では小数3桁へ丸める場合がありますが、表示用の丸め値を判定には使用しません。

```text
判定
→ raw値

表示
→ 丸めた値
```

---

## スループット回帰の扱い

システム全体では、

```text
baselineのmedian RPS
```

と、

```text
currentのmedian RPS
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

現在は20%を許容上限としています。

ただしRPSは、

- 負荷生成側
- ネットワーク
- 実行環境
- wait time
- 他endpointの処理時間

などにも影響されます。

そのため、RPS低下だけから原因を断定しません。

---

## API / endpoint単位の性能分析

`locust_stats.csv` を利用して、API / endpoint単位の性能分析を行います。

現在は以下を評価します。

- p95
- p99
- エラー率
- baseline比のp95性能回帰
- baseline比のp99性能回帰
- endpoint RPSの変化

### endpoint RPSはINFO

endpoint単位のRPS低下は、単独ではFAIL判定に使用しません。

あるendpointの処理時間が増加すると、Locust全体のユーザー処理サイクルが遅くなり、正常な別endpointの実行回数まで低下する場合があるためです。

```text
システム全体のmedian RPS
→ 性能回帰の判定対象

endpoint単位のRPS
→ INFOとして参考表示
```

例：

```text
GET /health

PASS: p95
PASS: p99
PASS: error rate
PASS: p95 baseline regression
PASS: p99 baseline regression
INFO: RPS decreased


GET /items

FAIL: p95 threshold
PASS: p99 threshold
FAIL: error rate
FAIL: p95 baseline regression
FAIL: p99 baseline regression
INFO: RPS decreased
```

これにより、

```text
システム全体でFAIL
  ↓
endpointごとの結果を確認
  ↓
どのAPIで遅延・エラー・回帰が発生したか絞り込む
```

という調査ができます。

---

## 実行成否と性能判定

負荷試験が技術的に完走したことと、性能要件を満たしたことは別です。

Locustには、

```text
--exit-code-on-error 0
```

を指定しています。

そのため、意図的なHTTP 503などが発生しても、負荷試験自体は最後まで実行できます。

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

## 出力フォーマット

分析結果は、

```text
JSON
Markdown
```

の2形式で生成します。

- JSON: 機械処理・再利用向け
- Markdown: 人間によるレビュー向け

現在のレポートスキーマは、

```text
report_schema_version = 1.2
```

です。

主なフィールドは以下です。

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
endpoints
```

schema 1.2では、データ品質判定に対応するため、

- `INVALID_DATA`
- 数値欄の `null`
- summary内のdata quality情報

を扱います。

非有限値はJSONへ `NaN` / `Infinity` として出力せず、数値欄を `null` にします。  
元の値がNaN / Infinity等だったことはfindingのreasonに残します。

最終シリアライズでは `allow_nan=False` を使用し、想定外の非有限値がJSONへ混入することも防ぎます。

---

## Codex Skillsによるレビュー支援

PoC固有の設計・レビュー方針は、

```text
.codex/skills/performance-poc/SKILL.md
```

に定義しています。

Skillには、例えば以下のルールを記載しています。

- Pythonが決定論的な性能判定を行う
- AIはPASS / FAILを上書きしない
- AIは原因を証拠なしに断定しない
- endpoint RPSはINFOとして扱う
- baseline比較では比較可能性を確認する
- 変更後はpytestで回帰確認する
- 数値的事実と仮説を分ける

### 実際に見つかった改善点

Codexによるレビューでは、以下のような問題を検出しました。

- 表示用に丸めたエラー率を閾値判定にも使用していた
- request countが0の場合に正常なエラー率0%として扱える余地があった
- NaN / Infinity等の非有限値がPASSになり得た
- endpointの不正RPSがbaseline比較処理へ影響するケースがあった

レビュー結果をそのまま採用するのではなく、

```text
指摘
  ↓
再現
  ↓
修正
  ↓
境界値・異常値テスト追加
  ↓
全pytest
```

の流れで検証しています。

---

## テスト

```bash
python -m pytest -q
```

現在の結果：

```text
181 passed
```

主なテスト観点は以下です。

- 正常時のPASS判定
- レスポンスタイム劣化
- エラー率増加
- baseline比較
- warm-up除外
- Locust統計リセット検出
- baselineが0の場合の `NOT_EVALUATED`
- manifest不一致時の比較抑止
- API別CSV読込
- API別閾値判定
- API別baseline比較
- API別RPSを `INFO` として扱うこと
- endpointのみ不正な場合の総合判定
- request countが0の場合
- requests / failuresの不整合
- NaN / `+inf` / `-inf`
- 負のp95 / p99 / RPS
- FAILとINVALID_DATAの優先順位
- 閾値直下・一致・直上
- warm-up除外行に不正値がある場合
- 非有限timestamp
- 計算結果が非有限になる場合
- strict JSON serialization
- CLIによるJSON / Markdown出力

---

## PoCの評価観点

- 閾値違反を正しく検出できるか
- baselineからの性能劣化を検出できるか
- 正常系をPASSにできるか
- 性能劣化をFAILにできるか
- エラー増加をFAILにできるか
- 不正データをPASSにしないか
- 比較不能な値を無理に数値化しないか
- 同じ入力に対して同じ判定結果になるか
- manifest不一致時に回帰判定を抑止できるか
- endpoint単位まで劣化箇所を絞り込めるか
- warm-up区間をbaseline / current双方で扱えるか
- 最終累積エラー率と最大エラー率を区別できるか
- 判定用raw値と表示用丸め値を分離できるか
- 数値的事実とAIの原因仮説を分離できるか
- AIがPASS / FAILを上書きしないか
- AIが原因を断定しないか
- 最終判断を人間に残しているか

---

## 実案件で確認すべきこと

このPoCの閾値や条件をそのまま実案件へ適用することは想定していません。

実案件では、例えば以下を確認する必要があります。

- SLA / SLO
- 通常時・ピーク時のユーザー数
- TPS / RPS
- 将来の業務量増加率
- ユーザー行動モデル
- APIごとの利用比率
- 実データ量
- キャッシュ条件
- warm-up条件
- 利用可能な性能試験ツール
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

現在は、性能試験結果の決定論的判定、データ品質確認、endpoint分析、AIとの責任分界に焦点を当てています。

今後は、

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
AIによる仮説整理
  ↓
Human Review
```

のように、観測対象を広げることが考えられます。

ただし、目標は、

**AIが原因を自動決定するシステム**

ではありません。

最終的な目的は、

**人間が性能問題を調査するために必要な情報を、より早く整理できる仕組み**

を作ることです。
