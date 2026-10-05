# Performance Troubleshooting Scenarios

## 1. この資料の目的

本資料は、性能試験や運用中の性能劣化に対して、

**観測事実 → 仮説 → 追加確認 → 現時点で断定できないこと**

の順で整理する練習用ドキュメントです。

性能問題では、単一のメトリクスだけを見て原因を断定しないことが重要です。

本資料の各ケースは学習用の架空例であり、実案件ではアプリケーション、OS、DB、ネットワーク、外部サービスなどの実測データを確認して原因を特定します。

---

## 2. Case 1: p95悪化 + RPS低下 + DB接続数上限付近

### 観測事実

- p95がbaseline比で大幅に悪化
- p99も悪化
- RPSが低下
- CPU使用率は正常範囲
- DB接続数が上限付近
- エラー率は大きく増えていない

### 仮説

DB connection poolの空き待ちが発生し、リクエスト処理が待たされている可能性がある。

### 追加確認

- connection pool利用率
- connection wait time
- DB connection上限
- SQL実行時間
- slow query
- lock状況
- DB CPU
- DB Disk I/O
- アプリケーション側のDB待機時間

### 現時点で断定できないこと

DB接続数が上限付近というだけでは、DBが性能劣化の原因とは断定できない。

SQL自体が遅い可能性、アプリケーションの接続解放不備、DB以外の待ち時間なども確認する必要がある。

---

## 3. Case 2: CPU 95% + RPS頭打ち

### 観測事実

- CPU使用率が95%前後
- RPSが一定値から伸びない
- p95 / p99が負荷増加に伴って悪化
- エラー率は低い
- Memory使用率は正常範囲

### 仮説

CPU飽和によって処理能力が制限されている可能性がある。

### 追加確認

- プロセス別CPU使用率
- coreごとのCPU使用率
- load average
- thread / worker数
- context switch
- GC発生状況
- profiling結果
- 暗号化・圧縮などCPU負荷の高い処理
- autoscalingの有無

### 現時点で断定できないこと

CPU使用率が高いこと自体は、必ずしも異常ではない。

高CPUでも要件を満たしている場合は問題ではない可能性があるため、レスポンスタイム、RPS、余力、継続時間を合わせて評価する。

---

## 4. Case 3: Memory増加 + GC増加 + レスポンスタイム悪化

### 観測事実

- 試験時間の経過とともにMemory使用量が増加
- GC回数またはGC停止時間が増加
- p95 / p99が徐々に悪化
- CPU使用率も一時的に上昇
- 試験開始直後は正常

### 仮説

メモリ使用量の増加によってGC負荷が高まり、レスポンスタイムへ影響している可能性がある。

メモリリークが存在する可能性もある。

### 追加確認

- heap使用量
- GC回数
- GC pause time
- object allocation rate
- swap利用状況
- OutOfMemory発生有無
- heap dump
- 長時間試験でのMemory推移
- キャッシュサイズ
- 解放されていないオブジェクト

### 現時点で断定できないこと

Memory使用量が増えているだけではメモリリークとは断定できない。

キャッシュなど意図的なMemory利用の可能性もあるため、長時間の推移やGC後の使用量を確認する。

---

## 5. Case 4: Disk I/O wait増加 + DB処理遅延

### 観測事実

- p95 / p99が悪化
- CPU utilization自体は高くない
- I/O waitが増加
- DB query timeが悪化
- RPSが低下
- Disk latencyが増加

### 仮説

Disk I/Oがボトルネックとなり、DB処理やファイルアクセスを待たせている可能性がある。

### 追加確認

- IOPS
- read latency
- write latency
- disk queue length
- I/O wait
- DB buffer cache hit rate
- slow query
- 一時ファイル生成量
- ログ出力量
- ストレージの性能上限
- 他プロセスによるDisk利用

### 現時点で断定できないこと

Disk latency増加とアプリケーション遅延に相関があっても、直接的な因果関係までは確認できない。

DBの実行計画やキャッシュ状況など、他の要因も確認する必要がある。

---

## 6. Case 5: Network latency増加 + 外部通信遅延

### 観測事実

- 特定APIのレスポンスタイムだけが悪化
- CPU / Memory / DBは正常範囲
- 外部サービスへの通信時間が増加
- timeoutが一部発生
- 同一サーバー内処理は正常

### 仮説

ネットワーク遅延または外部サービス側の応答遅延が影響している可能性がある。

### 追加確認

- 外部API response time
- DNS lookup time
- TCP connection time
- TLS handshake time
- packet loss
- retransmission
- network bandwidth
- timeout設定
- retry回数
- proxy / load balancerの状態
- 外部サービス側のSLA / 障害情報

### 現時点で断定できないこと

外部サービスへの通信時間が長い場合でも、ネットワーク自体が原因とは限らない。

外部サービス側の処理遅延、DNS、TLS、proxyなどを切り分ける必要がある。

---

## 7. Case 6: p95正常 + エラー率のみ増加

### 観測事実

- p95 / p99は性能要件内
- RPSもbaselineと大きな差がない
- error rateのみ閾値超過
- CPU / Memoryは正常
- 一部のHTTP 5xxが増加

### 仮説

性能遅延ではなく、アプリケーション例外や依存サービスの失敗が発生している可能性がある。

### 追加確認

- HTTP status内訳
- application log
- stack trace
- timeout
- DB error
- 外部API error
- retry状況
- 入力データ
- validation error
- エラー発生APIの偏り

### 現時点で断定できないこと

レスポンスタイムが正常だからといって、システムが正常とは判断できない。

また、HTTPエラーのすべてが性能問題とは限らないため、エラー種別の分類が必要になる。

---

## 8. Case 7: baseline比で性能悪化するが絶対閾値はPASS

### 観測事実

- current p95: 200ms
- p95閾値: 250ms
- baseline p95: 100ms
- error rateは正常
- p99も絶対閾値内
- RPSは若干低下

### 仮説

絶対的な性能要件は満たしているが、過去状態と比較して性能回帰が発生している可能性がある。

### 追加確認

- リリース差分
- アプリケーションバージョン
- DB schema変更
- SQL実行計画
- ライブラリ更新
- インフラ設定変更
- テストデータ量
- キャッシュ条件
- baselineとの環境差
- RPS低下率

### 現時点で断定できないこと

baselineとの差だけで障害とは断定できない。

性能要件を満たしている場合、回帰を許容するかどうかは業務要件、将来負荷、性能余力を踏まえて判断する必要がある。

---

## 9. Case 8: p95悪化 + CPU / DB / Memory正常

### 観測事実

- p95 / p99が悪化
- CPU正常
- Memory正常
- DB query time正常
- error rate正常
- 特定APIのみ遅い

### 仮説

アプリケーション内部の同期処理、外部API待ち、lock、thread待ちなどが影響している可能性がある。

### 追加確認

- application trace
- function / method単位の処理時間
- thread pool
- lock wait
- external API call
- retry処理
- serialization / deserialization
- cache hit rate
- APM trace

### 現時点で断定できないこと

主要リソースが正常でも、アプリケーション内部に待ち時間が存在する可能性がある。

CPU・DB・Memoryが正常という情報だけで「システムに問題なし」とは判断できない。

---

## 10. Case 9: Spike後も性能が回復しない

### 観測事実

- 一時的に大量アクセスが発生
- Spike中にp95 / error rateが悪化
- 負荷を通常値へ戻してもp95が高いまま
- CPUは徐々に低下
- DB接続数が高い状態を維持

### 仮説

Spike中に発生したconnection、queue、retry、cacheなどの状態が残り、回復を遅らせている可能性がある。

### 追加確認

- connection pool
- queue length
- pending request
- retry backlog
- DB connection
- thread pool
- autoscaling状態
- cache状態
- recovery time
- circuit breaker状態

### 現時点で断定できないこと

Spikeによってシステムが恒久的に劣化したとは断定できない。

一時的なbacklogやリソース解放待ちの可能性があるため、回復過程を時系列で確認する。

---

## 11. Case 10: 長時間試験で徐々に性能悪化

### 観測事実

- 試験開始時は正常
- 数時間経過するとp95 / p99が徐々に悪化
- error rateも少しずつ増加
- Memory使用量も増加傾向
- RPSが低下

### 仮説

長時間稼働によって蓄積する状態が性能へ影響している可能性がある。

候補としては、Memory leak、connection leak、ログ肥大化、cache肥大化などが考えられる。

### 追加確認

- Memory推移
- connection count
- file descriptor
- thread数
- log size
- temporary file
- cache size
- GC
- resource leak
- long-running query
- 数時間単位の時系列データ

### 現時点で断定できないこと

長時間試験で悪化したからといって、Memory leakとは限らない。

複数のリソース推移を時系列で比較し、継続的に増加している対象を確認する必要がある。

---

## 12. 性能問題を切り分ける基本フロー

性能問題を調査する際は、以下の順で整理する。

```text
1. 症状を確認
   ↓
2. baselineとの差を確認
   ↓
3. サービス指標を確認
   - p95 / p99
   - error rate
   - RPS
   ↓
4. リソース指標を確認
   - CPU
   - Memory
   - Disk I/O
   - Network
   ↓
5. DB / 外部サービスを確認
   ↓
6. ログ / Traceを確認
   ↓
7. 原因仮説を立てる
   ↓
8. 追加データで検証する
   ↓
9. 原因を特定する
```

重要なのは、**仮説と事実を分離すること**である。

---

## 13. AIを使う場合のルール

AIへ性能データを渡す場合でも、以下を守る。

### AIに任せること

- 観測事実の整理
- baselineとの差分整理
- 原因候補の列挙
- 追加確認項目の提案
- 調査順序の整理

### AIに任せないこと

- PASS / FAILの最終判定
- 証拠のない原因断定
- リリース可否判断
- 改善施策の最終決定

例えば、

```text
DBが原因です
```

ではなく、

```text
DB接続待ちの可能性があります。

確認には、
connection pool利用率、
SQL実行時間、
lock状況、
DB CPUなどの情報が必要です。
```

という形で仮説と追加確認項目を分離する。

---

## 14. 現在のPoCとの関係

現在のAI-Native Performance Engineering PoCでは、

```text
Locust
↓
CSV
↓
Python
↓
閾値判定
↓
baseline比較
↓
JSON / Markdown
↓
AI分析支援
↓
Human Review
```

まで実装している。

今後、以下の情報を追加できれば、単なる性能判定から**性能問題の切り分け支援**へ拡張できる。

- CPU
- Memory
- Disk I/O
- DB metrics
- application log
- trace
- network metrics
- external API metrics

---

## 15. 次の学習課題

- Linux performance metrics
- CPU saturation
- Memory / GC
- Disk I/O
- DB bottleneck
- Network latency
- Connection pool
- Thread pool
- APM / Distributed Tracing
- Soak Test
- Spike Test
- Capacity Planning
