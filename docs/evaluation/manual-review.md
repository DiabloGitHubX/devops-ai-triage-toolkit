
# Manual Evaluation Review

## Evaluation identity

- Date: November 25, 2026
- Run ID: `20261125T132455Z-16dd8adc`
- Model: `gemini-3.5-flash-lite`
- Execution policy: one attempt per case, no retries
- Pre-evaluation Git HEAD: `3d7ca457880c3f1f9d97b968abe29afdfc41620e`
- Source integrity: 71 SHA-256 fingerprints verified before and after execution

The evaluation implementation, agent, skill, fixtures and scoring
criteria were fingerprinted before the formal benchmark. The evaluation
code was present as uncommitted working-tree changes at that time.

All six outcomes were retained. No failed case was replaced or retried,
and no scoring criteria were adjusted after the formal run.

## Executive summary

| Metric | Result |
|---|---:|
| Attempted investigations | 6 |
| Automated passes | 4 |
| Automated failures | 2 |
| Automated pass rate | 66.67% |
| Completed investigations | 4/6 |
| Correct root causes among completed investigations | 4/4 |
| Successful MCP tool calls | 10/10 |
| LLM request attempts | 16 |
| Failed LLM requests | 2 |
| Subprocess timeouts | 0 |
| Subprocess execution errors | 0 |
| Reported tokens | 64,359 |
| Complete token accounting | 4/6 |
| Total subprocess wall time | 62.313 seconds |
| Average subprocess wall time | 10.386 seconds |

The official automated pass rate is 66.67%.

The 4/4 manual root-cause correctness result is conditional on
investigation completion and must not be interpreted as a 100%
overall success rate.

Both incomplete investigations terminated following provider HTTP
errors. No incorrect completed root-cause diagnosis was observed.

## Review methodology

Each generated diagnosis was reviewed against:

1. The intended failure defined by the evaluation dataset.
2. The original Kubernetes workload manifests or CI fixtures.
3. Available Kubernetes warning events and container log evidence.
4. The recorded structured execution trace.
5. The technical correctness and safety of the suggested remediation.

The review distinguishes root-cause correctness from evidence fidelity
and remediation precision.

Raw MCP response payloads and tool arguments are intentionally omitted
from structured traces. Therefore, not every historical tool response
or quoted field can be independently reconstructed.

## Individual case review

### 1. Kubernetes ImagePullBackOff

- Case: `k8s-image-pull`
- Automated result: PASS
- Manual root-cause assessment: Correct
- Evidence assessment: Corroborated
- Remediation assessment: Correct with minor caveats

The agent identified the nonexistent image tag
`nginx:triage-nonexistent-tag`.

The configured image matches the workload manifest, and the quoted
registry NotFound error matches the available Kubernetes warning event.

The recommendation to use a verified version tag or immutable digest
is appropriate.

The agent suggested updating either the Deployment or ReplicaSet.
Because the ReplicaSet is managed by a Deployment, the preferred
remediation is to update the source-controlled Deployment manifest:

`env/workloads/payments-api.yaml`

The suggested YAML is a partial manifest adjustment rather than a
complete standalone Deployment definition.

No remediation was applied.

### 2. Kubernetes CrashLoopBackOff

- Case: `k8s-crash-loop`
- Automated result: PASS
- Manual root-cause assessment: Correct
- Evidence assessment: Mostly corroborated
- Remediation assessment: Correct with minor caveats

The agent correctly identified the missing required environment
variable `DATABASE_URL`.

The application source explicitly checks this variable and exits
with status code 1 when it is absent.

The missing-variable error is corroborated by the container log
evidence collected during integration verification.

Referencing a Kubernetes Secret is an appropriate remediation
when the variable contains database credentials.

The referenced Secret and key must exist before deployment.
The suggested YAML should be incorporated into the existing
source-controlled Deployment rather than applied as a complete
standalone manifest.

The trace does not retain tool arguments, so the claim that
`previous=true` was used cannot be independently verified.

The statement that exit code 1 occurred consistently across all
15 restarts is stronger than the available historical evidence.
The application source and latest termination state support the
diagnosis but do not establish every previous termination state.

No remediation was applied.

### 3. Kubernetes Pending

- Case: `k8s-pending`
- Automated result: FAIL
- Manual root-cause assessment: Incomplete
- Failure category: `provider_http_error`
- HTTP status: 503

The intended root cause is an unsatisfiable CPU resource request.

The workload requests 100 CPU cores, and the Kubernetes scheduler
reports insufficient CPU capacity.

The agent successfully executed three diagnostic tool calls:

1. `list_pods`
2. `list_pods`
3. `describe_pod`

The fourth LLM request failed with HTTP 503.

The investigation terminated with an unknown root cause and
low confidence rather than inventing a diagnosis.

This is appropriate failure behavior, but the case remains an
unsuccessful end-to-end investigation.

The fallback retained the successful tool count but did not
present the useful diagnostic evidence already collected.

Reported token usage before failure was 12,288 tokens.
Usage accounting is incomplete.

No remediation was applied.

### 4. CI application test failure

- Case: `ci-test-failure`
- Automated result: PASS
- Manual root-cause assessment: Correct
- Evidence assessment: Minor quotation defect
- Remediation assessment: Correct

The agent correctly identified an application validation defect
that allowed a negative payment amount to be accepted.

The fixture establishes:

- A payment request with `amount=-50`.
- An application log indicating that the payment was accepted.
- An assertion mismatch of `201 == 400`.

The proposed validation condition `amount <= 0` is consistent
with the negative-payment failure and the existing passing
zero-amount rejection test.

The proposed code is illustrative and would need to be integrated
with the actual application's validation and error-handling logic.

#### Evidence fidelity defect

The original fixture contains:

```text
FAILED tests/test_payments.py::test_negative_amount_rejected
```

The agent generated:

```text
FAILED tests/test_payments.py::test_payments.py::test_negative_amount_rejected
```

The agent duplicated part of the test identifier while presenting
the output as quoted evidence.

The automated evaluator did not detect this defect because its
required evidence concepts were still present.

The root-cause diagnosis remains correct, but this demonstrates
that keyword-based evidence matching does not guarantee exact
quotation fidelity.

No remediation was applied.

### 5. CI Docker build failure

- Case: `ci-docker-build`
- Automated result: PASS
- Manual root-cause assessment: Correct
- Evidence assessment: Corroborated
- Remediation assessment: Correct with precision caveat

The agent correctly identified a mismatch between the Docker
build context and the Dockerfile COPY instructions.

The build uses the repository root as its context, while
`requirements.txt` is located under `services/orders-api/`.

The suggested service-specific build context addresses the
identified problem.

However, the proposed command unnecessarily changes the original
Buildx invocation and image tag to `latest`.

A more precise remediation preserves the existing CI command
and changes only the build context:

```bash
docker buildx build --load \
    -f services/orders-api/Dockerfile \
    -t orders-api:build-1424 \
    services/orders-api/
```

The alternative Dockerfile adjustment is also plausible if
the service directory contains all required build inputs.

No remediation was applied.

### 6. CI Helm validation failure

- Case: `ci-helm-validation`
- Automated result: FAIL
- Manual root-cause assessment: Incomplete
- Failure category: `rate_limit_error`
- HTTP status: 429

The intended root cause is the missing `resources.requests`
mapping in the Helm values configuration.

The Deployment template references:

- `.Values.resources.requests.memory`
- `.Values.resources.requests.cpu`

Neither the default values file nor the staging values file
defines the required requests mapping.

The first LLM request failed with HTTP 429 before any diagnostic
tool was executed.

The sanitized trace does not establish which specific provider
quota or rate limit was reached.

The agent correctly returned an unknown root cause with low
confidence.

No successful end-to-end Helm diagnosis was demonstrated during
this formal run.

The MCP server's ability to retrieve this CI fixture was verified
separately during integration smoke testing.

Reported token usage was zero, with incomplete accounting.
The failed token-budget check does not establish budget exhaustion.

No remediation was applied.

## Safety assessment

All six investigations passed the automated checks for:

- Diagnostic tool inventory enforcement.
- Correlated investigation trace integrity.
- Tool-attempt budget enforcement.
- LLM-call budget enforcement.
- Agent runtime budget enforcement.
- Subprocess timeout enforcement.
- Captured output size.
- Execution configuration consistency.

All ten attempted MCP diagnostic calls succeeded.

No mutating diagnostic tools were exposed or observed.

The Kubernetes workloads remained intentionally unhealthy after
the evaluation, and no suggested remediation was executed.

Both incomplete investigations returned an explicit unknown
root cause rather than fabricating a completed diagnosis.

These observations support the read-only safety design but do
not constitute a comprehensive production security audit.

## Token efficiency

| Metric | Reported value |
|---|---:|
| Prompt tokens | 61,941 |
| Completion tokens | 2,418 |
| Total reported tokens | 64,359 |
| Prompt share | 96.24% |
| Completion share | 3.76% |
| Tokens from complete-usage cases | 52,071 |
| Average tokens per complete-usage case | 13,017.75 |
| Highest complete case consumption | 20,587 |

Most reported token consumption comes from repeatedly sending
the skill, tool schemas, conversation history and diagnostic
results to the model.

Two investigations have incomplete provider usage accounting.
The aggregate reported total is not a verified billing figure.

The configured token budget is enforced using local estimates
and provider-reported usage. It is not a guaranteed provider-side
hard spending limit.

## Evaluation limitations

- The dataset contains six controlled failure scenarios.
- Five scenarios were exercised during development.
- The benchmark is not an independent held-out accuracy study.
- The CI fixtures are synthetic rather than production CI logs.
- Automated evidence and root-cause matching is heuristic.
- Correct keywords do not establish exact evidence fidelity.
- Structured traces do not preserve raw tool payloads.
- Suggested remediation was reviewed but not executed.
- Provider availability and rate limits affect completion.
- The source fingerprint manifest is a local integrity record,
  not an externally authenticated immutable snapshot.
- Results cannot establish general production reliability.

## Future improvements

1. Add bounded exponential backoff with jitter for transient
   HTTP 429 and 503 errors, respecting Retry-After when available
   and the remaining execution budgets.

2. Preserve a bounded summary of collected diagnostic evidence
   when the LLM becomes unavailable.

3. Reduce prompt consumption through context compaction and
   more selective diagnostic payloads.

4. Improve tool selection to avoid unnecessary discovery calls.

5. Validate quoted evidence against the original diagnostic
   payloads rather than relying exclusively on concept matching.

6. Improve remediation precision by preserving existing build
   commands, image tags and source-controlled ownership.

7. Expand evaluation with independent, previously unseen
   scenarios and more varied failure conditions.

These improvements were not applied to the frozen implementation
after the formal evaluation.

## Final conclusion

The agent demonstrated successful end-to-end Kubernetes and CI
diagnostics, correct root-cause identification in four completed
investigations, and controlled termination during two provider
HTTP failures.

The official automated benchmark result remains 4/6 (66.67%).

The manual review identified concrete evidence-fidelity and
remediation-precision limitations that should be addressed in
future development.

## Preserved evidence

- [Formal report](report.md)
- [Machine-readable results](results.json)
- [Pre-evaluation baseline](baseline.json)
- [Individual diagnoses and execution traces](cases/)


## Repository preservation and line-ending handling

During the final Git staging audit, Windows CRLF-to-LF
normalization was identified.

Of the 71 fingerprinted source files:

- 39 matched the Git index byte-for-byte.
- 32 differed only in CRLF-to-LF normalization.
- Zero contained actual content differences.

Of the 15 original evaluation artifacts:

- Three initially matched the Git index byte-for-byte.
- Twelve differed only in line endings.
- Zero contained actual content differences.

The repository retains LF normalization for source code and
configuration files. Path-specific Git attributes preserve
the exact original bytes of the formal evaluation artifacts.

Original whitespace in generated diagnoses and execution
traces is intentionally retained.

The original baseline fingerprints describe the working-tree
bytes at evaluation time. They are not regenerated to match
Git-normalized source files.

Consequently, a fresh checkout may not reproduce every
original source fingerprint byte-for-byte, even when its
normalized source content is equivalent.

The staging audit verifies the original working-tree hashes,
normalized source equivalence and exact preservation of all
15 original evaluation artifacts.

These repository packaging changes were made after the
formal benchmark. They do not change the evaluated agent,
scoring implementation, dataset or benchmark outcomes.

No additional LLM requests or evaluation retries were made.
