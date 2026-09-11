# Performance Test Analysis

**Verdict: FAIL**

## Deterministic evidence

- Samples: 3
- Peak users: 50
- Peak p95: 380.00 ms
- Peak p99: 650.00 ms
- Peak error rate: 2.000%
- Peak throughput: 42.00 requests/s
- Peak CPU: 91.00%
- Peak memory: 57.00%

## Checks

- FAIL: p95_ms=380.0 (limit 250.0)
- FAIL: p99_ms=650.0 (limit 500.0)
- FAIL: error_rate_percent=2.0 (limit 1.0)
- FAIL: cpu_percent=91.0 (limit 80.0)
- PASS: memory_percent=57.0 (limit 85.0)
- FAIL: p95_ms changed 261.9% (105.0 -> 380.0; limit 20.0%)
- FAIL: p99_ms changed 319.35% (155.0 -> 650.0; limit 20.0%)

## AI review instructions

Using only the evidence above, explain observed trends and risks. Treat causes as hypotheses, state what additional application/DB/infrastructure evidence would confirm them, and require human review before a release decision.
