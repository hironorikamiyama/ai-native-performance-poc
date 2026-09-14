---
name: performance-test-analysis
description: Analyze normalized or Locust performance-test CSV results, identify threshold violations and regressions, and produce an evidence-based report. Use when reviewing load-test results or comparing a run with a baseline; do not invent causes from metrics alone.
---

# Performance Test Analysis

Turn performance-test measurements into a reviewable engineering assessment.

## Workflow

1. Confirm the result CSV, evaluation policy, run manifest, and optional baseline pair. If acceptance criteria are provisional, keep that status in the report.
2. Read `evaluation.warmup_seconds` from the policy. Report the configured duration and the number of excluded rows for both the current and baseline runs.
3. Treat the exclusion as measurement-row filtering only. Locust percentiles, request counts, and failure counts remain cumulative unless the statistics were explicitly reset after warm-up.
4. Use the final cumulative error rate for the service threshold judgment. Report the peak observed error rate separately as diagnostic information, not as the verdict input.
5. When comparing runs, inspect both manifests. Do not calculate regression when tool, target, dataset, or workload signature differs.
6. Run `scripts/analyze_results.py` to produce deterministic JSON and Markdown evidence. Prefer calculations from the script over mental arithmetic.
7. Treat service-level breaches as `FAIL` and resource pressure as `WARN`; CPU or memory alone does not prove user impact.
8. Separate observations from hypotheses. An observation must quote a calculated metric, threshold, or comparison. A cause is a hypothesis unless supported by application, database, or infrastructure evidence.
9. Report threshold violations, baseline regressions, risk, and the next measurement needed to confirm each hypothesis.
10. Require human review before a release decision.

## Command

From this skill directory:

```bash
python scripts/analyze_results.py RESULT.csv --thresholds THRESHOLDS.json \
  --output-json analysis.json --output-md analysis.md
```

For a controlled comparison, add all three options:

```bash
--baseline BASELINE.csv --manifest RUN_MANIFEST.json \
--baseline-manifest BASELINE_MANIFEST.json
```

## Input

The preferred CSV columns are:

`timestamp,users,requests,failures,avg_ms,p95_ms,p99_ms,rps,cpu_percent,memory_percent`

The script also recognizes core columns from Locust `*_stats_history.csv` output. CPU and memory are optional; explicitly state when infrastructure metrics are absent.

## Constraints

- Never calculate percentiles by averaging percentile columns.
- Do not attribute latency to CPU, database, network, or code without corroborating metrics or traces.
- A passing sample does not prove production capacity beyond the tested load and duration.
- Compare runs only when workload, environment, data volume, and configuration are sufficiently similar.
- Keep service acceptance criteria separate from diagnostic resource thresholds.
- Mention data-quality limitations and omitted metrics.
- Apply the same warm-up duration to the current and baseline runs.
- Do not claim that filtering Locust history rows completely removes warm-up requests from cumulative metrics.
- Do not use the peak observed error rate as the service verdict input when a final cumulative error rate is available.
- Clearly distinguish the final cumulative error rate from the peak observed error rate.

Return a concise assessment containing: verdict, evaluation window, excluded-row counts, final cumulative error rate, peak observed error rate, evidence, regressions, plausible hypotheses, additional checks, and human-review points. Keep deterministic values unchanged from the generated evidence.
