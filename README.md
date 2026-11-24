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