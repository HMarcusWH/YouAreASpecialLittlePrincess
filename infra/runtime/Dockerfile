# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
ARG NODE_IMAGE=node:22.22.2-bookworm-slim@sha256:9f6d5975c7dca860947d3915877f85607946403fc55349f39b4bc3688448bb6e

FROM ${NODE_IMAGE} AS render-build
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:${PATH} \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps ./apps
COPY packages ./packages
RUN corepack enable && corepack install
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @princess/render run build
RUN pnpm --filter @princess/render deploy --prod --legacy /opt/render-deploy
RUN pnpm --filter @princess/web exec playwright install chromium
RUN BROWSER="$(node -e "const { chromium } = require('./apps/render/node_modules/playwright-core'); process.stdout.write(chromium.executablePath())")" \
    && mkdir -p /opt/chromium \
    && cp -a "$(dirname "$BROWSER")/." /opt/chromium/

FROM ${PYTHON_IMAGE} AS backend-runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/princess/src:/opt/princess/apps/api \
    HOME=/tmp
WORKDIR /opt/princess
COPY infra/runtime/python-py312.lock /tmp/python-py312.lock
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: --no-deps \
      -r /tmp/python-py312.lock \
    && rm -rf /root/.cache /tmp/python-py312.lock \
    && rm -rf /usr/local/lib/python3.12/site-packages/pip* \
              /usr/local/lib/python3.12/site-packages/setuptools* \
              /usr/local/lib/python3.12/site-packages/wheel* \
              /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12
COPY src ./src
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
COPY migrations ./migrations
COPY infra/environments ./infra/environments
COPY infra/runtime ./infra/runtime
COPY schema/premium_interpretation_database_v1.json ./schema/premium_interpretation_database_v1.json
RUN groupadd --system --gid 10001 princess \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin princess \
    && mkdir -p /data \
    && chown 10001:10001 /data
USER 10001:10001
ENTRYPOINT ["python", "/opt/princess/infra/runtime/entrypoint.py"]

FROM backend-runtime AS export-runtime
USER root
COPY --from=render-build /usr/local/bin/node /usr/local/bin/node
COPY --from=render-build /opt/render-deploy /opt/princess/apps/render
COPY --from=render-build /repo/apps/render/dist/render.mjs /opt/princess/apps/render/dist/render.mjs
COPY --from=render-build /opt/chromium /opt/chromium
RUN node /opt/princess/apps/render/node_modules/playwright-core/cli.js install-deps chromium \
    && rm -rf /var/lib/apt/lists/*
ENV PRINCESS_CHROMIUM=/opt/chromium/chrome
USER 10001:10001
