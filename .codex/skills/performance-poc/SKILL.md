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
8. When analysis has not yet been generated, run `scripts/analyze_results.py` to produce deterministic JSON and Markdown evidence. When reviewing existing reports, use the Python analysis JSON as the numerical and verdict source of truth; do not recompute or override its verdict or finding statuses.
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

## AI review inputs

- Use the Python analysis JSON: `verdict`, `report_schema_version`, `policy`, `findings`, `endpoints` and their findings, `summary`, `baseline_summary`, `evaluation`, `comparability`, and `limitations`.
- Use Markdown as a reading aid, not a second numerical authority. If artifacts disagree, report the discrepancy and ask a human to verify the run and generation time; do not silently reconcile them.
- Use supplied current/baseline manifests to assess recorded comparison conditions. Logs, traces, and infrastructure measurements are optional corroborating evidence; identify their source, run, and time range.
- Do not infer missing inputs. In particular, `comparability: null` does not by itself mean that no baseline was supplied. Distinguish baseline absence from comparison conditions not being verified.
- Avoid duplicate copies of evidence and unrelated CSV rows, code, logs, credentials, or personal data. Retain normal measurements needed to explain the findings. If inputs are abbreviated, disclose omissions.

## AI review rules

The Python JSON is the source of truth for numerical evidence and deterministic decisions. Preserve `verdict`, every quoted finding status, and calculated values. Do not rejudge rounded values, replace missing/invalid values with zero, or add an AI PASS/FAIL decision. The AI review is a separate artifact, not a modification of the analysis report.

Present evaluation limitations before causal analysis:

- `INVALID_DATA`: identify the affected scope, metric, source when recorded, and reason. Explain which evaluations are unavailable. Do not build hypotheses on invalid measurements. Preserve valid FAIL findings when FAIL and INVALID_DATA coexist.
- `NOT_COMPARABLE`: state that regression assessment was suppressed and identify the mismatched conditions. Do not calculate a replacement regression; current absolute-threshold findings remain usable.
- Manifest absent: quote existing Python comparison findings with an explicit "comparison conditions unverified" qualification.
- `NOT_EVALUATED`: identify the metric and reason, such as a zero baseline. Do not describe it as PASS or substitute another baseline value. Also disclose unavailable endpoint RPS comparisons reported as INFO.
- Reset not detected or detection differing between runs: state each run's result separately and qualify cumulative statistics and regression interpretation.
- Even when the verdict is PASS, disclose unevaluated comparisons, unverified conditions, optional metric omissions, provisional criteria, and the tested workload/duration limits. Resource WARN and endpoint RPS INFO do not establish a service failure or a cause.

Separate the output into four explicit parts:

1. **Observations / 観測事実**: cite supplied measurements, thresholds, Python statuses, calculated comparisons, reset results, missing inputs, and evaluation limitations. Each observation needs an ID and evidence references. Distinguish final cumulative error rate from diagnostic peak observed error rate, absolute thresholds from regression, and overall from endpoint results. Do not infer time trends or correlations from independent aggregate peaks.
2. **Hypotheses / 原因仮説**: each hypothesis needs an ID, related observation IDs, a qualified explanation, missing evidence, and the additional evidence needed to support or refute it. Use "may", "possible", and "unconfirmed" for causal claims. Wording alone is insufficient: every hypothesis must have a relevant evidential basis and a verification path. Do not assert that DB, CPU, network, application code, or another component caused the finding, and do not list such components mechanically. Allow `hypotheses: []` when evidence is insufficient; never invent speculation to fill this section.
3. **Additional checks / 追加確認事項**: each check needs an ID, priority, related observation/hypothesis IDs, a concrete action, required evidence, and its purpose or interpretation criteria. Prioritize CSV/collection validation, comparability, reset verification, and unevaluated baselines before investigating causes that depend on those inputs. A hypothesis-specific check must explain how the evidence could support or refute the hypothesis.
4. **Human review / 人間確認**: each item needs an ID, related observation/hypothesis/check IDs as applicable, the triggering condition, and the decision or verification requested. Humans make the final cause determination, performance assessment, and release decision. The AI must not approve a release.

Explicitly flag human review for FAIL, INVALID_DATA, NOT_COMPARABLE, unverified comparison conditions, NOT_EVALUATED or unavailable INFO comparisons, reset limitations, provisional criteria, relevant resource warnings or missing optional metrics, and conflicting artifacts. Human release review is required even when none of these conditions occurs.

## Recommended review format

Use `review_schema_version = "1.0"` for the separate AI review structure. This version does not change the Python analysis `report_schema_version = "1.2"` or its JSON schema. The following envelope is reusable for a future API integration; it does not require or authorize an external API call:

```json
{
  "review_schema_version": "1.0",
  "input_report_schema_version": "1.2",
  "python_verdict": "PASS",
  "review_limitations": [],
  "observations": [],
  "hypotheses": [],
  "additional_checks": [],
  "human_review": {
    "release_decision_required": true,
    "items": []
  }
}
```

Copy `input_report_schema_version` and `python_verdict` from the actual input; PASS above is only an envelope example. Populate observations and human-review items for the actual run. Empty hypotheses are valid, not evidence of a confirmed cause.

Use these item fields:

| Collection | Required fields |
|---|---|
| `review_limitations` | `id` (L1...), `statement`, `evidence_refs` |
| `observations` | `id` (O1...), `scope`, `statement`, `evidence_refs`, `limitations`; include the unchanged `python_status` when citing a finding |
| `hypotheses` | `id` (H1...), `statement`, `observation_ids`, `missing_evidence`, `supporting_evidence_needed`, `refuting_evidence_needed` |
| `additional_checks` | `id` (C1...), `priority` (high/medium/low), `observation_ids`, `hypothesis_ids`, `action`, `required_evidence`, `purpose` |
| `human_review.items` | `id` (R1...), `related_ids`, `condition`, `requested_decision` |

IDs must be unique within the review, and all ID references must resolve. Each hypothesis must reference at least one observation. Each observation must reference supplied evidence; an evidence reference contains `artifact_id` and `pointer` (a JSON Pointer for JSON artifacts, or a precise location for other supplied evidence). Do not fabricate artifact references, numerical confidence scores, measurements, or timestamps. Missing information may be stated explicitly as missing.

For Markdown output, show the unchanged Python verdict and limitations first, followed by the four named parts in order. Preserve the same IDs and evidence links as the structured form. Keep the review concise while covering evaluation window, excluded rows, both reset results, final/peak error rates, median throughput, regression findings, and relevant endpoints. Do not duplicate the full analysis JSON.

Before returning the review, check that the Python verdict/statuses and quoted numbers are unchanged, evidence and ID references resolve, limitations precede hypotheses, and every proposed causal explanation has a supporting/refuting evidence plan. This format is a recommended review contract, not an implemented API integration or automated validator.
