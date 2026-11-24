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