FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY shared_contracts /app/shared_contracts
RUN uv pip install --system -e /app/shared_contracts

COPY rag-indexer/requirements.txt /app/requirements.txt
RUN uv pip install --system -r /app/requirements.txt

COPY rag-indexer/requirements-dev.txt /app/requirements-dev.txt
RUN uv pip install --system -r /app/requirements-dev.txt

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        git \
        libmagic1 \
        libgl1 \
        libglib2.0-0 \
        tesseract-ocr \
        tesseract-ocr-rus \
        tesseract-ocr-eng \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY shared_contracts /app/shared_contracts
COPY rag-indexer/app /app/app
COPY rag-indexer/api /app/api
COPY rag-indexer/embedding /app/embedding
COPY rag-indexer/parser /app/parser
COPY rag-indexer/storage /app/storage
COPY rag-indexer/config.py /app/config.py
COPY rag-indexer/config_loader.py /app/config_loader.py
COPY rag-indexer/logging_config.py /app/logging_config.py
COPY rag-indexer/indexer_worker.py /app/indexer_worker.py
COPY rag-indexer/tests /app/tests
COPY rag-indexer/pytest.ini /app/pytest.ini

RUN find /usr/local/lib/python3.13/site-packages -type d \( -name __pycache__ \) -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.13/site-packages -type f -name "*.pyc" -delete \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* \
    && rm -rf /usr/local/lib/python3.13/site-packages/uv \
    && rm -rf /usr/local/lib/python3.13/site-packages/uv-*.dist-info \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 /usr/local/bin/uv /usr/local/bin/uvx

CMD ["python", "-m", "app.main"]
