---
name: performance-test-analysis
description: Analyze normalized or Locust performance-test CSV results, identify threshold violations and regressions, and produce an evidence-based report. Use when reviewing load-test results or comparing a run with a baseline; do not invent causes from metrics alone.
---

# Performance Test Analysis

Turn performance-test measurements into a reviewable engineering assessment.

## Workflow

1. Confirm the target CSV, thresholds, and optional baseline CSV. If acceptance criteria are missing, label conclusions as provisional.
2. Run `scripts/analyze_results.py` to produce deterministic JSON and Markdown evidence. Prefer calculations from the script over mental arithmetic.
3. Separate observations from hypotheses. An observation must quote a calculated metric, threshold, or comparison. A cause is a hypothesis unless supported by application, database, or infrastructure evidence.
4. Report threshold violations, baseline regressions, risk, and the next measurement needed to confirm each hypothesis.
5. Require human review before a release decision.

## Command

From this skill directory:

```bash
python scripts/analyze_results.py RESULT.csv --thresholds THRESHOLDS.json \
  --output-json analysis.json --output-md analysis.md
```

Add `--baseline BASELINE.csv` when a comparable prior run exists.

## Input

The preferred CSV columns are:

`timestamp,users,requests,failures,avg_ms,p95_ms,p99_ms,rps,cpu_percent,memory_percent`

The script also recognizes core columns from Locust `*_stats_history.csv` output. CPU and memory are optional; explicitly state when infrastructure metrics are absent.

## Constraints

- Never calculate percentiles by averaging percentile columns.
- Do not attribute latency to CPU, database, network, or code without corroborating metrics or traces.
- A passing sample does not prove production capacity beyond the tested load and duration.
- Compare runs only when workload, environment, data volume, and configuration are sufficiently similar.
- Mention data-quality limitations and omitted metrics.

Return a concise assessment containing: verdict, evidence, regressions, plausible hypotheses, additional checks, and human-review points. Keep deterministic values unchanged from the generated evidence.
