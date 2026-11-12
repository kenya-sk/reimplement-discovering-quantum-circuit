FROM ghcr.io/astral-sh/uv:0.7.3 AS uv
FROM python:3.13-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/qdiscover
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python
COPY src ./src
RUN uv sync --locked --no-dev --python /usr/local/bin/python
RUN cd src/qdiscover/_vendor/uncompute \
    && make kernel PYTHON=/opt/qdiscover/.venv/bin/python ARCH_FLAGS=

FROM python:3.13-slim-bookworm AS evaluator
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/qdiscover /opt/qdiscover
ENV PATH="/opt/qdiscover/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PYTHONPATH="/opt/qdiscover/src:/opt/qdiscover/src/qdiscover/_vendor/uncompute" \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    NUMBA_CACHE_DIR=/tmp/numba \
    XDG_CACHE_HOME=/tmp/cache \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    NUMBA_NUM_THREADS=1
WORKDIR /opt/qdiscover/src/qdiscover/_vendor/uncompute
USER 65532:65532
ENTRYPOINT ["python"]
