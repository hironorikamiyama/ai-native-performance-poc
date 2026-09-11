# AI-Native Performance Engineering PoC

FastAPIに負荷をかけ、性能試験CSVを確定的に評価し、Codex Skillで傾向・リスク・追加調査を整理する簡易PoCです。

## 全体像

1. FastAPIの検証用APIを起動する
2. Locustで負荷試験を実行する
3. CSVのp95・p99・エラー率をPythonで評価する
4. ベースラインとの差分を検出する
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

## 2. Locustで負荷試験

正常系の例です。

```bash
POC_DELAY_MS=20 POC_FAIL_RATE=0 locust \
  -f loadtest/locustfile.py \
  --headless -u 20 -r 5 -t 60s \
  --host http://127.0.0.1:8000 \
  --csv results/baseline
```

劣化系の例です。

```bash
POC_DELAY_MS=350 POC_FAIL_RATE=0.03 locust \
  -f loadtest/locustfile.py \
  --headless -u 50 -r 10 -t 60s \
  --host http://127.0.0.1:8000 \
  --csv results/degraded
```

Locustが生成した時系列ファイル（`*_stats_history.csv`）を分析対象にします。

## 3. サンプルデータを分析

依存ライブラリを入れる前でも、分析スクリプト自体はPython標準ライブラリだけで実行できます。

```bash
python performance-test-analysis/scripts/analyze_results.py \
  data/degraded.csv \
  --baseline data/baseline.csv \
  --thresholds config/thresholds.json \
  --output-json results/sample-analysis.json \
  --output-md results/sample-analysis.md
```

期待結果は`FAIL`です。p95、p99、エラー率、CPUが閾値を超え、ベースラインからの回帰も検出されます。

## 4. 実際のLocust結果を分析

```bash
python performance-test-analysis/scripts/analyze_results.py \
  results/degraded_stats_history.csv \
  --baseline results/baseline_stats_history.csv \
  --thresholds config/thresholds.json \
  --output-json results/locust-analysis.json \
  --output-md results/locust-analysis.md
```

LocustだけではCPU・メモリが入らないため、レポートには未取得と表示されます。本番想定ではCloudWatch、Azure Monitor、Prometheusなどの監視データとの時刻突合が次の拡張です。

## 5. Codex Skillとして使う

`performance-test-analysis`フォルダをCodexのSkills配置先へ置き、分析対象CSVと閾値を指定して呼び出します。

依頼例：

> performance-test-analysisを使って、results/degraded_stats_history.csvをbaselineと比較してください。数値的事実と原因仮説を分け、追加確認項目を示してください。

Skillは、付属スクリプトで算出した数値を根拠にし、CPU・DB・ネットワークなどを証拠なしに原因と断定しないよう定義しています。

## 6. テスト

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

- 性能要件と合否基準
- 採用する負荷試験ツールと出力形式
- テスト環境、データ量、負荷モデル
- 監視データの取得元
- AIへ渡せる情報の範囲
- PoCの評価指標と終了条件
