ARG BASE=python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
FROM ${BASE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/
ENV  UV_COMPILE_BYTECODE=1  UV_LINK_MODE=copy  UV_PYTHON_DOWNLOADS=0  UV_NO_DEV=1
WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

FROM ${BASE}
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app/ ./app/
ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin almanac \
    && mkdir /data \
    && chown almanac:almanac /data
USER 10001
ENTRYPOINT ["python", "-m", "app"]
CMD ["--help"]