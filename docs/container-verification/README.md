# Container Deployment Verification

## Purpose

This directory preserves the original outputs of three separate container deployment verification attempts conducted on November 25, 2026.

These attempts verify Docker packaging, runtime configuration, MCP integration, restricted Kubernetes connectivity, live LLM communication, and controlled failure handling.

They are not part of the formal six-case evaluation benchmark.

## Results

| Attempt | Target | Result | LLM requests | Successful MCP calls | Wall time |
|---|---|---|---:|---:|---:|
| 1 | analytics-worker | Configuration failure | 0 | 0 | 4s |
| 2 | analytics-worker | Provider HTTP 503 | 3 | 2 | 19s |
| 3 | build-1424 | Completed diagnosis | 2 | 1 | 17s |

All three attempts are retained. No automatic retries were performed.

The formal evaluation remains unchanged at 4/6 successful cases (66.67%).

## Attempt 1 — Configuration Failure

The original Docker launcher used Docker's `--env-file` option.

The private dotenv configuration was accepted by the host's Python configuration loader but rejected inside the container because Docker preserved additional whitespace in the API key.

The agent terminated before starting an investigation.

No MCP calls or LLM requests were executed.

### Corrective action

The launcher was redesigned to use the existing Python dotenv parser and strict configuration validator before starting Docker.

Only eleven approved agent configuration variables are explicitly forwarded, together with fixed MCP runtime settings.

Secret values are inherited through the Docker subprocess environment rather than embedded in command-line arguments.

The original private dotenv file was not modified.

Offline regression tests confirmed consistent parsing of trailing whitespace, quoted values, defaults, and unrelated configuration exclusion.

## Attempt 2 — Provider Failure

The corrected launcher successfully initialized the agent, loaded the Skill, established an MCP stdio session, authenticated with the LLM provider, and executed two Kubernetes diagnostic tools:

- `list_pods`
- `describe_pod`

The third LLM request returned HTTP 503.

The investigation terminated with an incomplete diagnosis and low confidence. No remediation was executed.

Reported token usage was 7,807 tokens, with incomplete usage accounting because the failed provider request did not return complete usage information.

Investigation duration was 13.704 seconds.

This attempt demonstrates containerized Kubernetes diagnostic integration and controlled failure handling, but not a completed Kubernetes root-cause diagnosis.

## Attempt 3 — Successful CI Diagnosis

The agent investigated CI fixture `build-1424`.

It retrieved the failure evidence through `get_ci_log` and correctly identified a mismatch between the Docker build context and the location of `requirements.txt`.

The investigation completed successfully using:

- Two LLM requests.
- One successful MCP tool call.
- 8,597 reported tokens with complete usage accounting.
- 11.748 seconds of investigation runtime.
- A successful process exit.

### Manual review

The diagnosis correctly identified the failed COPY instruction, missing file, actual dependency file location, and build-context mismatch.

The proposed Dockerfile changes are a reasonable alternative when retaining the repository root as the build context.

The preferred minimal remediation is to preserve the original Buildx command and change its build context to the service directory:

```bash
docker buildx build --load \
    -f services/orders-api/Dockerfile \
    -t orders-api:build-1424 \
    services/orders-api/
```

The generated diagnosis could be improved by identifying the incorrect context more definitively, including the complete corrected build command, and preserving the exact formatting of quoted log evidence.

No remediation was executed.

## Container Security Verification

Separate offline and MCP integration checks verified:

- Non-root execution using UID and GID 10001.
- Read-only container root filesystem.
- Dropped Linux capabilities.
- No-new-privileges enforcement.
- Writable temporary filesystem.
- Memory, CPU, and process limits.
- Restricted ServiceAccount credentials mounted read-only.
- TLS verification enabled.
- Five discovered read-only MCP tools.
- Fourteen successful diagnostic checks.
- Eight rejected invalid or unauthorized requests.
- Continued MCP session availability after rejected requests.

The containerized MCP integration verification required no LLM requests.

## Evidence Integrity

Each attempt contains its original diagnosis, execution trace, Make exit code, and wall-clock duration.

The accompanying `manifest.json` records artifact sizes and SHA-256 fingerprints.

The original files were copied byte-for-byte. Git attributes preserve their original line endings.

Make exit codes are recorded separately from agent exit codes because GNU Make can return its own nonzero status when an underlying recipe fails.

The evidence was checked for exact matches against the current LLM API key and restricted Kubernetes tokens before preservation. This is not an exhaustive historical secret scan.

## Limitations

- Provider availability remains outside the application's control.
- The agent does not automatically retry failed provider requests.
- Incomplete diagnoses do not currently preserve all previously collected diagnostic evidence.
- The successful complete containerized investigation was a CI case, not a Kubernetes case.
- Runtime environment variables remain accessible to sufficiently privileged Docker daemon administrators.
- Native Linux installations may require appropriate secure read permissions for the mounted kubeconfig and fixed container UID.
- These deployment attempts are development verification evidence, not an independent or statistically representative evaluation dataset.