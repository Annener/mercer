FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY shared_contracts /app/shared_contracts
RUN uv pip install --system -e /app/shared_contracts

COPY db-api-server/requirements.txt /app/requirements.txt
RUN uv pip install --system -r /app/requirements.txt

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY shared_contracts /app/shared_contracts
COPY db-api-server/main.py /app/main.py
COPY db-api-server/config.py /app/config.py
COPY db-api-server/config_loader.py /app/config_loader.py
COPY db-api-server/logging_config.py /app/logging_config.py
COPY db-api-server/api /app/api
COPY db-api-server/storage /app/storage

RUN find /usr/local/lib/python3.13/site-packages -type d \( -name __pycache__ -o -name tests \) -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.13/site-packages -type f -name "*.pyc" -delete \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* \
    && rm -rf /usr/local/lib/python3.13/site-packages/uv \
    && rm -rf /usr/local/lib/python3.13/site-packages/uv-*.dist-info \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 /usr/local/bin/uv /usr/local/bin/uvx

CMD ["python", "main.py"]
