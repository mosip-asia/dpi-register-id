# syntax=docker/dockerfile:1

# ------------------------------------------------------------------------------
# Base Builder Stage
# ------------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation and copy mode
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install dependencies using cache mounts for fast builds
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy source tree and install project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ------------------------------------------------------------------------------
# Development Stage (for Dev Containers & local development)
# ------------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS development

WORKDIR /app

# Install system utilities useful in development
RUN apt-get update && apt-get install -y --no-install-recommends \
    sudo \
    curl \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Setup non-root dev user with passwordless sudo
ARG USERNAME=appuser
ARG USER_UID=1000
ARG USER_GID=1000

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m -s /bin/bash $USERNAME \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=dev

USER $USERNAME

EXPOSE 8000

CMD ["sleep", "infinity"]

# ------------------------------------------------------------------------------
# Production Runner Stage (Lean, hardened production image)
# ------------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runner

WORKDIR /app

# Create non-root system user and ensure app directory ownership
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser && \
    mkdir -p /app/logs && \
    chown -R appuser:appgroup /app

# Copy virtual environment and app code from builder
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appgroup /app/src /app/src
COPY --from=builder --chown=appuser:appgroup /app/django_manage.py /app/django_manage.py
COPY --from=builder --chown=appuser:appgroup /app/pyproject.toml /app/pyproject.toml

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=5s \
    CMD python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health")' || exit 1

CMD ["python3", "-m", "uvicorn", "project.web:app", "--host", "0.0.0.0", "--port", "8000"]
