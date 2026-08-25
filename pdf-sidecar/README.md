# pdf-sidecar

HTTP-сервис для парсинга PDF через **unstructured hi_res** с поддержкой OCR.
Запускается на хосте (MacBook Pro M3) в Python venv, принимает PDF-файлы от
`rag-indexer` по HTTP и возвращает постраничный текст с заголовками.

## Архитектура

```
rag-indexer (Docker)
       │
       │  POST http://host.docker.internal:8765/parse
       │  multipart/form-data  (PDF bytes)
       ▼
pdf-sidecar (venv, хост macOS)
       │
       ├── unstructured hi_res  ← основной путь
       │        ├── detectron2 (layout analysis, MPS GPU)
       │        └── tesseract  (OCR, рус+англ)
       ├── unstructured fast    ← fallback при падении hi_res
       └── pdf2image + pytesseract  ← последний резерв
       │
       │  JSON response
       ▼
rag-indexer: pages[], headings[], metadata{}
```

Препроцессинг текста (удаление артефактов, нормализация) выполняется
**внутри sidecar** через `shared_contracts.preprocessing.preprocess()`
(см. также `shared_contracts/`).

## Системные зависимости (через Homebrew)

```bash
# tesseract + языковые пакеты (обязательно)
brew install tesseract tesseract-lang

# poppler (нужен pdf2image для OCR-фоллбэка)
brew install poppler
```

## Установка Python-окружения

```bash
cd pdf-sidecar
chmod +x install.sh start.sh stop.sh status.sh

# Установит venv, requirements.txt и detectron2
./install.sh
```

> **Примечание по detectron2:**
> Официального wheel для Apple Silicon нет на PyPI. `install.sh` пытается
> установить из исходников через `git+https://github.com/facebookresearch/detectron2`.
> Требует Xcode Command Line Tools и установленного torch.
> Если установка не прошла — unstructured автоматически переключится на fast-стратегию.

## Управление

```bash
./start.sh          # запустить на порту 8765 (по умолчанию)
./start.sh 9876     # запустить на другом порту
./stop.sh           # остановить
./status.sh         # проверить статус + health check
```

Логи записываются в `logs/sidecar.log`.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `PDF_SIDECAR_PORT` | `8765` | Порт HTTP-сервера |
| `LOG_LEVEL` | `INFO` | Уровень логирования |

## API

### `GET /health`
```json
{
  "status": "ok",
  "service": "pdf-sidecar",
  "reranker_loaded": "True",
  "embedder_loaded": "True"
}
```

`reranker_loaded` / `embedder_loaded` — `"True"` / `"False"` строки (не bool).
Сервис может отвечать `/health` даже если модели ещё не загружены (lifespan в процессе warmup'а).

### `POST /parse`
Content-Type: `multipart/form-data`

Поле: `file` — PDF-файл.

**Ответ:**
```json
{
    "pages": [
        {"text": "Текст страницы...", "page_number": 1}
    ],
    "headings": [
        {"text": "Заголовок раздела", "page_number": 1, "y0": 0.0, "font_size": 0.0}
    ],
    "metadata": {"source": "document.pdf", "parser": "unstructured-hi_res/yolox"},
    "page_count": 5
}
```

Поля `y0` и `font_size` в `headings` могут быть `0.0` — они используются
rag-indexer только для сортировки заголовков внутри страницы.

### `POST /parse/stream`
Content-Type: `multipart/form-data`. Поле `file` — PDF.

Возвращает NDJSON-поток (`application/x-ndjson`):
- `{"type":"progress","page":N,"total":M,"elapsed":X,"elements":K,"has_table":bool}` — для каждой страницы
- `{"type":"result", ...}` — финальный результат (та же структура что у `/parse`)
- `{"type":"error", "detail":"..."}` — при ошибке парсинга

### `POST /rerank`
Реранжирование документов через CrossEncoder (`BAAI/bge-reranker-v2-m3`).

Запрос:
```json
{"query": "...", "documents": ["doc1", "doc2", "doc3"]}
```

Ответ (отсортирован по убыванию `relevance_score`):
```json
{"results": [{"index": 2, "relevance_score": 0.94}, ...]}
```

Возвращает `503` если реранкер ещё не загружен.

### `POST /embeddings`
Эмбеддинг через SentenceTransformer (`BAAI/bge-m3`). **OpenAI-совместимый формат.**

Запрос (строка или список):
```json
{"model": "BAAI/bge-m3", "input": "text"}
{"model": "BAAI/bge-m3", "input": ["text one", "text two"]}
```

Ответ:
```json
{
  "data": [
    {"index": 0, "embedding": [0.021, -0.043, ...]},
    {"index": 1, "embedding": [...]}
  ],
  "model": "BAAI/bge-m3"
}
```

Векторы L2-нормализованы. Весь список обрабатывается за один forward pass.

Возвращает `503` если embedder ещё не загружен.

## Конфигурация в rag-indexer

В `config/config.yaml` добавьте секцию `pdf_sidecar`:

```yaml
pdf_sidecar:
  # URL sidecar-сервиса (host.docker.internal → хост MacBook из Docker-контейнера)
  url: "http://host.docker.internal:8765"
  # Таймаут парсинга одного файла (секунды). hi_res может занимать 30-120с на большой PDF.
  timeout_seconds: 180
  # Если sidecar недоступен — падать или молча переключаться на старый pdfminer?
  fallback_to_pdfminer: true
```

Для использования sidecar как embedding-провайдера в настройках модели vault'а:
```yaml
provider: openai_compatible  # или "sidecar"
base_url: http://host.docker.internal:8765
```

## Структура файлов

```
pdf-sidecar/
├── app.py            — FastAPI HTTP-сервер (/parse, /parse/stream, /rerank, /embeddings)
├── parser.py         — парсер (unstructured → унифицированный формат, parallel batch)
├── reranker.py       — CrossEncoder BAAI/bge-reranker-v2-m3
├── embedder.py       — SentenceTransformer BAAI/bge-m3 (OpenAI-compatible)
├── requirements.txt  — Python-зависимости
├── install.sh        — скрипт установки venv + deps + прогрев моделей
├── start.sh          — запуск в фоне (nohup). Автоматически выставляет
│                       PYTHONPATH=.. для shared_contracts.
├── stop.sh           — остановка
├── status.sh         — проверка статуса
├── agent/            — host-agent (управление sidecar с хоста через HTTP)
│   ├── agent.py
│   ├── com.mercer.host-agent.plist.template
│   ├── requirements.txt
│   ├── .venv/
│   └── logs/
├── README.md         — эта документация
└── logs/             — логи (создаётся автоматически)
    └── sidecar.log
```
