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


## Phase 5 — Automated Testing and Security Hardening

### Tasks Delegated to AI

AI assistance was used to design the automated testing strategy, generate pytest fixtures and test cases, review the MCP security boundaries, implement restricted kubeconfig validation, strengthen protocol argument validation and separate agent credentials from MCP configuration.

AI also assisted with regression commands, documentation and debugging integration failures.

### Human Execution and Verification

The developer implemented the proposed changes locally, reviewed configuration and source code, executed automated tests and inspected actual MCP protocol responses.

All reported test results were obtained from local command execution. No successful test outcomes were fabricated or inferred solely from generated code.

### Issues Identified and Corrected

**1. Credential validation before Kubernetes client initialization**

The initial Kubernetes client implementation loaded kubeconfig directly through the Kubernetes SDK before verifying the authenticated identity.

Review identified that unsupported authentication mechanisms could be processed before identity verification.

The implementation was changed to validate a restricted, token-only kubeconfig structure before passing a reconstructed configuration dictionary to the Kubernetes SDK.

Automated tests verified rejection of executable credential plugins, unsupported authentication fields, insecure TLS configuration, unauthorized namespaces and unexpected authenticated identities.

**2. Argument coercion at the MCP protocol boundary**

An isolated Pydantic experiment demonstrated that standard integer and boolean annotations accepted incorrectly typed values through automatic coercion.

Strict Pydantic types and explicit numeric constraints were introduced. The actual MCP protocol was then tested to confirm that malformed arguments were rejected before credential initialization.

**3. Namespace authorization order**

The previous lazy initialization flow could initialize the Kubernetes client before rejecting an unauthorized namespace.

Namespace authorization was moved ahead of credential loading and Kubernetes connectivity.

Protocol tests using a deliberately nonexistent kubeconfig verified that unauthorized namespace requests returned allowlist errors rather than credential initialization errors.

**4. Credential separation**

The MCP configuration loader previously read the same environment file used by the LLM agent.

Agent and MCP configuration were separated into `.env` and `.env.mcp`. A shared subprocess launcher was introduced to forward only explicitly supported MCP configuration variables.

The existing LLM API key and configuration values were preserved during migration without displaying credential values.

**5. Duplicate function definitions during integration**

During integration of the shared MCP launcher, obsolete `server_parameters()` implementations remained in both the smoke test and protocol validation test files.

Python syntax validation succeeded because duplicate function definitions are syntactically valid. However, the automated regression suite reported five failures, and Ruff reported eight linting errors.

The later obsolete function definitions replaced the new implementations at runtime and referenced imports that had already been removed.

The issue was corrected by removing the obsolete definitions while preserving the new shared launcher and existing test assertions.

The complete regression suite and live MCP integration tests subsequently passed.

This incident demonstrated why syntax validation alone is insufficient and why AI-assisted changes must be verified through linting, automated tests and integration testing.

### Verified Results

- 387 automated tests passed.
- One symbolic link test was skipped because symbolic link creation was unavailable in the Windows development environment.
- Zero automated test failures remained.
- Complete pytest execution time: 14.33 seconds.
- All 18 Python files in the linting scope passed formatting checks.
- Ruff linting passed.
- Dependency consistency checks passed.
- All five MCP tools remained operational through the official MCP protocol.
- CI diagnostics remained available without Kubernetes credentials.
- Local configuration and generated Kubernetes credentials remained excluded from Git.

### Remaining Limitations

Credential minimization is not complete process isolation. The MCP SDK may supply standard operating-system environment variables, and processes sharing the same OS identity may access the same filesystem.

SDK validation errors may echo invalid input values. Real diagnostic logs may contain sensitive information.

The skipped symbolic link test requires verification in an environment supporting symbolic link creation.

LLM diagnostic accuracy has not yet been evaluated. These results validate the diagnostic infrastructure and security controls, not the quality of future agent-generated diagnoses.


## Phase 6 — Diagnostic Skill and Deterministic CI Helper

### Tasks delegated to AI

- Drafting the Kubernetes and CI diagnostic Skill.
- Defining activation criteria, diagnostic branches, evidence requirements, safety instructions, and confidence levels.
- Optimizing the Skill to satisfy the assignment's line-count restriction.
- Refactoring CI failure extraction into a shared Python module.
- Designing the standalone CI extraction CLI.
- Generating structural Skill tests and standalone helper regression tests.
- Reviewing actual test failures and recommending corrections.

### Human implementation and verification

The generated files were reviewed and implemented locally using VS Code. Compilation, formatting, regression tests, standalone CLI tests, and live MCP integration checks were executed locally.

The shared extraction implementation was compared against the original MCP implementation before refactoring. All three CI fixtures and six additional edge cases produced identical results.

The MCP server was subsequently verified through the official MCP client to ensure the shared module remained accessible during standalone stdio execution.

### AI-generated issues and corrections

**1. Skill exceeded the assignment's line limit**

The initial AI-generated Skill contained 376 lines, exceeding the requirement of fewer than 300 lines.

The structural validation detected the violation. The Skill was rewritten to consolidate overlapping instructions while retaining the required diagnostic branches, safety rules, and output format.

The final Skill contains 228 lines and 1,599 words.

**2. Unnecessary lint suppression directives**

The AI initially recommended suppressing Ruff E402 for entry-point import-path initialization. The project's Ruff configuration did not enable E402, resulting in unused suppression errors.

The unnecessary directives were removed and import ordering was corrected without weakening the existing lint configuration.

**3. Windows newline handling in a regression test**

An AI-generated test initially failed because Python text-mode file writing converted LF line endings into CRLF on Windows, while the helper correctly preserved the original file content.

After reviewing the actual pytest failure, the test was corrected to write explicit UTF-8 bytes and parameterized to cover both LF and CRLF.

Both newline variants passed. The production extraction algorithm remained unchanged.

### Design decisions

The MCP server and offline helper share one deterministic extraction implementation rather than maintaining duplicate algorithms.

The offline helper is intentionally available to human operators only. It accepts an explicit local file path, whereas the agent must use the MCP tool with restricted fixture access.

The Skill is generic and does not embed evaluation answers or fixture-specific root causes.

Structural Skill validation and deterministic helper testing are kept separate from LLM behavioral evaluation to avoid overstating the demonstrated diagnostic accuracy.

### Verified results

- Skill size: 228 lines, below the mandatory 300-line limit.
- Skill structural tests: 22 passed.
- Standalone helper tests: 13 passed.
- Complete regression suite: 422 passed, 1 skipped.
- Regression suite execution time: 15.17 seconds.
- Ruff linting: all checks passed.
- Ruff formatting: 22 files correctly formatted.
- Live MCP integration: all checks passed.
- Dependency consistency: no broken requirements.
- CI extraction: 195 original source lines reduced to 97 selected lines across three fixtures.

The skipped test concerns symbolic-link creation restrictions on the Windows platform or account.

No LLM-based diagnostic success rate was measured during this phase. Agent integration and behavioral evaluation remain separate implementation phases.

## Phase 7 — Bounded AI Diagnostic Agent and Live Integration

### Tasks Delegated to AI

AI assistance was used extensively during the design and implementation of the diagnostic agent.

Delegated tasks included:

- Designing the agent architecture and separation of responsibilities.
- Implementing validated, environment-driven agent configuration.
- Implementing the official MCP client integration using stdio transport.
- Converting discovered MCP tool schemas into LLM-compatible function definitions.
- Implementing the asynchronous OpenAI-compatible LLM client.
- Preserving provider-specific tool-call metadata during conversation replay.
- Designing the bounded iterative investigation loop.
- Implementing tool allowlisting, argument validation, duplicate-call detection and execution budgets.
- Implementing structured JSON execution tracing.
- Implementing the command-line interface and client lifecycle management.
- Generating automated regression tests and integration verification commands.
- Reviewing live diagnostic outputs and identifying weaknesses in generated recommendations.
- Assisting with troubleshooting, documentation and implementation corrections.

The AI generated substantial portions of the implementation and test suite. The developer remained responsible for reviewing the proposed changes, applying them locally, executing verification commands and approving implementation decisions.

### Human Implementation and Verification

The developer implemented the proposed files locally using VS Code and executed all verification commands in the local Python virtual environment.

Verification included:

- Python dependency installation and consistency checks.
- Configuration validation using synthetic credentials and the actual local configuration.
- Automated tests using mocked LLM and MCP clients.
- Real MCP protocol communication through the official MCP SDK.
- Live Kubernetes diagnostics using the restricted ServiceAccount kubeconfig.
- Real Gemini API requests.
- Review of generated diagnoses against known workload failures and CI fixture contents.
- Inspection of structured execution traces and reported token usage.
- Verification of CLI exit codes and incomplete investigation behavior.
- Ruff linting, formatting and strict pytest warning validation.

The developer reviewed actual execution results before progressing to subsequent implementation steps.

### Architecture and Design Decisions

**Custom bounded agent loop**

A custom iterative agent loop was selected instead of a larger agent orchestration framework.

This provides explicit control over tool execution, validation, token accounting, termination conditions, error handling and observability while keeping the implementation understandable and reviewable.

The agent communicates with the MCP server through the official MCP protocol over stdio. It does not import or directly execute the server's diagnostic tool implementations.

**Provider compatibility**

The OpenAI-compatible Python SDK was retained, with the Gemini API configured through environment variables.

The selected development model is `gemini-3.5-flash-lite`. Both the provider endpoint and model identifier remain configurable.

Provider-specific metadata is preserved when replaying assistant messages, including Gemini thought signatures attached to tool calls.

**Defense in depth**

Security enforcement does not depend exclusively on the diagnostic Skill or model instructions.

The agent validates discovered tools against an explicit inventory of five diagnostic tools, validates requested arguments against their schemas, rejects unsupported tool requests and prevents identical repeated tool invocations.

The MCP server independently validates requests and enforces namespace restrictions and bounded diagnostic responses.

Kubernetes authorization is additionally enforced by the dedicated ServiceAccount and namespace-scoped RBAC.

The agent has no registered remediation, shell execution or Kubernetes mutation tools.

**Execution budgets**

Investigations are bounded by configurable limits:

| Configuration | Default |
|---|---:|
| Maximum tool attempts | 10 |
| Maximum LLM requests | 12 |
| Investigation token budget | 30,000 |
| Maximum output tokens per LLM request | 2,048 |
| LLM request timeout | 60 seconds |
| MCP request timeout | 45 seconds |
| Investigation runtime budget | 300 seconds |

The token budget combines provider-reported token consumption with a conservative pre-request prompt-size estimate.

The estimate is not an exact provider tokenizer and does not constitute a guaranteed billing limit. Failed requests may also consume tokens without returning usage metadata.

The agent marks token accounting as incomplete when reliable provider usage information is unavailable.

**Structured observability**

Structured JSON execution tracing was implemented as an optional assignment enhancement.

Trace events include investigation identifiers, tool names, predefined diagnostic purposes, execution durations, request outcomes, token accounting, budget configuration and termination reasons.

The trace intentionally excludes raw prompts, tool arguments, diagnostic payloads, API keys and provider exception messages.

Trace purposes describe the intended diagnostic function of each tool rather than exposing private model reasoning.

The structured agent trace is emitted to standard error, while the diagnosis is emitted to standard output. MCP subprocess messages may also appear on standard error and are not necessarily structured JSON.

### Issues Identified and Corrected

**1. Unexpected provider tool requests during finalization**

Earlier function-calling validation demonstrated that the model could request additional tools despite receiving `tool_choice="none"`.

The agent implementation therefore uses explicit finalization instructions and omits tool definitions entirely when performing a tool-free finalization request.

The agent also validates unexpected tool requests and does not execute tools outside its registered inventory.

Regression tests verify that tool-free finalization omits both the `tools` and `tool_choice` request parameters.

This behavior was verified with the selected Gemini model. It is not a guarantee that every compatible provider or future model version will behave identically.

**2. Provider-specific conversation metadata**

The implementation preserves the complete serialized assistant message when replaying conversation history.

This avoids discarding provider-specific metadata, including Gemini thought signatures associated with function calls.

Automated tests verify metadata preservation across the tool-calling and finalization sequence.

**3. Test implementation and integration issues**

During agent development, the AI-generated test suite required several corrections.

These included Windows newline handling, malformed SDK model serialization warnings, duplicated test helper logic and Ruff violations associated with test organization.

Shared test helpers were consolidated, malformed response validation was moved ahead of serialization, and platform-dependent test assumptions were corrected.

The complete regression suite was subsequently executed with warnings treated as errors.

**4. Live LLM provider failures**

The initial live investigation of `payments-api` successfully collected Kubernetes evidence through MCP but failed during a subsequent LLM request.

A controlled manual retry completed the investigation successfully.

A later `orders-api` investigation returned HTTP 503 after successfully collecting diagnostic evidence.

The original provider error handling exposed a generic failure category, which made troubleshooting unnecessarily difficult.

The LLM client and structured trace implementation were enhanced to preserve sanitized error categories and validated HTTP status codes.

Provider error categories now distinguish authentication failures, rate limits, timeouts, connection failures, HTTP errors and invalid responses.

Raw provider exception messages are not included in the structured trace.

The agent does not automatically retry failed provider requests. This avoids hidden request amplification and unpredictable additional token consumption.

Manual retries performed during development were recorded as separate investigation attempts.

**5. Token budget exhaustion**

The initial default investigation budget was 20,000 tokens.

During live investigation of `orders-api`, the agent successfully invoked three diagnostic tools but stopped because the estimated remaining token budget was insufficient for another model request.

The provider had reported 13,441 consumed tokens at that point.

The difference between reported consumption and the configured budget was not necessarily sufficient for another request because conversation history, the diagnostic Skill, tool definitions and collected evidence contribute to subsequent prompt size.

A temporary 30,000-token budget was tested.

After an unrelated HTTP 503 provider failure and a controlled retry, the investigation completed successfully with 19,435 reported tokens.

The `analytics-worker` investigation also completed under the increased budget.

Based on these observations, the default token budget was increased from 20,000 to 30,000 in the agent configuration and public environment template.

The private local configuration was updated without displaying or modifying the API key.

Environment-variable overrides remain supported. The tool-attempt, LLM-request, output-token and runtime limits were retained.

The selected budget is an empirical development default, not a guarantee that all future investigations will complete within it.

**6. Windows CLI output encoding**

A failed investigation exposed a Windows output encoding issue when the diagnosis was redirected to a file.

The Unicode em dash in the incomplete diagnosis was not preserved correctly under the active Windows encoding.

The CLI was updated to configure standard output and standard error explicitly as UTF-8 when the streams support reconfiguration.

A safe error-handling mode was also configured for output encoding.

The correction was verified through redirected output and automated regression tests.

**7. Remediation recommendation quality**

An early successful `payments-api` investigation correctly identified the invalid container image tag but recommended using `nginx:latest`.

Although this could resolve the immediate image-pull failure, it is not an appropriate default recommendation for reproducible deployment management.

The diagnostic Skill was strengthened to:

- Prefer source-controlled declarative configuration changes.
- Avoid recommending mutable `latest` image tags.
- Require verified image versions or digests where possible.
- Distinguish observed evidence from inferred root causes.
- Use placeholders for unavailable Secret names and configuration values.
- Avoid inventing credentials or unsupported application requirements.
- Maintain consistency between Kubernetes resource requests and limits.
- Prefer changes to the owning workload rather than individual generated pods.
- Include read-only verification suggestions.
- Preserve the meaning of quoted diagnostic evidence.

The updated Skill contains 251 lines and remains below the assignment's mandatory 300-line limit.

The Skill improvements guide model behavior but do not guarantee that every generated recommendation will satisfy all requirements.

### Live Integration Demonstrations

Live integration testing used the actual Gemini API, the official MCP client, the MCP diagnostic server and the restricted Kubernetes environment.

The following table records all eight live investigation attempts conducted during this phase.

| Scenario | Token budget | Outcome | Reported tokens |
|---|---:|---|---:|
| CI build-1423 | 20,000 | Completed | 7,917 |
| payments-api | 20,000 | Provider failure | 7,311* |
| payments-api retry | 20,000 | Completed | 12,452 |
| orders-api | 20,000 | Estimated token budget exhausted | 13,441 |
| orders-api | 30,000 | HTTP 503 provider failure | 19,141* |
| orders-api retry | 30,000 | Completed | 19,435 |
| analytics-worker | 30,000 | Completed | 17,986 |
| CI build-1424 natural-language query | 30,000 | Completed | 8,546 |

\* Token accounting was incomplete because the failed provider request did not return usage information.

#### Successfully demonstrated root causes

| Scenario | Observed diagnosis |
|---|---|
| payments-api | ImagePullBackOff caused by an invalid container image tag. |
| orders-api | Repeated container failure caused by the missing `DATABASE_URL` environment variable. |
| analytics-worker | Pending workload caused by an unsatisfiable CPU request of 100 CPU cores. |
| CI build-1423 | Application validation defect allowing negative payment amounts. |
| CI build-1424 | Incorrect Docker build context preventing access to `requirements.txt`. |

The Kubernetes investigations collected evidence from the live cluster. The CI investigations used synthetic but realistic failure fixtures.

All three mandatory Kubernetes scenarios and at least one CI scenario were successfully demonstrated.

Both explicit CLI investigation modes and natural-language input were exercised.

#### Integration completion statistics

- Distinct scenarios successfully demonstrated: 5 of 5.
- Total investigation attempts: 8.
- Completed investigations: 5.
- Incomplete investigations: 3.
- First-attempt completion: 3 of 5 scenarios (60%).
- Overall attempt completion: 5 of 8 attempts (62.5%).
- Total reported token usage across successful investigations: 66,336.
- Mean reported token usage across successful investigations: 13,267.2 tokens.

These statistics describe development integration attempts, not formal diagnostic accuracy.

The attempts used different token budgets and included implementation and Skill changes between runs. Successful retries were not substituted for unsuccessful attempts.

Formal evaluation will be performed separately using predefined expected root causes and a consistent agent configuration.

#### Manual review of diagnosis quality

The completed investigations identified the intended root causes during manual review.

However, completion does not imply that every generated recommendation was optimal.

Observed weaknesses included:

- An early recommendation to use a mutable image tag.
- Illustrative payment validation code that did not fully establish the application's intended handling of zero-valued payments.
- Kubernetes remediation examples containing unnecessary configuration or assumptions about existing Secrets.
- Resource recommendations that require workload-specific sizing before production use.
- A Docker build-context diagnosis that identified the correct cause but did not provide the complete corrected build command.

These observations will inform the formal evaluation criteria and future improvements.

Exact evidence quotation fidelity was not independently audited for every generated response during these integration demonstrations.

No suggested remediation was executed by the agent.

### Automated Regression Hardening

Following live integration testing, additional regression cases were introduced to cover the newly identified failure modes.

The additional coverage focused on:

- Sanitized LLM error categories.
- HTTP status metadata validation.
- Provider failure trace events.
- Incomplete token accounting.
- Rejection of unsupported error metadata.
- UTF-8 output configuration.
- Compatibility with output streams that do not support reconfiguration.

The existing test coverage was preserved.

The default token budget was also verified through configuration regression tests, including environment-variable override behavior.

### Verified Results

| Verification | Observed result |
|---|---|
| Configuration regression tests | 62 passed |
| Targeted regression tests | 275 passed |
| Complete agent test suite | 479 passed |
| Complete project regression suite | 901 passed, 1 skipped |
| Additional hardening test cases | 43 |
| Complete regression execution time | 20.70 seconds |
| Strict pytest warning validation | Passed |
| Ruff linting | Passed |
| Ruff formatting | 39 files compliant |
| Python dependency consistency | No broken requirements |
| Git whitespace validation | Passed |
| Live MCP integration | Passed |
| Private `.env` Git exclusion | Verified |

The single skipped test concerns symbolic-link creation, which is unavailable on the current Windows platform or account.

This is a previously documented environment limitation rather than a newly introduced regression.

The actual symbolic-link test remains to be verified in an environment that supports symbolic-link creation.

All reported results were obtained from locally executed commands and observed outputs.

### Remaining Limitations

- LLM output remains nondeterministic, and provider availability can affect investigation completion.
- Prompt token estimation is approximate and cannot guarantee an exact monetary spending limit.
- Provider failures may leave token accounting incomplete.
- Structural validation of the diagnosis does not establish factual correctness.
- A successful CLI exit code does not independently prove that the root cause or remediation is correct.
- The agent does not independently validate every quoted evidence line against the original diagnostic payload.
- The Skill cannot guarantee that every generated remediation recommendation follows all instructions.
- Diagnostic logs and events may contain sensitive information. Structured trace minimization does not constitute complete diagnostic data redaction.
- MCP credential minimization does not provide complete operating-system process isolation.
- The real symbolic-link test remains unverified on the current Windows environment.
- Containerized agent execution and clean-machine end-to-end reproducibility remain to be verified.
- Formal behavioral evaluation has not yet been completed.

### Next Steps

The next implementation phase will introduce a reproducible evaluation harness with predefined expected root causes, consistent configuration, recorded investigation outcomes and transparent pass-rate reporting.

Evaluation answers must remain separate from the agent's runtime context.

Failed investigations, incorrect diagnoses and incomplete results must remain visible in the evaluation report.

Subsequent work will address containerized execution, final documentation and end-to-end reproducibility verification.