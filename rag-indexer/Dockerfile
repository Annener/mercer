FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY shared_contracts /app/shared_contracts
RUN uv pip install --system -e /app/shared_contracts

COPY rag-indexer/requirements.txt /app/requirements.txt
RUN uv pip install --system -r /app/requirements.txt

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# shared_contracts доступен через PYTHONPATH=/app — корень репо в образе
# содержит /app/shared_contracts/. Без PYTHONPATH pip install -e shared_contracts
# не заполняет finder (setuptools 80+ не подхватывает regular package с
# wildcard import в __init__.py), и `from shared_contracts.preprocessing import
# preprocess` падает с ModuleNotFoundError.
ENV PYTHONPATH=/app

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
COPY rag-indexer/logging_config.py /app/logging_config.py
COPY rag-indexer/indexer_worker.py /app/indexer_worker.py
COPY rag-indexer/chunking_pipeline.py /app/chunking_pipeline.py
COPY rag-indexer/embedding_pipeline.py /app/embedding_pipeline.py
COPY rag-indexer/provider_factory.py /app/provider_factory.py

RUN find /usr/local/lib/python3.13/site-packages -type d \( -name __pycache__ \) -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.13/site-packages -type f -name "*.pyc" -delete \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* \
    && rm -rf /usr/local/lib/python3.13/site-packages/uv \
    && rm -rf /usr/local/lib/python3.13/site-packages/uv-*.dist-info \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 /usr/local/bin/uv /usr/local/bin/uvx

CMD ["python", "-m", "app.main"]
