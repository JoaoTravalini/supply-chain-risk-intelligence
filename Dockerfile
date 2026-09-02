FROM python:3.13-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN python -m pip install --no-cache-dir uv==0.12.5

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

RUN groupadd --system supplychain \
    && useradd --system --gid supplychain --home-dir /app --shell /usr/sbin/nologin supplychain

COPY --from=builder --chown=supplychain:supplychain /app/.venv /app/.venv
COPY --chown=supplychain:supplychain src ./src

USER supplychain

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/_stcore/health', timeout=5).read()" || exit 1

CMD ["sh", "-c", "streamlit run src/supplychain/ui/app.py --server.address=0.0.0.0 --server.port=${PORT:-8080} --server.headless=true --browser.gatherUsageStats=false"]
