# AI Usage Log

## 2026-11-24 — Environment setup and API validation

### AI assistance
- Proposed the initial architecture and technology stack.
- Assisted with environment verification and dependency selection.
- Generated an initial Gemini API connectivity diagnostic.

### Issues identified during manual execution
- The generated diagnostic used implicit `load_dotenv()`
  discovery while executing Python through standard input.
- This caused an AssertionError before the API request.

### Correction
- Identified the failure from the Python traceback.
- Replaced implicit discovery with an explicit `.env` path.
- Added configuration file and required-variable validation.

### Verification
- Dependencies installed successfully.
- No broken Python requirements.
- Confirmed that `.env` is excluded from Git.
- Corrected API diagnostic pending verification.

## 2026-11-24 — LLM provider troubleshooting

### Initial issue
- Gemini API authentication and model discovery succeeded.
- AI initially recommended gemini-2.5-flash.
- Text generation returned HTTP 404.
- Alternative model identifiers did not resolve the issue.
- gemini-3.5-flash requests timed out.

### Troubleshooting
- Tested the native Gemini REST API independently
  of the OpenAI SDK.
- Confirmed that gemini-2.5-flash is no longer
  available to new users.
- Tested gemini-3.5-flash-lite as an alternative.

### Verified results
- HTTP status: 200
- Expected response: API_TEST_OK
- Actual response: API_TEST_OK
- Response time: 1.12 seconds
- Total token usage: 14

### Design decision
- Keep model selection configurable through
  environment variables.
- Select gemini-3.5-flash-lite as the initial candidate.
- Validate OpenAI compatibility and function calling
  before finalizing the LLM provider implementation.

## 2026-11-24 — Function-calling validation

### Verified capabilities
- OpenAI-compatible text generation succeeded.
- Gemini autonomously selected the list_pods tool.
- Generated the correct namespace argument.
- Mock tool execution completed successfully.
- The second API request was accepted.
- Token usage was reported for both requests.

### Issue identified
- The second model response contained no visible diagnosis.
- The automated function-calling acceptance test failed.
- Total token consumption was 343 tokens.

### Next action
- Inspect the complete response object and finish reason.
- Determine whether the issue is related to model behavior,
  response parsing or provider compatibility.

## 2026-11-24 — Unexpected LLM tool behavior

### Findings
- The second LLM response was not empty due to
  a response parsing error.
- The model returned finish_reason=tool_calls.
- Gemini requested an unregistered get_pod_logs tool.
- This occurred despite tool_choice="none".

### AI implementation limitations
- The initial AI-generated diagnostic assumed that
  two model calls would complete the investigation.
- The model attempted additional investigation
  instead of returning a final diagnosis.

### Engineering lessons
- Validate every requested tool against the
  registered tool inventory.
- Validate tool arguments before execution.
- Never rely solely on LLM instructions for
  security enforcement.
- Implement a bounded iterative agent loop.
- Explicitly handle unexpected tool requests.
- Preserve provider-specific tool-call metadata
  when replaying conversation history.

### Proposed correction
- Explicitly instruct the model to finalize.
- Omit tool definitions from the final request.
- Verify that the model returns an evidence-based
  textual diagnosis.

## 2026-11-24 — Successful LLM function-calling validation

### Correction
- Added explicit finalization instructions after tool execution.
- Removed tool definitions from the final model request.
- Configured explicit output token limits.
- Preserved provider-specific tool-call metadata.

### Verified results
- Model: gemini-3.5-flash-lite
- Autonomous tool selection: PASS
- Correct tool arguments: PASS
- Tool result processing: PASS
- Final text generation: PASS
- Symptom identification: PASS
- Total token consumption: 444
- Final finish reason: stop

### Manual review
- Correctly identified ImagePullBackOff.
- Correctly acknowledged that the exact root cause was unknown.
- Did not request additional tools during finalization.
- Confidence in the symptom should be distinguished from
  confidence in the root cause.
- Evidence was simulated, not collected from a live cluster.

### Final design decision
- Retain the OpenAI-compatible Python SDK.
- Keep model selection configurable.
- Implement a bounded iterative agent loop.
- Enforce tool validation at the application level.
- Use explicit finalization when investigation ends.

### Limitations
- This was a mocked function-calling smoke test.
- Real MCP integration and Kubernetes access remain untested.
- End-to-end diagnostic accuracy remains unverified.
- The individual cause of the previous unexpected tool
  behavior was not isolated.


## Phase 2 — Kubernetes Environment and Security

### AI-assisted tasks

- Designed the local Kubernetes environment using kind.
- Generated declarative Kubernetes manifests for three intentionally broken workloads.
- Designed namespace-scoped RBAC using a dedicated ServiceAccount, Role, and RoleBinding.
- Implemented Bash scripts for environment provisioning, restricted kubeconfig generation, and cleanup.
- Implemented Makefile targets for environment management.
- Suggested security validation and reproducibility tests.

### Manual execution and verification

- Created and inspected the kind cluster locally.
- Verified the Kubernetes node image and pinned its digest.
- Applied Kubernetes manifests and inspected actual pod states, logs, and events.
- Verified the root causes of all three intentionally broken workloads.
- Tested RBAC permissions through ServiceAccount impersonation.
- Generated temporary ServiceAccount credentials and independently verified authentication using the restricted kubeconfig.
- Confirmed that unauthorized Kubernetes operations were denied.
- Verified that generated credentials were excluded from Git.
- Executed the setup script repeatedly to verify idempotency.
- Deleted and recreated the environment to validate reproducibility.

### AI-generated issues and corrections

1. The initial setup script treated unsuccessful authorization commands as successful permission denials. This could incorrectly accept authentication or connectivity failures. The implementation was corrected to validate both the authorization response and its exit status.

2. An initial verification command suggested using `kubectl get pods -w` with the restricted ServiceAccount. The ServiceAccount intentionally does not have watch permissions. The verification procedure was corrected to use bounded polling instead of expanding RBAC permissions.

3. The credential generation script uses Unix-style file permission controls. During Windows testing, Git Bash displayed the generated kubeconfig with broader permissions than expected. Git exclusion was verified, but equivalent NTFS access restrictions were not independently validated.

### Observed Kubernetes behavior

- Pod phase alone is insufficient for diagnosing container health.
- A repeatedly crashing container may alternate between Error and CrashLoopBackOff.
- Previous container logs may be unavailable even when current logs contain sufficient diagnostic evidence.
- Kubernetes scheduling events provide useful evidence for diagnosing unscheduled pods.

These observations will inform the MCP server implementation and troubleshooting skill.

### Verified results

- All three intended workload root causes were reproduced.
- All 20 automated authorization checks passed.
- Actual API requests for Secrets and pods in unauthorized namespaces were rejected.
- Environment cleanup preserved unrelated Docker containers and local configuration.
- Fresh-cluster infrastructure provisioning completed in 47.293 seconds.

The measured provisioning time was obtained on a development machine with a previously downloaded kind node image. It does not represent a completely cold installation or the complete AI agent demonstration.

## Phase 3 — CI/CD Failure Fixtures

### AI-assisted tasks

- Generated three synthetic CI/CD failure logs representing
  application testing, Docker build configuration, and Helm
  deployment validation failures.
- Designed fixtures containing realistic diagnostic evidence
  and pipeline stage information.

### Manual execution and verification

- Created and inspected all three fixture files.
- Verified job identifiers, failure messages, file encoding,
  and failed job conclusions.
- Normalized fixture line endings to LF.

### AI-generated issues and corrections

- The initial Helm fixture reported a missing CPU value,
  although the preceding memory expression would fail first.
  The reported error was corrected to match the template.

### Limitations

The fixtures are synthetic and were not collected from actual
CI/CD pipeline executions. They provide controlled,
reproducible inputs for evaluating the triage agent.

Expected diagnoses will be maintained separately from the
agent's runtime context to avoid evaluation answer leakage.

## Phase 4 — MCP Diagnostic Server Implementation

### Tasks Delegated to AI

- Proposed the MCP server architecture and separation of responsibilities.
- Designed the five diagnostic tool contracts.
- Generated initial configuration and input validation implementations.
- Implemented Kubernetes diagnostic operations using the official Python client.
- Implemented deterministic CI failure extraction and bounded fixture retrieval.
- Implemented FastMCP tool registration, descriptions, annotations and error handling.
- Generated a reusable MCP protocol integration test.
- Assisted with troubleshooting, code quality checks and documentation.

### Human Execution and Verification

- Installed and verified the required Python dependencies.
- Confirmed SDK imports and supported function signatures.
- Executed Kubernetes operations against the live kind cluster using restricted credentials.
- Verified namespace isolation and Kubernetes RBAC behavior.
- Executed configuration, safety and CI diagnostic smoke tests.
- Applied Ruff corrections and formatting.
- Executed the real MCP integration test and subsequent regression test.
- Reviewed actual command outputs before progressing.

### AI-Generated Issues and Corrections

**Datetime compatibility and exception handling**

The initial Kubernetes implementation used `timezone.utc` and broad exception handling. Ruff identified modernization and exception-handling violations.

The implementation was corrected to use `datetime.UTC`, specific expected exceptions and a `finally` block to release partially initialized Kubernetes clients.

An intentional broad exception boundary remains in the MCP server to prevent unexpected internal errors from being exposed to clients.

**Nested asynchronous context managers**

The generated MCP smoke test initially used nested asynchronous context managers. Ruff reported two SIM117 violations.

Both were corrected, and the complete integration test was executed again successfully.

**Pod phase interpretation**

Live verification demonstrated that a crashing workload may report the Kubernetes pod phase as `Running` while its container is unhealthy.

The diagnostic implementation therefore exposes container states, readiness, restart counts and previous termination information instead of relying exclusively on pod phase.

### Observed Verification Results

- Configuration and safety smoke tests: 45/45 passed.
- Live Kubernetes diagnostic operations: passed.
- CI diagnostic smoke tests: passed.
- MCP tool discovery: 5/5 tools.
- MCP invocation: all five tools successfully invoked.
- Invalid MCP requests: 8/8 rejected.
- CI availability without Kubernetes credentials: passed.
- MCP integration regression test: passed.
- Python syntax, Ruff linting, formatting and dependency checks: passed.

CI failure extraction selected 97 of 195 original fixture lines, approximately a 50.3% reduction, while preserving the expected failure markers.

The response truncation test returned an 810-byte serialized payload under a configured 1,024-byte limit.

### Remaining Limitations and Follow-Up

- Formal pytest coverage is required for safety controls and failure paths.
- Kubeconfig contents should be validated before SDK credential loading.
- MCP input coercion and schema constraints require additional testing.
- LLM credentials should be further isolated from the MCP server.
- Server-side cleanup execution requires independent verification.
- Logs and events must be treated as untrusted diagnostic data.
- No LLM diagnosis or agent evaluation has been performed during this phase.

All reported results are based on locally executed commands and observed outputs. No agent evaluation results have been fabricated.
