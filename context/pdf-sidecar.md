# pdf-sidecar

## Назначение

Автономный HTTP-сервис (FastAPI, **версия 5.0**) для высококачественного парсинга PDF, реранжирования
и эмбеддинга текстовых фрагментов. Работает как отдельный процесс (sidecar) на хосте, **вне Docker**.
Намеренно не зависит от других компонентов Mercer — все зависимости самодостаточны.

**Точка запуска:** `python app.py` или `./start.sh`  
**Порт по умолчанию:** `8765` (`PDF_SIDECAR_PORT`)  
**Запросы поступают** от `rag-indexer` и `rag-backend` (sidecar-прокси) через `PDF_SIDECAR_URL`.

---

## Структура файлов

```
pdf-sidecar/
├── app.py             — FastAPI-сервер (основной файл)
├── parser.py          — unstructured hi_res + yolox (парсинг PDF, OCR)
├── preprocessor.py    — постобработка текста
├── reranker.py        — CrossEncoder (BAAI/bge-reranker-v2-m3) через sentence-transformers
├── embedder.py        — SentenceTransformer (BAAI/bge-m3), OpenAI-compatible API
├── requirements.txt
├── install.sh         — установка зависимостей + моделей
├── start.sh / stop.sh / status.sh
├── logs/              — sidecar.log
└── agent/             — host-agent для macOS (launchd)
    ├── agent.py
    ├── com.mercer.host-agent.plist.template
    └── requirements.txt
```

---

## Стек технологий

| Компонент | Технология | Назначение |
|---|---|---|
| Парсер PDF | `unstructured` + `unstructured-inference`, стратегия `hi_res`, модель layout `yolox` | Парсинг, OCR, извлечение заголовков и таблиц |
| Реранкер | `sentence-transformers` — `CrossEncoder(BAAI/bge-reranker-v2-m3)` | Реранжирование |
| Эмбеддер | `sentence-transformers` — `SentenceTransformer(BAAI/bge-m3)` | Эмбеддинг (L2-normализован, OpenAI-compatible) |
| HTTP-сервер | FastAPI 5.0 + Uvicorn | Асинхронный сервер |

Все модели загружаются **один раз при старте** (lifespan-хук FastAPI), держатся в памяти все время работы.

**Преимущество выноса bge-m3 из Ollama в sidecar:**
- Батчинг: весь батч за один forward pass вместо N HTTP-запросов к Ollama
- Изоляция: нагрузка индексации не мешает LLM-запросам пользователей
- Детерминированность: те же веса, не зависящие от версии Ollama

---

## Эндпоинты

### `GET /health`
Проверка жизнеспособности. Возвращает статус всех трёх моделей:
```json
{
  "status": "ok",
  "service": "pdf-sidecar",
  "reranker_loaded": "True",
  "embedder_loaded": "True"
}
```

### `POST /parse`
Синхронный парсинг PDF. Принимает `multipart/form-data` (field `file`), возвращает JSON.

Пример ответа:
```json
{
  "page_count": 12,
  "headings": ["Overview", "Chapter 1"],
  "pages": [
    {"page_number": 1, "text": "...", "has_table": false}
  ]
}
```

### `POST /parse/stream`
CTSTREAMING. Возвращает NDJSON-поток (`Content-Type: application/x-ndjson`).

Прогресс-событие для каждой страницы:
```json
{"type": "progress", "page": 3, "total": 12, "elapsed": 4.2, "elements": 18, "has_table": false}
```
Финальное событие:
```json
{"type": "result", "page_count": 12, "headings": [...], "pages": [...]}
```
Или при ошибке:
```json
{"type": "error", "detail": "..."}
```

### `POST /rerank`
Реранжирование документов через CrossEncoder (`BAAI/bge-reranker-v2-m3`).

Запрос:
```json
{"query": "...", "documents": ["doc1", "doc2", "doc3"]}
```
Ответ (отсортирован по убыванию релевантности):
```json
[
  {"index": 2, "relevance_score": 0.94},
  {"index": 0, "relevance_score": 0.71},
  {"index": 1, "relevance_score": 0.33}
]
```
Sortable by `relevance_score` desc. Параметр `batch_size=8` — оптимизация памяти для MPS/CPU.

### `POST /embed`  *(добавлено в v5.0)*
Эмбеддинг текстов через SentenceTransformer (`BAAI/bge-m3`). **OpenAI-совместимый формат ответа.**

Запрос:
```json
{"texts": ["text one", "text two", "text three"]}
```
Ответ:
```json
{
  "data": [
    {"index": 0, "embedding": [0.021, -0.043, ...]},
    {"index": 1, "embedding": [...]},
    {"index": 2, "embedding": [...]}
  ]
}
```
Векторы L2-нормализованы, совместимы с cosine-similarity. Батчинг: весь список — один forward pass.

---

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `PDF_SIDECAR_PORT` | `8765` | Порт uvicorn |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `RERANKER_MODEL_ID` | `BAAI/bge-reranker-v2-m3` | HuggingFace model id реранкера |
| `RERANKER_FORCE_CPU` | `0` | `1` — принудительно CPU (рекомендуется на macOS) |
| `EMBEDDER_MODEL_ID` | `BAAI/bge-m3` | HuggingFace model id эмбеддера |
| `EMBEDDER_FORCE_CPU` | `0` | `1` — принудительно CPU |
| `EMBED_BATCH_SIZE` | `32` | Размер батча при эмбеддинге |

---

## Модули

### `parser.py`
Парсинг через `unstructured` (стратегия `hi_res`, модель layout `yolox`). OCR-режим автоматический. Поддерживает `progress_callback(page_num, total, n_elements, has_table)` для streaming-режима. Прогрев моделей при старте: `warmup_models()`.

### `preprocessor.py`
Постобработка текста: удаление артефактов парсера, нормализация unicode, убрание лишних переносов.

### `reranker.py`
`CrossEncoder(BAAI/bge-reranker-v2-m3)` через `sentence-transformers`. Device-автоопределение: CUDA > MPS > CPU. На macOS рекомендуется `RERANKER_FORCE_CPU=1` — MPS даёт тихий CPU-fallback для большинства ops без изменения выходного. `PYTORCH_ENABLE_MPS_FALLBACK=1` выставляется автоматически при `device=mps`.

### `embedder.py`  *(v5.0)*
`SentenceTransformer(BAAI/bge-m3)` через `sentence-transformers`. L2-нормализация (`normalize_embeddings=True`). Device-автоопределение: MPS > CUDA > CPU. Весь батч за один forward pass. `EMBEDDER_FORCE_CPU=1` — принудительно CPU. Функции: `load_embedder()`, `embed(texts)`, `is_loaded()`.

---

## поддиректория `agent/`

Для мачин на macOS: **launchd**-вариант host-agent (аналог `systemd` для Linux).

| Файл | Назначение |
|---|---|
| `agent.py` | Тот же host-agent (`pdf-sidecar/agent/agent.py` = `host-agent/agent.py`), настроен на `SIDECAR_DIR` = родительская директория |
| `com.mercer.host-agent.plist.template` | Шаблон launchd plist (автозапуск при логине). Инсталлируется в `~/Library/LaunchAgents/` |
| `requirements.txt` | Зависимости host-agent (FastAPI, uvicorn) |

Для Linux используется `host-agent/mercer-host-agent.service` (проект `host-agent/` в корне репозитория).

> См. также: `context/host-agent.md`

---

## Запуск и управление

```bash
# Установка зависимостей и загрузка моделей
bash install.sh

# Запуск
./start.sh

# Статус
./status.sh

# Останов
./stop.sh
```

Управление через UI: через host-agent (см. `GET/POST /api/settings/sidecar/*`).
