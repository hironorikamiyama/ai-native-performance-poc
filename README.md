# AI-Native Performance Engineering PoC

## 1. このPoCについて

性能試験結果の数値判定、原因仮説、最終判断を分離するためのPoCです。検証用FastAPIにLocustで負荷をかけ、CSVをPythonで分析してJSON／Markdownレポートを生成します。

```text
Locust → FastAPIへの負荷試験 → CSV / manifest
                                      ↓
                                  Python分析
                                      ↓
                              JSON / Markdown
                                      ↓
                 人間が直接確認、または任意のAI / Codex支援を利用
                                      ↓
                              人間による最終判断
```

- **Python**：測定値の検証、集計、閾値・baseline比較、決定論的なPASS／FAIL判定。
- **AI / Codex**：レポートを基に、傾向、原因仮説、追加確認事項を整理。合否を決定したり、測定値だけで原因を断定したりしません。
- **人間**：性能要件の設定、仮説の検証、性能評価の承認、リリース可否判断。

外部AI APIの自動連携はありません。Python分析後のAIレビューは、利用者が別途依頼する作業です。

## 2. 実装済み機能と主要ファイル

実装済みの機能は、負荷試験の実行と証跡保存、warm-up処理、全体・endpointの閾値判定、baseline回帰比較、データ品質検証、JSON／Markdown出力です。

| ファイル | 役割 |
|---|---|
| `app/main.py` | 検証用API。`/health`と、遅延・エラーを再現できる`/items` |
| `loadtest/locustfile.py` | 負荷シナリオとLocust統計リセット |
| `scripts/run_scenario.py` | Locustの起動、CSV出力先の設定、manifestの保存 |
| `config/test_plan.json` | 対象環境、負荷条件、シナリオ |
| `config/thresholds.json` | 暫定閾値とwarm-up時間 |
| `performance-test-analysis/scripts/analyze_results.py` | 決定論的な分析とレポート生成 |
| `data/` | 分析用サンプルCSV |
| `tests/` | 正常系・異常系・境界値・回帰テスト |

Codex Skillによる支援は、これらのPython実装機能とは別の利用手順です。

## 3. 使い方

以下のコマンドはリポジトリのルートから実行します。

### セットアップとサンプル分析

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python performance-test-analysis/scripts/analyze_results.py \
  data/degraded.csv \
  --baseline data/baseline.csv \
  --thresholds config/thresholds.json \
  --output-json results/sample-analysis.json \
  --output-md results/sample-analysis.md
```

Windows PowerShellでは、環境の有効化に`.venv\Scripts\Activate.ps1`を使用します。サンプル分析はmanifestなしの計算例であり、比較条件の確認は行いません。

### API起動と負荷試験

```bash
uvicorn app.main:app --reload --port 8000
```

別ターミナルで仮想環境を有効化し、負荷試験を実行します。

```bash
python scripts/run_scenario.py baseline --run-id baseline-v1 --dry-run
python scripts/run_scenario.py baseline --run-id baseline-v1
python scripts/run_scenario.py regression --run-id regression-v1
```

`--dry-run`は実行予定のmanifestを表示します。実行時は`results/runs/<run-id>/`に`locust_stats_history.csv`、`locust_stats.csv`、`manifest.json`を保存します。既存のrun-idは再利用できないため、再実行時は新しい名前を使用してください。

| シナリオ | 用途 |
|---|---|
| `smoke` | 疎通確認 |
| `baseline` | 正常時の比較基準取得 |
| `regression` | baselineと同じ負荷条件で遅延・エラー増加を再現 |
| `stress` | 高負荷時の傾向確認 |

runnerは負荷試験を実行し、分析は次のコマンドで別途行います。

### manifest・endpoint付き分析

```bash
python performance-test-analysis/scripts/analyze_results.py \
  results/runs/regression-v1/locust_stats_history.csv \
  --thresholds config/thresholds.json \
  --baseline results/runs/baseline-v1/locust_stats_history.csv \
  --manifest results/runs/regression-v1/manifest.json \
  --baseline-manifest results/runs/baseline-v1/manifest.json \
  --endpoint results/runs/regression-v1/locust_stats.csv \
  --baseline-endpoint results/runs/baseline-v1/locust_stats.csv \
  --output-json results/locust-analysis.json \
  --output-md results/locust-analysis.md
```

baseline比較やendpoint分析は任意です。`--baseline-endpoint`には`--endpoint`も必要です。

## 4. 評価ルール

### 指標と暫定閾値

現在の設定は以下です。業界標準や本番向けの保証値ではなく、PoC用の暫定基準です。

| 指標 | 評価方法 | 上限・扱い |
|---|---|---|
| 全体p95 / p99 | 評価対象CSV各行のp95 / p99の最大値 | 250ms / 500ms、超過はFAIL |
| 全体エラー率 | 最終累積failures ÷ requests × 100 | 1.0%、超過はFAIL |
| CPU / Memory | 評価対象行の最大値。未提供なら省略 | 80% / 85%、超過はWARN |
| 全体p95 / p99回帰 | currentとbaselineの各最大値の悪化率 | 各20%、超過はFAIL |
| 全体スループット回帰 | 評価対象行のmedian RPSの低下率 | 20%、超過はFAIL |
| endpoint p95 / p99 / エラー率 | `locust_stats.csv`のendpoint別測定値 | 全体と同じ閾値。設定でendpoint別に上書き可能 |
| endpoint p95 / p99回帰 | 同じendpointのbaselineとの悪化率 | 各20%、超過はFAIL |
| endpoint RPS変化 | 同じendpointのbaselineとの比較 | 通常INFO。不正値はINVALID_DATA |

p95／p99はCSVに記録された値を使います。生の応答時間から全期間のpercentileを再計算したり、percentile列を平均したりはしません。観測期間中の最大エラー率は診断用であり、合否には最終累積エラー率を使用します。

閾値と一致する値は超過ではありません。判定には丸め前のraw値を使い、表示・出力のみ丸めます。例えばエラー率1.0004%は、表示が1.000%でも閾値1.0%に対してFAILです。

### baselineの比較可能性

`--manifest`と`--baseline-manifest`を**両方指定した場合に比較条件確認を行います**。片方のみの指定は例外になります。

確認対象は`tool`、`target`、`workload_signature`、`evaluation.warmup_seconds`、`evaluation.stats_reset_mode`です。不一致なら`comparability.status = NOT_COMPARABLE`とし、全体・endpointの回帰判定を抑止します。currentの絶対閾値判定は行います。

両方とも未指定なら、比較条件を検証せずbaseline比較を実行します。比較の妥当性は利用者が確認してください。相対比較に使う有効なbaseline値が0の場合、対象findingはNOT_EVALUATEDです。endpoint RPSの比較不能は従来どおりINFOになります。

### warm-up除外と統計リセット

- **行の除外**：分析時に`evaluation.warmup_seconds`（現在10秒）を使い、読み込み後の先頭行のtimestampを起点にcurrent・baselineの初期区間を除外します。
- **統計リセット**：負荷試験時にLocustのLocalRunner向けにwarm-up終了後の`runner.stats.reset_all()`を予約します。

行の除外だけでは、残った行の累積件数・percentileからwarm-up分を完全には取り除けません。分析側は累積requestsの減少をリセットの証拠として検出し、除外行数と検出結果をレポートに記録します。manifestの宣言だけでリセット済みとは判断しません。未検出の場合はwarm-upの測定が残っている可能性があります。

## 5. 判定結果とデータ品質

### 総合verdict

全体・endpointのfindingsを合わせて、以下の優先順位で決定します。

**FAIL > INVALID_DATA > PASS_WITH_WARNINGS > PASS**

| verdict | 条件 |
|---|---|
| `FAIL` | 有効な測定値による閾値超過・回帰のFAILがある |
| `INVALID_DATA` | FAILがなく、不正・不足データのfindingがある |
| `PASS_WITH_WARNINGS` | FAILもINVALID_DATAもなく、WARNがある |
| `PASS` | 上記のfindingがない |

FAILとINVALID_DATAが併存しても、確認済みのFAILを維持し、不正データの理由はfindingsに残します。endpointのみ不正でも総合PASSにはしません。総合PASSでも、実施できなかった個別比較がないかfindingsを確認してください。

### 個別findingのstatusと比較可能性

| finding status | 意味 |
|---|---|
| `PASS` | 有効な測定値があり、対象の評価基準内 |
| `FAIL` | 有効な測定値があり、対象の評価基準を超過 |
| `WARN` | CPU・Memoryの診断用閾値を超過 |
| `INVALID_DATA` | 評価に必要な測定値が不正または不足。reasonを記録 |
| `NOT_EVALUATED` | データは有効だが相対比較できない。例：baselineが0 |
| `INFO` | endpoint RPSの参考情報 |

NOT_EVALUATEDとINFOは総合verdictの優先順位には加えません。`COMPARABLE`／`NOT_COMPARABLE`は`comparability.status`であり、総合verdictや個別findingのstatusとは別です。

### INVALID_DATAと入力エラー

読み込めた数値に以下の問題がある場合、全体・endpoint、current・baselineで同じデータ品質ルールを適用します。

- `requests = 0`または負数、`failures < 0`、`failures > requests`。
- p95・p99・RPSが負数。
- 測定値にNaN・+Infinity・-Infinityがある。
- 有限な入力から計算した中央値・変化率が非有限になる。

件数が不正ならエラー率は算出不可とし、0%としてPASSにしません。p95／p99も測定の裏付けがないためPASSにしません。各INVALID_DATA findingにはmetricとreasonを残します。

warm-upとして除外済みの行は評価対象外です。評価対象の不正行は黙って捨ててPASSにせず、有効な測定から確認できたpeakのFAILは維持します。不正データがあるmetricの回帰判定は行わず、中央値は対象metricの全行が有効な場合に使用します。非有限timestampで評価窓を確定できない場合は行を保持し、INVALID_DATAを記録します。

一方、必須列不足、数値に変換できない入力、空CSV、warm-up除外後に行が残らない場合などは**例外で分析を停止**します。これらを一律にINVALID_DATAレポートへ変換する実装ではありません。history CSVの初期N/A行は既存処理で除外し、読み込める行が残らない場合は例外になります。任意のCPU・Memoryが未提供の場合は評価を省略します。

## 6. レポート出力

分析レポートは`report_schema_version = 1.2`です。JSONは機械処理用、Markdownは人間によるレビュー用です。

主要フィールドは`verdict`、`summary`、`baseline_summary`、`policy`、`evaluation`、`findings`、`comparability`、`limitations`、`endpoints`です。全体のfindingsは`findings`、endpoint別のfindingsは`endpoints`内に格納します。summaryには`data_quality`も含まれます。

**strict JSONの対象は分析レポートです。** 非有限の数値は`null`へ変換し、元の値の種類と理由をfindingのreasonに残します。最終シリアライズは`allow_nan=False`で、想定外の非有限値の混入も検出します。有限だが不正な入力値は証拠として残します。MarkdownにはINVALID_DATA、理由、および「無効／算出不可」を表示します。

runnerのmanifestは別の出力で、`schema_version = 1.1`です。負荷試験の`COMPLETED`は性能合格を意味しません。また、分析レポートのFAIL／INVALID_DATAをCLIの非ゼロ終了コードへ変換する機能はないため、機械連携ではJSONのverdictを確認してください。

## 7. Codex Skillによる分析支援

現在のSkillは[.codex/skills/performance-poc/SKILL.md](.codex/skills/performance-poc/SKILL.md)です。Skill名は`performance-test-analysis`です。

利用者がCodexに分析を依頼するときの例：

```text
performance-test-analysis Skillを使い、生成したJSON / Markdownをレビューしてください。
数値的事実と原因仮説を分け、baselineの比較条件、warm-up、統計リセットの
検出結果を確認し、追加確認事項を整理してください。
```

Skillは、計算済みの証拠を使い、原因を断定せず、仮説と追加測定を整理するための指示です。Pythonの判定結果をAIが上書きする機能や、分析ツールからSkill・外部AI APIを自動実行する機能はありません。

## 8. テスト

```bash
python -m pytest -q
```

確認済みの結果は **181 passed** です。正常系・性能劣化・エラー増加に加え、閾値境界、丸め前の判定、baseline比較抑止、warm-up、endpoint分析、件数不整合、非有限値・負数、verdict優先順位、strict JSONとCLI出力を検証しています。

## 9. 制約と今後の拡張候補

このPoCのPASSは、試験した負荷・期間・環境を超える本番性能を保証しません。測定値だけでDB・CPU・ネットワークなどの原因を特定することもできません。RPS低下は負荷生成側や他endpointの処理時間にも影響されます。

CPU・Memoryは入力CSVにあれば分析しますが、自動収集は実装していません。manifest比較は記録された設定の一致確認であり、実際の環境・データ・コードが同一であることを保証するものではありません。実案件ではSLA／SLO、負荷条件、データ量、観測基盤に合わせて基準を見直す必要があります。

今後の拡張候補（未実装）は、アプリケーションログ・DB・インフラメトリクスの収集連携、時刻同期と相関分析、CIでの性能ゲート、外部AI APIとの連携です。拡張後も、原因の確認とリリース判断は人間が行う方針です。
