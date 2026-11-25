
# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.12-slim

# --------------------------------------------------
# Stage 1: Install runtime dependencies
# --------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}"

COPY agent/requirements.txt ./agent-requirements.txt
COPY mcp-server/requirements.txt ./mcp-requirements.txt

RUN python -m pip install \
        --requirement agent-requirements.txt \
        --requirement mcp-requirements.txt \
    && python -m pip check


# --------------------------------------------------
# Stage 2: Minimal application runtime
# --------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="DevOps AI Triage Toolkit" \
      org.opencontainers.image.description="Read-only Kubernetes and CI diagnostics using an LLM, MCP and a triage skill"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/triage

RUN groupadd --gid 10001 triage \
    && useradd \
        --uid 10001 \
        --gid 10001 \
        --create-home \
        --shell /usr/sbin/nologin \
        triage

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Application runtime
COPY agent/ ./agent/
COPY mcp-server/ ./mcp-server/
COPY common/ ./common/

# Diagnostic knowledge and CI fixtures
COPY skills/k8s-triage/ ./skills/k8s-triage/
COPY fixtures/ci/ ./fixtures/ci/

# Runtime configuration contains no credentials.
ENV ALLOWED_NAMESPACES=staging \
    KUBECONFIG_PATH=/run/credentials/kubeconfig \
    KUBECONFIG_CONTEXT=triage-reader \
    CI_FIXTURES_DIR=/app/fixtures/ci \
    AGENT_DEFAULT_NAMESPACE=staging

USER 10001:10001

ENTRYPOINT ["python", "-m", "agent"]

CMD ["--help"]
