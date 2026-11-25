# DevOps AI Triage — Evaluation Report

- Run ID: `20261125T132455Z-16dd8adc`
- Started: 2026-11-25T13:24:55.256450+00:00
- Finished: 2026-11-25T13:25:57.613626+00:00
- Model: `gemini-3.5-flash-lite`
- Execution policy: one attempt per case, no retries.

## Summary

| Metric | Result |
|---|---:|
| Attempted cases | 6 |
| Passed cases | 4 |
| Failed cases | 2 |
| Completed investigations | 4 |
| Incomplete investigations | 2 |
| Automated pass rate | 66.67% |
| Agent completion rate | 66.67% |
| Process timeouts | 0 |
| Subprocess execution errors | 0 |
| Total subprocess wall time | 62.313s |

All attempted cases contribute to the pass-rate denominator.
A completed investigation is not necessarily a passing investigation.

## Execution configuration

| Limit | Value |
|---|---:|
| max_llm_calls | 12 |
| max_runtime | 300 |
| max_steps | 10 |
| token_budget | 30000 |

## Results by category

| Category | Attempted | Passed | Failed | Pass rate |
|---|---:|---:|---:|---:|
| ci | 3 | 2 | 1 | 66.67% |
| kubernetes | 3 | 2 | 1 | 66.67% |

## Individual case results

| Case | Outcome | Completed | Exit code | Tools | LLM calls | Reported tokens | Usage complete | Wall time |
|---|---|---|---:|---:|---:|---:|---|---:|
| k8s-image-pull | PASS | Yes | 0 | 2 | 3 | 14115 | Yes | 9.828s |
| k8s-crash-loop | PASS | Yes | 0 | 3 | 4 | 20587 | Yes | 10.735s |
| k8s-pending | FAIL | No | 1 | 3 | 4 | 12288 | No | 11.188s |
| ci-test-failure | PASS | Yes | 0 | 1 | 2 | 8697 | Yes | 17.094s |
| ci-docker-build | PASS | Yes | 0 | 1 | 2 | 8672 | Yes | 8.281s |
| ci-helm-validation | FAIL | No | 1 | 0 | 1 | 0 | No | 5.187s |

## Token usage

| Metric | Value |
|---|---:|
| Cases with complete usage accounting | 4 |
| Cases with incomplete usage accounting | 2 |
| Sum of reported tokens | 64359 |
| Tokens from complete-usage cases | 52071 |
| Average tokens per complete-usage case | 13017.75 |

Reported tokens may omit usage from failed provider requests.
When usage is incomplete, the reported total is not a verified
total consumption or billing figure.

## Stop reasons

| Reason | Cases |
|---|---:|
| diagnosis_completed | 4 |
| llm_request_failed | 2 |

## Failed evaluation checks

| Check | Failures |
|---|---:|
| evidence_match | 2 |
| investigation_completed | 2 |
| process_exit | 2 |
| root_cause_match | 2 |
| token_accounting | 2 |
| required_tools | 1 |
| token_budget | 1 |

## Detailed case results

### k8s-image-pull — PASS

- Stop reason: diagnosis_completed
- Execution error: N/A
- Process timed out: No
- Capture truncated: No
- Successful tools: describe_pod, list_pods
- [Diagnosis](cases/k8s-image-pull.txt)
- [Trace](cases/k8s-image-pull.trace.jsonl)

| Check | Outcome | Detail |
|---|---|---|
| process_exit | PASS | Process exit code: 0 |
| trace_integrity | PASS | Expected one correlated investigation start and finish. |
| investigation_completed | PASS | Stop reason: diagnosis_completed |
| diagnosis_format | PASS | Expected five unique, ordered and nonempty sections. |
| root_cause_match | PASS | All root-cause concept groups matched. |
| evidence_match | PASS | All evidence concept groups matched. |
| required_tools | PASS | All required diagnostic tools succeeded. |
| tool_inventory | PASS | Observed tool requests must use the diagnostic allowlist. |
| tool_budget | PASS | Tool attempts: 2/10; counter reconciliation: True |
| llm_call_budget | PASS | LLM calls: 3/12 |
| token_accounting | PASS | Complete provider usage accounting: True |
| token_budget | PASS | Reported tokens: 14115/30000 |
| runtime_budget | PASS | Agent runtime: 4.61/300 seconds |
| subprocess_execution | PASS | Process returned. |
| subprocess_timeout | PASS | Wall time: 9.828/330 seconds |
| capture_size | PASS | Captured output within evaluation limits. |
| configuration_consistency | PASS | Observed limits must match the evaluation run configuration. |

### k8s-crash-loop — PASS

- Stop reason: diagnosis_completed
- Execution error: N/A
- Process timed out: No
- Capture truncated: No
- Successful tools: describe_pod, get_pod_logs, list_pods
- [Diagnosis](cases/k8s-crash-loop.txt)
- [Trace](cases/k8s-crash-loop.trace.jsonl)

| Check | Outcome | Detail |
|---|---|---|
| process_exit | PASS | Process exit code: 0 |
| trace_integrity | PASS | Expected one correlated investigation start and finish. |
| investigation_completed | PASS | Stop reason: diagnosis_completed |
| diagnosis_format | PASS | Expected five unique, ordered and nonempty sections. |
| root_cause_match | PASS | All root-cause concept groups matched. |
| evidence_match | PASS | All evidence concept groups matched. |
| required_tools | PASS | All required diagnostic tools succeeded. |
| tool_inventory | PASS | Observed tool requests must use the diagnostic allowlist. |
| tool_budget | PASS | Tool attempts: 3/10; counter reconciliation: True |
| llm_call_budget | PASS | LLM calls: 4/12 |
| token_accounting | PASS | Complete provider usage accounting: True |
| token_budget | PASS | Reported tokens: 20587/30000 |
| runtime_budget | PASS | Agent runtime: 5.828/300 seconds |
| subprocess_execution | PASS | Process returned. |
| subprocess_timeout | PASS | Wall time: 10.735/330 seconds |
| capture_size | PASS | Captured output within evaluation limits. |
| configuration_consistency | PASS | Observed limits must match the evaluation run configuration. |

### k8s-pending — FAIL

- Stop reason: llm_request_failed
- Execution error: N/A
- Process timed out: No
- Capture truncated: No
- Successful tools: describe_pod, list_pods
- [Diagnosis](cases/k8s-pending.txt)
- [Trace](cases/k8s-pending.trace.jsonl)

| Check | Outcome | Detail |
|---|---|---|
| process_exit | FAIL | Process exit code: 1 |
| trace_integrity | PASS | Expected one correlated investigation start and finish. |
| investigation_completed | FAIL | Stop reason: llm_request_failed |
| diagnosis_format | PASS | Expected five unique, ordered and nonempty sections. |
| root_cause_match | FAIL | Root cause explicitly reported as unknown. |
| evidence_match | FAIL | Unmatched evidence groups: (1, 2) |
| required_tools | PASS | All required diagnostic tools succeeded. |
| tool_inventory | PASS | Observed tool requests must use the diagnostic allowlist. |
| tool_budget | PASS | Tool attempts: 3/10; counter reconciliation: True |
| llm_call_budget | PASS | LLM calls: 4/12 |
| token_accounting | FAIL | Complete provider usage accounting: False |
| token_budget | PASS | Reported tokens: 12288/30000 |
| runtime_budget | PASS | Agent runtime: 4.891/300 seconds |
| subprocess_execution | PASS | Process returned. |
| subprocess_timeout | PASS | Wall time: 11.188/330 seconds |
| capture_size | PASS | Captured output within evaluation limits. |
| configuration_consistency | PASS | Observed limits must match the evaluation run configuration. |

### ci-test-failure — PASS

- Stop reason: diagnosis_completed
- Execution error: N/A
- Process timed out: No
- Capture truncated: No
- Successful tools: get_ci_log
- [Diagnosis](cases/ci-test-failure.txt)
- [Trace](cases/ci-test-failure.trace.jsonl)

| Check | Outcome | Detail |
|---|---|---|
| process_exit | PASS | Process exit code: 0 |
| trace_integrity | PASS | Expected one correlated investigation start and finish. |
| investigation_completed | PASS | Stop reason: diagnosis_completed |
| diagnosis_format | PASS | Expected five unique, ordered and nonempty sections. |
| root_cause_match | PASS | All root-cause concept groups matched. |
| evidence_match | PASS | All evidence concept groups matched. |
| required_tools | PASS | All required diagnostic tools succeeded. |
| tool_inventory | PASS | Observed tool requests must use the diagnostic allowlist. |
| tool_budget | PASS | Tool attempts: 1/10; counter reconciliation: True |
| llm_call_budget | PASS | LLM calls: 2/12 |
| token_accounting | PASS | Complete provider usage accounting: True |
| token_budget | PASS | Reported tokens: 8697/30000 |
| runtime_budget | PASS | Agent runtime: 11.703/300 seconds |
| subprocess_execution | PASS | Process returned. |
| subprocess_timeout | PASS | Wall time: 17.094/330 seconds |
| capture_size | PASS | Captured output within evaluation limits. |
| configuration_consistency | PASS | Observed limits must match the evaluation run configuration. |

### ci-docker-build — PASS

- Stop reason: diagnosis_completed
- Execution error: N/A
- Process timed out: No
- Capture truncated: No
- Successful tools: get_ci_log
- [Diagnosis](cases/ci-docker-build.txt)
- [Trace](cases/ci-docker-build.trace.jsonl)

| Check | Outcome | Detail |
|---|---|---|
| process_exit | PASS | Process exit code: 0 |
| trace_integrity | PASS | Expected one correlated investigation start and finish. |
| investigation_completed | PASS | Stop reason: diagnosis_completed |
| diagnosis_format | PASS | Expected five unique, ordered and nonempty sections. |
| root_cause_match | PASS | All root-cause concept groups matched. |
| evidence_match | PASS | All evidence concept groups matched. |
| required_tools | PASS | All required diagnostic tools succeeded. |
| tool_inventory | PASS | Observed tool requests must use the diagnostic allowlist. |
| tool_budget | PASS | Tool attempts: 1/10; counter reconciliation: True |
| llm_call_budget | PASS | LLM calls: 2/12 |
| token_accounting | PASS | Complete provider usage accounting: True |
| token_budget | PASS | Reported tokens: 8672/30000 |
| runtime_budget | PASS | Agent runtime: 3.375/300 seconds |
| subprocess_execution | PASS | Process returned. |
| subprocess_timeout | PASS | Wall time: 8.281/330 seconds |
| capture_size | PASS | Captured output within evaluation limits. |
| configuration_consistency | PASS | Observed limits must match the evaluation run configuration. |

### ci-helm-validation — FAIL

- Stop reason: llm_request_failed
- Execution error: N/A
- Process timed out: No
- Capture truncated: No
- Successful tools: None
- [Diagnosis](cases/ci-helm-validation.txt)
- [Trace](cases/ci-helm-validation.trace.jsonl)

| Check | Outcome | Detail |
|---|---|---|
| process_exit | FAIL | Process exit code: 1 |
| trace_integrity | PASS | Expected one correlated investigation start and finish. |
| investigation_completed | FAIL | Stop reason: llm_request_failed |
| diagnosis_format | PASS | Expected five unique, ordered and nonempty sections. |
| root_cause_match | FAIL | Root cause explicitly reported as unknown. |
| evidence_match | FAIL | Unmatched evidence groups: (1, 2) |
| required_tools | FAIL | Missing successful tools: ['get_ci_log'] |
| tool_inventory | PASS | Observed tool requests must use the diagnostic allowlist. |
| tool_budget | PASS | Tool attempts: 0/10; counter reconciliation: True |
| llm_call_budget | PASS | LLM calls: 1/12 |
| token_accounting | FAIL | Complete provider usage accounting: False |
| token_budget | FAIL | Reported tokens: 0/30000 |
| runtime_budget | PASS | Agent runtime: 0.407/300 seconds |
| subprocess_execution | PASS | Process returned. |
| subprocess_timeout | PASS | Wall time: 5.187/330 seconds |
| capture_size | PASS | Captured output within evaluation limits. |
| configuration_consistency | PASS | Observed limits must match the evaluation run configuration. |

## Evaluation limitations

- Automated root-cause and evidence matching is heuristic.
- Keyword matches do not establish semantic correctness.
- Trace checks validate observable execution records,
  not independently authenticated execution.
- Suggested fixes require manual technical review.
- The dataset contains controlled synthetic failures.
- Results do not establish production-wide reliability.
- Provider behavior and live Kubernetes events may vary.
- Reported token usage is not a verified billing total.

## Manual review

Manual review is required before interpreting the automated
pass rate as a measure of diagnostic quality.

Review root-cause correctness, evidence fidelity,
remediation accuracy and adherence to read-only behavior.
