# syntax=docker/dockerfile:1
# TestAgent platform image. The same image also runs the procurement demo SUT (command "demo").
#
# Optional package mirrors (all empty by default = the official sources). Set them in .env for
# docker compose, or pass --build-arg, e.g. on servers in mainland China:
#   DEBIAN_MIRROR=mirrors.aliyun.com
#   PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
#   NPM_REGISTRY=https://registry.npmmirror.com
#   PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
# Packages are still checked against the hashes in uv.lock / package-lock.json.

# image that provides the uv binary (override if ghcr.io is unreachable, e.g. a registry proxy)
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13
FROM ${UV_IMAGE} AS uv

# ---- web UI (React + Vite) -------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
ARG NPM_REGISTRY=
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
 && npm ci --no-audit --no-fund
COPY web/ ./
# vite writes the bundle to ../src/testagent/web
RUN npm run build

# ---- platform ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# optional Debian mirror host (also used by "playwright install --with-deps" below)
ARG DEBIAN_MIRROR=
RUN if [ -n "$DEBIAN_MIRROR" ]; then \
      sed -i "s#deb.debian.org#${DEBIAN_MIRROR}#g" /etc/apt/sources.list.d/debian.sources; \
    fi \
 && apt-get -o Acquire::Retries=5 update \
 && apt-get install -y --no-install-recommends git ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# dependencies first (better layer caching)
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
# uv sync --frozen downloads from the URLs recorded in uv.lock (files.pythonhosted.org), so with a
# mirror the locked set is exported with its hashes and installed from the mirror first; uv sync then
# only verifies it.
ARG PIP_INDEX_URL=
RUN if [ -n "$PIP_INDEX_URL" ]; then \
      uv export --frozen --no-dev --no-emit-project --format requirements.txt -o /tmp/requirements.txt \
      && uv venv .venv \
      && uv pip install --python .venv/bin/python --index-url "$PIP_INDEX_URL" -r /tmp/requirements.txt \
      && rm /tmp/requirements.txt; \
    fi \
 && uv sync --frozen --no-dev --no-install-project
# Chromium + its system libraries for browser execution and Playwright test scripts
ARG PLAYWRIGHT_DOWNLOAD_HOST=
RUN if [ -z "$PLAYWRIGHT_DOWNLOAD_HOST" ]; then unset PLAYWRIGHT_DOWNLOAD_HOST; fi \
 && .venv/bin/playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY src ./src
COPY examples ./examples
COPY ops ./ops
COPY --from=web /build/src/testagent/web ./src/testagent/web
RUN uv sync --frozen --no-dev \
 && chmod +x ops/docker-entrypoint.sh \
 && useradd --create-home --uid 10001 testagent \
 && mkdir -p /data/runtime /data/demo \
 && chown -R testagent:testagent /data

ENV PATH=/app/.venv/bin:$PATH \
    TESTAGENT_HOST=0.0.0.0 \
    TESTAGENT_PORT=8765 \
    TESTAGENT_RUNTIME_DIR=/data/runtime
USER testagent
EXPOSE 8765 8766
VOLUME ["/data"]
ENTRYPOINT ["/usr/bin/tini", "--", "/app/ops/docker-entrypoint.sh"]
CMD ["platform"]
