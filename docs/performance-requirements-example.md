# Performance Requirements Example

## 1. この資料の目的

本資料は、業務要件から性能要件・負荷試験条件へ落とし込む流れを、架空のECサービスを題材に整理する。

数値はすべて学習用の仮定であり、実案件における標準値を示すものではない。

実案件では、以下のような情報を関係者と確認して決定する。

- SLA / SLO
- 実際のアクセスログ
- 業務ピーク
- 利用者数
- 画面 / APIごとの利用比率
- 将来の利用増加率

---

## 2. 想定システム

架空のECサービスを対象とする。

主な機能は以下。

1. ログイン
2. 商品検索
3. 商品詳細表示
4. カート追加
5. 注文確定

ユーザーはWebブラウザからサービスを利用する。

バックエンドはREST APIで構成されているものとする。

---

## 3. 業務側から確認できた想定

以下の情報が業務側から提示されたと仮定する。

| 項目 | 想定値 |
|---|---:|
| 登録ユーザー数 | 100,000人 |
| 通常時同時利用者 | 200人 |
| ピーク時同時利用者 | 500人 |
| 最大ピーク継続時間 | 10分 |
| 今後1年間の利用増加見込み | 20% |
| 許容エラー率 | 1%未満 |

登録ユーザー数100,000人全員が同時利用するわけではない。

そのため性能試験では、**登録ユーザー数ではなく、実際に同時利用すると想定されるユーザー数**を基準に負荷条件を作成する。

---

## 4. ユーザー行動モデル

ピーク時間帯にユーザーが以下の割合で操作すると仮定する。

| 操作 | 割合 |
|---|---:|
| ログイン | 10% |
| 商品検索 | 40% |
| 商品詳細表示 | 30% |
| カート追加 | 15% |
| 注文確定 | 5% |

合計は100%となる。

この操作比率をLocustのタスク比率へ反映する。

例：

```python
@task(8)
def search(self):
    ...

@task(6)
def product_detail(self):
    ...

@task(3)
def add_cart(self):
    ...

@task(1)
def purchase(self):
    ...
```

実際の実装では、利用する負荷試験ツールに合わせて整数比率などへ変換する。

---

## 5. ピーク負荷の考え方

ピーク時同時利用者は500人とする。

さらに1年間で利用量が20%増加すると想定した場合、

```text
500 × 1.2 = 600
```

となる。

そのため、将来負荷を考慮した性能確認では、**600 concurrent users**を一つの試験条件候補とする。

ただし、**「利用者が20%増えたからRPSも必ず20%増える」わけではない。**

ユーザー行動や操作頻度が変化する可能性があるため、実案件では実アクセスログなどから確認する。

---

## 6. RPSの算出例

ピーク5分間に発生すると想定されるAPIリクエスト数が36,000件だったと仮定する。

5分は300秒なので、

```text
36,000 ÷ 300 = 120 requests/sec
```

となる。

したがって、**目標処理量：120 RPS**を性能要件候補とする。

将来増加分20%を考慮すると、

```text
120 × 1.2 = 144 RPS
```

となる。

余裕を持たせる場合、150 RPS程度を試験条件候補として設定することも考えられる。

ただし、この余裕率も業務要件やリスク許容度に基づいて決定する。

---

## 7. レスポンスタイム要件

各処理について、以下の性能目標が合意されたと仮定する。

| API | p95 | p99 |
|---|---:|---:|
| ログイン | 500ms以下 | 1,000ms以下 |
| 商品検索 | 800ms以下 | 1,500ms以下 |
| 商品詳細 | 500ms以下 | 1,000ms以下 |
| カート追加 | 500ms以下 | 1,000ms以下 |
| 注文確定 | 1,000ms以下 | 2,000ms以下 |

注文処理は、在庫確認・DB更新・外部サービス連携などを含む可能性があるため、他の参照系APIより許容時間を長く設定したという想定である。

この数値も学習用の仮定であり、実際には利用者要求・既存実績・SLOなどから決定する。

---

## 8. エラー率要件

ピーク負荷時でも、以下を目標とする。

```text
error rate < 1%
```

ただし、HTTP 4xx / 5xxをすべて同じ「性能エラー」と扱うとは限らない。

例えば、401 Unauthorizedが不正なテストデータによって発生している場合と、503 Service Unavailableが負荷によって発生している場合では意味が異なる。

そのため実案件では、以下を分類する必要がある。

- HTTP Status
- application error
- timeout
- validation error
- test data error

---

## 9. 性能試験シナリオ

### 9.1 Baseline Test

目的：通常状態の性能を記録する。

想定：

```text
Users: 200
Duration: 10 min
```

確認項目：

- p95
- p99
- error rate
- RPS
- CPU
- Memory
- DB metrics

### 9.2 Peak Load Test

目的：想定ピーク負荷に耐えられるか確認する。

想定：

```text
Users: 500
Duration: 10 min
Target throughput: 約120 RPS
```

判定対象：

- API別p95 / p99
- error rate
- throughput
- resource utilization

### 9.3 Future Load Test

目的：利用量20%増加後を想定する。

想定：

```text
Users: 600
Target throughput: 約144 RPS
```

ここでは「現時点でサービス提供可能か」だけでなく、**将来的にどこで性能限界が現れるか**も確認する。

### 9.4 Spike Test

目的：短時間のアクセス集中時の挙動を確認する。

例：

```text
200 users
↓
短時間で600 users
↓
数分後200 usersへ戻す
```

確認項目：

- error rate急増の有無
- latencyの急激な悪化
- recovery time
- connection pool
- autoscaling
- resource saturation

---

## 10. 合否判定の例

ピーク負荷試験で以下の結果だったとする。

```text
Peak users: 500
p95: 650ms
p99: 1,200ms
Error rate: 0.3%
RPS: 123
```

対象が商品検索APIで、以下の要件だとする。

```text
p95 <= 800ms
p99 <= 1,500ms
error rate < 1%
target throughput >= 120 RPS
```

判定は以下となる。

```text
p95        : PASS
p99        : PASS
error rate : PASS
RPS        : PASS
```

したがって、この条件だけを見れば、

```text
Service Performance: PASS
```

となる。

ただしCPU使用率が95%だった場合、性能要件は満たしていても、

```text
Resource Risk: WARN
```

として追加確認する。

つまり、**サービス性能の合否と、リソース余力の評価は分けて扱う。**

---

## 11. 性能要件を決める流れ

性能要件定義を単純化すると、以下の流れになる。

```text
業務要件
↓
利用者数
↓
ピーク条件
↓
ユーザー行動モデル
↓
API利用比率
↓
TPS / RPS
↓
レスポンスタイム目標
↓
エラー率
↓
負荷試験条件
↓
合否判定
```

重要なのは、p95 = 500msのような値を技術者が先に決めるのではなく、**なぜ500ms以内である必要があるのかを業務要件から説明できる状態にすること**である。

---

## 12. 性能試験で確認するデータ

負荷試験結果だけでなく、以下の情報を同じ時間軸で確認する。

### Application

- response time
- throughput
- error rate
- application log
- thread / worker
- GC

### OS / Infrastructure

- CPU
- Memory
- Disk I/O
- Network

### Database

- SQL execution time
- connection count
- connection pool
- lock
- slow query
- DB CPU
- DB Memory

### External Service

- response time
- timeout
- error rate

これらを組み合わせて、以下の流れで原因調査を進める。

```text
観測事実
↓
原因仮説
↓
追加確認
↓
原因特定
```

---

## 13. AIを利用する場合

AIへ渡す情報の例：

```text
Peak users: 500

Current:
p95: 1,200ms
p99: 1,800ms
error rate: 0.4%
RPS: 85

Baseline:
p95: 600ms
p99: 900ms
RPS: 125
```

AIには以下を提示させる。

- 性能劣化の整理
- baselineとの差分
- 原因候補
- 追加確認項目

ただし、

```text
DBがボトルネックです
```

のような断定はさせない。

監視情報がなければ、

```text
DB待ちの可能性がある。

確認するためには、
SQL実行時間、
connection pool、
lock、
DB CPU等の情報が必要。
```

という仮説として扱う。

---

## 14. 現在のPoCとの対応

現在のAI-Native Performance Engineering PoCでは、以下まで実装している。

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

現在のPoCでは性能条件を設定ファイルで与えているが、実案件ではその前段として、

```text
業務要件
↓
性能要件
↓
負荷モデル
```

を設計する必要がある。

この部分が、今後学習すべき重要領域である。

---

## 15. この例から分かったこと

性能試験は、**ツールで負荷をかけることから始まるのではない。**

その前に、以下を整理する必要がある。

- 誰が使うか
- 何人使うか
- いつ使うか
- どの機能を使うか
- どの程度の応答性能を求めるか
- どの程度の障害を許容するか

その結果として、以下の試験条件が決まる。

```text
Users
RPS
p95
p99
Error Rate
Duration
```

つまり性能試験では、**負荷試験ツールを操作する能力だけでなく、業務要件を試験条件へ変換する能力が必要になる。**

---

## 16. 次の学習課題

- 実アクセスログから負荷モデルを作る方法
- TPSとRPSの違い
- Concurrent UsersとRPSの関係
- Think Time
- Ramp-up
- Spike Test
- Soak Test
- Stress Test
- キャパシティプランニング
- ボトルネック解析
