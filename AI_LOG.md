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