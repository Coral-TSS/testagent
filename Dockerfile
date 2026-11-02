# syntax=docker/dockerfile:1
# TestAgent platform image. The same image also runs the procurement demo SUT (command "demo").

# ---- web UI (React + Vite) -------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# vite writes the bundle to ../src/testagent/web
RUN npm run build

# ---- platform ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# optional: --build-arg DEBIAN_MIRROR=<host> if deb.debian.org is unreachable from your network
ARG DEBIAN_MIRROR=deb.debian.org
RUN sed -i "s#deb.debian.org#${DEBIAN_MIRROR}#g" /etc/apt/sources.list.d/debian.sources \
 && apt-get -o Acquire::Retries=5 update \
 && apt-get install -y --no-install-recommends git ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# dependencies first (better layer caching)
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN uv sync --frozen --no-dev --no-install-project
# Chromium + its system libraries for browser execution and Playwright test scripts
RUN .venv/bin/playwright install --with-deps chromium \
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
