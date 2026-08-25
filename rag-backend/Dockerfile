FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY rag-backend/app/static/frontend/package.json rag-backend/app/static/frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY rag-backend/app/static/frontend/ ./
RUN npm run build

FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY shared_contracts /app/shared_contracts
RUN uv pip install --system -e /app/shared_contracts

COPY rag-backend/requirements.txt /app/requirements.txt
RUN uv pip install --system -r /app/requirements.txt

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# shared_contracts доступен через PYTHONPATH=/app — корень репо в образе
# содержит /app/shared_contracts/. См. комментарий в rag-indexer/Dockerfile.
ENV PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY shared_contracts /app/shared_contracts
COPY rag-backend/app /app/app
COPY rag-backend/alembic.ini /app/alembic.ini
COPY rag-backend/migrations /app/migrations
COPY rag-backend/tools /app/tools

# Frontend static bundle (React + Vite build output)
COPY --from=frontend-builder /app/frontend/dist /app/app/static/dist
COPY --from=frontend-builder /app/frontend/dist/index.html /app/app/static/index.html

RUN find /usr/local/lib/python3.13/site-packages -type d \( -name __pycache__ -o -name tests \) -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.13/site-packages -type f -name "*.pyc" -delete \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* \
    && rm -rf /usr/local/lib/python3.13/site-packages/uv \
    && rm -rf /usr/local/lib/python3.13/site-packages/uv-*.dist-info \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 /usr/local/bin/uv /usr/local/bin/uvx

CMD ["python", "-m", "app.main"]