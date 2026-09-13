# Performance Test Analysis

**Service verdict: FAIL**

## Deterministic evidence

- Samples: 55
- Peak users: 50
- Peak p95: 380.00 ms
- Peak p99: 390.00 ms
- Peak error rate: 6.667%
- Peak throughput: 80.70 requests/s
- CPU: not supplied
- Memory: not supplied

## Checks

- FAIL: p95_ms=380.0 (limit 250.0)
- PASS: p99_ms=390.0 (limit 500.0)
- FAIL: error_rate_percent=6.667 (limit 1.0)
- FAIL: p95_ms changed 493.75% (64.0 -> 380.0; limit 20.0%)
- FAIL: p99_ms changed 343.18% (88.0 -> 390.0; limit 20.0%)

## Baseline comparability

- COMPARABLE: Tool, target, and workload signature match.

## AI review instructions

Using only the evidence above, explain observed trends and risks. Treat causes as hypotheses, state what additional application/DB/infrastructure evidence would confirm them, and require human review before a release decision.
