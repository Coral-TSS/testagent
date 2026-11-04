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
#
# Build speed: needs BuildKit (default for "docker compose build" with the buildx plugin). Downloads
# of apt, uv and npm are kept in BuildKit cache mounts, so even a changed lock file only fetches the
# difference; a code-only change rebuilds just the last layers. Per-step timing:
#   docker compose build --progress=plain
# Base images can be pointed at a registry mirror/proxy as well (PYTHON_IMAGE, NODE_IMAGE, UV_IMAGE).

# image that provides the uv binary (override if ghcr.io is unreachable, e.g. a registry proxy)
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:22-bookworm-slim
FROM ${UV_IMAGE} AS uv

# ---- web UI (React + Vite) -------------------------------------------------------------
FROM ${NODE_IMAGE} AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
ARG NPM_REGISTRY=
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
 && echo "npm registry: $(npm config get registry)" \
 && npm ci --no-audit --no-fund --prefer-offline
COPY web/ ./
# vite writes the bundle to ../src/testagent/web
RUN npm run build

# ---- platform ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE}
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/root/.cache/uv \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# optional Debian mirror host (also used by "playwright install --with-deps" below)
ARG DEBIAN_MIRROR=
# apt downloads stay in a cache mount (the image's docker-clean hook would delete them)
# The mirror replaces deb.debian.org for debian, debian-updates and debian-security, in both the
# deb822 (debian.sources) and the classic sources.list format. Retries and timeouts keep a slow
# mirror from hanging the build; the chosen sources are printed in the build log.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
 && printf '%s\n' 'Binary::apt::APT::Keep-Downloaded-Packages "true";' \
      'Acquire::Retries "5";' 'Acquire::http::Timeout "30";' 'Acquire::https::Timeout "30";' \
      > /etc/apt/apt.conf.d/90testagent-build \
 && if [ -n "$DEBIAN_MIRROR" ]; then \
      for f in /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list; do \
        if [ -f "$f" ]; then sed -i -E "s#(https?://)(deb|security)\.debian\.org#\1${DEBIAN_MIRROR}#g" "$f"; fi; \
      done; \
    fi \
 && echo "apt sources (DEBIAN_MIRROR='${DEBIAN_MIRROR}'):" \
 && { grep -hE '^(URIs:|deb )' /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null || true; } \
 && apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates tini
WORKDIR /app

# dependencies first (better layer caching)
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
# uv sync --frozen downloads from the URLs recorded in uv.lock (files.pythonhosted.org), so with a
# mirror the locked set is exported with its hashes and installed from the mirror first; uv sync then
# only verifies it.
ARG PIP_INDEX_URL=
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    echo "Python index: ${PIP_INDEX_URL:-PyPI (uv.lock URLs)}" \
 && if [ -n "$PIP_INDEX_URL" ]; then \
      uv export --frozen --no-dev --no-emit-project --format requirements.txt -o /tmp/requirements.txt \
      && uv venv .venv \
      && uv pip install --python .venv/bin/python --index-url "$PIP_INDEX_URL" -r /tmp/requirements.txt \
      && rm /tmp/requirements.txt; \
    fi \
 && uv sync --frozen --no-dev --no-install-project
# Headless Chromium + its system libraries for browser execution and Playwright test scripts.
# The container has no display, so only the headless shell is installed (about half the download);
# PLAYWRIGHT_ONLY_SHELL=0 installs the full Chromium build as well (e.g. for channel="chromium").
ARG PLAYWRIGHT_DOWNLOAD_HOST=
ARG PLAYWRIGHT_ONLY_SHELL=1
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    if [ -z "$PLAYWRIGHT_DOWNLOAD_HOST" ]; then unset PLAYWRIGHT_DOWNLOAD_HOST; fi \
 && if [ "$PLAYWRIGHT_ONLY_SHELL" = 1 ]; then only="--only-shell"; else only=""; fi \
 && .venv/bin/playwright install --with-deps $only chromium

COPY src ./src
COPY examples ./examples
COPY ops ./ops
COPY --from=web /build/src/testagent/web ./src/testagent/web
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev \
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
