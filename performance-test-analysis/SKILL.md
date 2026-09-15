---
name: performance-test-analysis
description: Analyze normalized or Locust performance-test CSV results, identify threshold violations and regressions, and produce an evidence-based report. Use when reviewing load-test results or comparing a run with a baseline; do not invent causes from metrics alone.
---

# Performance Test Analysis

Turn performance-test measurements into a reviewable engineering assessment.

## Workflow

1. Confirm the result CSV, evaluation policy, run manifest, and optional baseline pair. If acceptance criteria are provisional, keep that status in the report.
2. When comparing runs, inspect both manifests. Do not calculate regression when the tool, target, dataset, workload signature, warm-up duration, or statistics reset mode differs.
3. Read `evaluation.warmup_seconds` from the policy. Report the configured duration and the number of excluded rows for both the current and baseline runs.
4. Check `stats_reset_detected` and `baseline_stats_reset_detected`. A manifest declaration alone is not proof that the statistics reset actually occurred.
5. When a reset is detected, state that a decrease in cumulative request counts confirms the reset. When it is not detected, state that warm-up requests may remain in cumulative percentiles and request counters.
6. Evaluate the final cumulative error rate against the service threshold. Report the peak observed error rate separately as diagnostic evidence.
7. Compare median throughput after applying the evaluation window. Treat a decrease beyond `rps_decrease_percent_max` as a regression, not as proof of a specific root cause.
8. Run `scripts/analyze_results.py` to produce deterministic JSON and Markdown evidence. Prefer calculations from the script over mental arithmetic.
9. Treat service-level breaches as `FAIL` and resource pressure as `WARN`; CPU or memory alone does not prove user impact.
10. Separate observations from hypotheses. An observation must quote a calculated metric, threshold, comparison, or reset-detection result.
11. Report threshold violations, baseline regressions, reset status, risks, and the next measurement needed to confirm each hypothesis.
12. Require human review before a release decision.

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
- Use median RPS, not peak RPS, for throughput regression judgment.
- Do not attribute an RPS decrease to application code without checking the load generator, network, environment, and dependent services.
- Do not claim that statistics were reset solely because the manifest specifies `locust_reset_all`.
- Use the decrease in cumulative request counts as evidence that the reset occurred.
- If reset detection differs between the current and baseline runs, identify it as a data-quality risk and qualify the regression assessment.

Return a concise assessment containing: verdict, evaluation window, excluded-row counts, statistics reset status, final cumulative error rate, peak observed error rate, median throughput, throughput regression, evidence, plausible hypotheses, additional checks, and human-review points. Keep deterministic values unchanged from the generated evidence.
