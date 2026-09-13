# AI-Native Performance Engineering PoC

## これは何か
性能試験の結果分析を、AIに「数値的事実」と「原因仮説」を分離させて出力させる仕組みのPoCです。
現場でよくある「AIに聞いたら原因を断定してきて、それが外れていた」という問題に対し、
数値判定はPythonの決定的ロジックで行い、AI（Codex Skill）は仮説提示のみを担当する設計にしています。

## 背景
未経験の「AI×性能試験」案件を打診されたことがきっかけで、レビュー前に
「AIにどこまで任せて良いか」を自分で検証するために作りました。
（経緯はnoteにも書いています → [リンク]）

## 分かったこと / 工夫した点
- 閾値判定・ベースライン差分検出は完全にPythonの決定的ロジックに寄せ、AIには渡さない
- AI（Skill）には「数値の解釈」だけを任せ、証拠のない原因断定を禁止するようプロンプト設計
- Locust実行結果からp95/p99/エラー率を自動評価し、劣化を機械的に検出できることを確認
- 監視データ（CPU/メモリ）との時刻突合は未実装 → 実案件での次の課題として明記


## このPoCで仮設定した標準

| 項目 | 仮設定 | 理由 |
|---|---|---|
| 負荷試験ツール | Locust 2.40.4 / headless | Pythonでシナリオを実装でき、CIから実行しやすい |
| 一次データ | Locust `*_stats_history.csv` | 時系列の応答時間・件数・失敗数を機械処理できる |
| 実行証跡 | `manifest.json` | ツール、対象環境、負荷条件、実行コマンドを残す |
| 機械判定結果 | JSON | CI連携や再分析に利用する |
| 人向けレポート | Markdown | 根拠、リスク、追加確認をレビューしやすい |

これらは採用決定ではなく、関係者と議論するための暫定案です。実案件では既存基盤、監視方式、セキュリティ制約を確認して確定します。

## 全体像

1. FastAPIの検証用APIを起動する
2. `config/test_plan.json`から負荷条件を読み、Locustを実行する
3. CSVのp95・p99・エラー率をPythonで評価する
4. manifestで比較条件が一致した場合だけベースラインとの差分を判定する
5. `performance-test-analysis` Skillで、根拠と仮説を分離して説明する

## 0. セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShellでは有効化コマンドを次に置き換えます。

```powershell
.venv\Scripts\Activate.ps1
```

## 1. FastAPIを起動

```bash
uvicorn app.main:app --reload --port 8000
```

別のターミナルで確認します。

```bash
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/items?delay_ms=20&fail_rate=0&limit=3"
```

`delay_ms`と`fail_rate`は、劣化状態を意図的に作るためのPoC専用パラメータです。

## 2. シナリオと判定基準を確認

負荷条件は`config/test_plan.json`、判定方針は`config/thresholds.json`にあります。

- `smoke`: 疎通確認（2ユーザー、15秒）
- `baseline`: 比較元（50ユーザー、60秒）
- `regression`: 劣化検証（baselineと同じ負荷条件）
- `stress`: 限界傾向の観察（200ユーザー、180秒）

まずdry-runで、実行せずにコマンドとmanifestを確認できます。

```bash
python scripts/run_scenario.py baseline --run-id baseline-v1 --dry-run
```

## 3. Locustで負荷試験

APIを起動した状態で、設定済みシナリオを実行します。

```bash
python scripts/run_scenario.py baseline --run-id baseline-v1
python scripts/run_scenario.py regression --run-id regression-v1
```

各実行の成果物は次の場所に生成されます。

- `results/runs/<run-id>/locust_stats_history.csv`: 一次分析データ
- `results/runs/<run-id>/manifest.json`: 実行条件と実行証跡
- その他の`locust_*.csv`: 集計値や失敗情報の補助データ

## 4. サンプルデータを分析

依存ライブラリを入れる前でも、分析スクリプト自体はPython標準ライブラリだけで実行できます。

```bash
python performance-test-analysis/scripts/analyze_results.py \
  data/degraded.csv \
  --baseline data/baseline.csv \
  --thresholds config/thresholds.json \
  --output-json results/sample-analysis.json \
  --output-md results/sample-analysis.md
```

期待結果は`FAIL`です。p95、p99、エラー率はサービス判定の`FAIL`、CPU超過は原因調査を促す`WARN`として出力され、ベースラインからの回帰も検出されます。

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

ツール、対象環境、ユーザー数、増加率、継続時間、タスク比率が一致しなければ`NOT_COMPARABLE`となり、回帰判定を抑止します。LocustだけではCPU・メモリが入らないため、レポートには未取得と表示されます。本番想定ではCloudWatch、Azure Monitor、Prometheusなどの監視データとの時刻突合が次の拡張です。

## 6. 判定の責任分界

- Pythonスクリプト: CSV集計、閾値判定、比較条件チェックを確定的に実施
- AI/Codex Skill: 傾向の要約、リスク候補、追加調査案を提示
- 人間: 要件と閾値の承認、原因確認、リリース可否の最終判断

応答性能とエラー率は利用者影響に直結するため`FAIL`、CPU・メモリは単独で不合格理由にせず`WARN`とします。値はPoC用の暫定値であり、SLA/SLOや業務ピーク、構成上限を根拠に案件ごとに合意します。

## 7. Codex Skillとして使う

`performance-test-analysis`フォルダをCodexのSkills配置先へ置き、分析対象CSVと閾値を指定して呼び出します。

依頼例：

> performance-test-analysisを使って、results/degraded_stats_history.csvをbaselineと比較してください。数値的事実と原因仮説を分け、追加確認項目を示してください。

Skillは、付属スクリプトで算出した数値を根拠にし、CPU・DB・ネットワークなどを証拠なしに原因と断定しないよう定義しています。

## 8. テスト

```bash
pytest -q
```

## PoCの評価観点

- 閾値違反を正しく検出できるか
- ベースラインからの性能劣化を検出できるか
- 数値的事実とAIの原因仮説が分離されているか
- 実行者が変わっても同じ数値判定になるか
- AIによる説明で分析時間を短縮できるか
- 最終判断を人間が確認する設計になっているか

## 次に実案件で確認すること

- SLA/SLO、通常時・ピーク時の業務量、将来増加率
- Locust採用可否と、既存標準ツール・CI基盤との整合
- 対象API、ユーザー行動比率、テストデータ量、ウォームアップ時間
- 環境占有条件、他処理の有無、アプリ・DB・外部サービスのバージョン
- 監視データの取得元
- AIへ渡せる情報の範囲とマスキング方式
- PoCの評価指標（見逃し、誤検知、再現性、分析時間、レビュー負荷）と終了条件
