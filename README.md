# DevOps AI Triage Toolkit

An AI-powered, read-only troubleshooting agent for Kubernetes
workloads and CI/CD pipeline failures.

## Project Objectives

- Provide secure infrastructure access through an MCP server.
- Investigate Kubernetes workload failures using real evidence.
- Analyze failed CI/CD pipeline logs.
- Apply a structured troubleshooting skill.
- Generate actionable remediation recommendations.
- Enforce least-privilege access and bounded agent execution.

## Technology Stack

- Python 3.12
- Google Gemini
- OpenAI-compatible Python SDK
- Model Context Protocol (MCP)
- Kubernetes (kind)
- Docker
- Kubernetes RBAC
- pytest
- Makefile and Bash

## Security Principles

- Read-only infrastructure access.
- Dedicated Kubernetes ServiceAccount.
- Least-privilege RBAC.
- Configurable namespace allowlist.
- Bounded tool output and agent execution.
- No automatic remediation.
- No committed credentials.

## Project Status

Under development.


## Local Kubernetes Environment

The project uses a single-node kind cluster with a pinned Kubernetes node image and three intentionally broken workloads deployed in the `staging` namespace.

### Environment Management

| Command | Description |
|---|---|
| `make env` | Create or reconcile the Kubernetes environment |
| `make kubeconfig` | Refresh temporary ServiceAccount credentials |
| `make clean` | Delete the local kind cluster and default generated kubeconfig |
| `make help` | Display available commands |

### Failure Scenarios

| Workload | Expected Symptom | Intended Root Cause |
|---|---|---|
| payments-api | ImagePullBackOff | Nonexistent container image tag |
| orders-api | CrashLoopBackOff | Missing DATABASE_URL environment variable |
| analytics-worker | Pending | CPU request exceeds available node capacity |

The workloads are intentionally unhealthy and should not be repaired during normal evaluation.

### Security Model

The MCP server will authenticate using a dedicated ServiceAccount named `triage-reader`.

The custom namespace-scoped Role grants:

- `get` and `list` on pods.
- `get` on pod logs.
- `list` on events.

Administrator credentials are used only for environment provisioning and temporary credential generation.

The restricted kubeconfig is generated locally at `.runtime/kubeconfig` and excluded from version control.

### Infrastructure Validation

| Validation | Result |
|---|---|
| Fresh-cluster provisioning | 47.293 seconds |
| Automated authorization checks | 20/20 passed |
| Reproduced workload root causes | 3/3 |
| Setup idempotency | Verified |
| Cross-namespace isolation | Verified |
| Secret access denial | Verified |
| Environment cleanup | Verified |

Provisioning was measured with a cached kind node image. Workload failure stabilization and complete agent execution are not included in this measurement.

## MCP Diagnostic Server

The project implements a read-only Model Context Protocol (MCP) server using the official Python MCP SDK and FastMCP.

The server communicates with independent MCP clients through JSON-RPC over stdio. Kubernetes operations use the official Kubernetes Python client rather than shelling out to kubectl.

### Available Tools

| Tool | Purpose |
|---|---|
| `list_pods` | Discover workloads, readiness, restart counts and container states |
| `describe_pod` | Inspect pod conditions, resource configuration, termination states and recent events |
| `get_pod_logs` | Retrieve bounded current or previous container logs |
| `list_events` | Retrieve recent Kubernetes events with optional resource filtering |
| `get_ci_log` | Retrieve CI fixture logs or relevant failure sections |

### Installation

With the Python 3.12 virtual environment activated:

```bash
python -m pip install -r mcp-server/requirements.txt
```

For development and automated testing:

```bash
python -m pip install -r mcp-server/requirements-dev.txt
```

### Running the Server

```bash
make env
make mcp
```

The MCP server uses stdio transport and is intended to be launched by an MCP client. It does not expose an HTTP endpoint.

A compatible MCP client can launch the server using the Python interpreter from the project's virtual environment and the absolute path to `mcp-server/server.py`.

### Security Controls

- Dedicated Kubernetes ServiceAccount with namespace-scoped, read-only RBAC.
- Explicit restricted kubeconfig and authenticated ServiceAccount identity verification.
- Configurable namespace allowlist, defaulting to `staging`.
- No workload mutation, container execution or direct Kubernetes Secret retrieval tools.
- CI job identifier validation and fixture directory containment checks.
- Bounded Kubernetes requests, log retrieval and serialized diagnostic payloads.
- Sanitized application-level errors.
- Read-only MCP tool annotations.
- Diagnostic logging separated from stdout protocol communication.

Read-only annotations communicate tool behavior to clients but are not an authorization mechanism. Authorization is enforced through application validation and Kubernetes RBAC.

### Default Safety Limits

| Setting | Default |
|---|---|
| Allowed namespaces | staging |
| Default container log tail | 100 lines |
| Maximum container log tail | 500 lines |
| Maximum returned pods | 100 |
| Maximum returned events | 50 |
| Maximum scanned events | 1,000 |
| Maximum serialized diagnostic payload | 32 KiB |
| Maximum CI fixture size | 1 MiB |
| Kubernetes request timeout | 10 seconds |

The serialized payload limit applies to application diagnostic data, not the complete MCP protocol envelope.

### Integration Verification

Run the reusable MCP integration test:

```bash
make mcp-smoke
```

The test launches the MCP server as a separate subprocess and communicates through the official MCP client SDK.

Verified behavior:

- MCP protocol initialization using protocol version `2025-11-25`.
- Discovery and invocation of all five registered tools.
- Live inspection of three intentionally unhealthy Kubernetes workloads.
- Retrieval of application configuration and scheduling failure evidence.
- Retrieval of all three synthetic CI failure fixtures.
- Rejection of eight unauthorized or invalid requests.
- CI diagnostics remain available when Kubernetes credentials are missing.
- Successful closure of both MCP client sessions.

The integration test does not require an LLM API key or invoke an external LLM.

### CI Failure Extraction

CI failure extraction uses deterministic regular expressions and surrounding context windows. Overlapping sections are merged to reduce redundant evidence.

Observed results:

| CI fixture | Original lines | Selected lines |
|---|---:|---:|
| build-1423 | 52 | 29 |
| build-1424 | 77 | 33 |
| build-1425 | 66 | 35 |
| Total | 195 | 97 |

The extraction reduced the number of selected log lines by approximately 50.3% while retaining the expected failure markers in all three fixtures.

A separate truncation test produced an 810-byte serialized response under a configured 1,024-byte limit while preserving the final diagnostic evidence.

These measurements describe synthetic fixture processing, not measured LLM token or monetary savings.

### Current Limitations

- Failure extraction is heuristic and may miss unfamiliar CI error formats.
- Kubernetes events and container logs are dynamic and may become unavailable.
- Large diagnostic responses may contain incomplete evidence.
- Kubernetes logs and events may contain sensitive or untrusted content.
- Kubeconfig pre-validation and stricter MCP boundary validation require additional hardening.
- MCP client session closure has been verified, but server-side cleanup execution has not yet been independently confirmed.
- The AI agent, triage skill and formal automated test suite are not yet implemented.
