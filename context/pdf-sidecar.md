# pdf-sidecar

## Назначение

Автономный HTTP-сервис (FastAPI, версия 4.0.0) для высококачественного парсинга PDF-документов
и реранжирования текстовых фрагментов. Работает как отдельный процесс (sidecar) рядом с
`rag-indexer` и `rag-backend`. Намеренно не зависит от других компонентов Mercer — все
зависимости самодостаточны.

**Точка запуска:** `python app.py` или `./start.sh`  
**Порт по умолчанию:** `8765` (переопределяется через `PDF_SIDECAR_PORT`)  
**Требуемый Python:** 3.11–3.13 (unstructured-inference несовместим с 3.14+)

---

## Файловая структура

```
pdf-sidecar/
├── app.py           — FastAPI-приложение, эндпоинты, lifespan-хук
├── parser.py        — Парсинг PDF через unstructured hi_res, параллельный батч-парсинг
├── preprocessor.py  — Постобработка текста (нормализация Unicode, пробелы, переносы)
├── reranker.py      — CrossEncoder-реранкер (BAAI/bge-reranker-v2-m3)
├── requirements.txt — Python-зависимости
├── install.sh       — Установка системных зависимостей (Tesseract, Ghostscript, venv)
├── start.sh         — Запуск сервиса
├── stop.sh          — Остановка сервиса
├── status.sh        — Проверка статуса
└── logs/
    └── sidecar.log  — Файл логов
```

---

## HTTP API

### `GET /health`

Проверка работоспособности. Возвращает статус сервиса и флаг загруженности reranker-модели.

```json
{"status": "ok", "service": "pdf-sidecar", "reranker_loaded": "True"}
```

---

### `POST /parse`

Синхронный парсинг PDF. Принимает `multipart/form-data` с полем `file` (`.pdf`).
Блокирует соединение до полного завершения парсинга. Возвращает `application/json`.

**Формат ответа:**
```json
{
  "pages": [
    {"text": "...", "page_number": 1}
  ],
  "headings": [
    {"text": "Раздел 1", "page_number": 1, "y0": 45.2, "font_size": 0.0}
  ],
  "metadata": {"source": "file.pdf", "parser": "unstructured-hi_res/yolox"},
  "page_count": 10
}
```

После парсинга каждая страница дополнительно прогоняется через `preprocessor.preprocess()`.

---

### `POST /parse/stream`

Стриминговый парсинг PDF. Принимает тот же формат что `/parse`.  
Возвращает `application/x-ndjson` — поток JSON-объектов, по одному на строку.

**Типы событий в потоке:**

| Тип события | Поля | Описание |
|---|---|---|
| `progress` | `page`, `total`, `elapsed`, `elements`, `has_table` | Прогресс по завершению каждой страницы |
| `result` | все поля ответа + `"type": "result"` | Финальный результат (последнее сообщение при успехе) |
| `error` | `detail` | Ошибка парсинга |

Прогресс-события поступают через `asyncio.Queue` — thread-safe callback из дочерних процессов.
Раз в 5 секунд (при отсутствии событий) отправляется keepalive `\n`.

---

### `POST /rerank`

Реранжирование документов через CrossEncoder.

**Тело запроса:**
```json
{
  "model": "BAAI/bge-reranker-v2-m3",
  "query": "вопрос пользователя",
  "documents": ["фрагмент 1", "фрагмент 2", "..."]
}
```

**Формат ответа** (совместим с openai_compatible `/rerank` провайдерами):
```json
{
  "results": [
    {"index": 2, "relevance_score": 0.921},
    {"index": 0, "relevance_score": 0.743}
  ]
}
```

Возвращает `503` если модель ещё не загружена при старте.

---

## Архитектура парсера (`parser.py`)

### Стратегия hi_res

Используется `unstructured.partition_pdf` со стратегией `hi_res`:
- **YOLO (yolox FP32)** — детекция layout (заголовки, параграфы, таблицы, списки)
- **Table Transformer** — распознавание структуры таблиц  
- **Tesseract OCR** — извлечение текста из изображений и при необходимости из страниц

> **Почему yolox FP32, не yolox_quantized?**  
> `yolox_quantized` деградирует на русских PDF: все элементы классифицируются как
> `UncategorizedText`, заголовки и таблицы теряются. FP32-модель обязательна.

### Параллельный батч-парсинг

Документ разрезается на батчи, каждый батч запускается в отдельном **процессе**
через `ProcessPoolExecutor` (не в потоке), потому что:
- unstructured/ONNX Runtime держат GIL во время inference
- процессы дают настоящий параллелизм

**Расчёт размера батча:**
```
batch_size = clamp(ceil(total_pages / min(MAX_WORKERS, cpu_count)), MIN=8, MAX=30)
```

Пример: 98 страниц, 4 воркера → batch=25 → 4 батча.

**Параметры:**
- `PDF_SIDECAR_MAX_WORKERS` — максимум параллельных процессов (по умолчанию: 4)
- `PDF_RENDER_DPI` — DPI рендеринга страниц (по умолчанию: 200; стандартный 350 избыточен)

При одном батче (маленький документ) process overhead исключается — используется single-pass.

### GPU-поддержка (Apple Silicon)

Monkey-patches применяются при старте каждого воркер-процесса:
- **Table Transformer** → device `mps` (через `_patched_load_agent`)
- **YOLO** → `CoreMLExecutionProvider` + `CPUExecutionProvider` (если CoreML доступен)

### Ghostscript fallback

Если PDFium не смог открыть PDF (`Data format error`), парсер:
1. Нормализует файл через `gs -sDEVICE=pdfwrite` во временный файл
2. Повторяет `hi_res` парсинг на нормализованном файле
3. Удаляет временный файл в `finally`-блоке
4. Если и после нормализации PDFium падает — пробрасывает исключение в `app.py`

### Фильтрация элементов

Элементы типа `Image` и `FigureCaption` **намеренно отбрасываются** — не нужны для RAG.

Включаемые категории:
- **Heading-категории** (→ поле `headings`): `Title`, `Header`, `SectionHeader`
- **Text-категории** (→ поле `pages[].text`): `NarrativeText`, `Text`, `ListItem`, `Table`, `Footer`, `EmailAddress`, `UncategorizedText`, `Formula`

### Фикс OCR-переносов

Tesseract возвращает переносы строк внутри элементов: `«выва-\nливается»`.  
Фиксируется на двух уровнях:
1. `parser.py` — сразу после получения raw_text (regex: `(\w+)-\s*\n\s*(\w)` → `\1\2`)
2. `preprocessor.py` — шаг 4a, для случаев где `\n` уже заменён пробелом (`«выва- ливается»`)

---

## Препроцессор (`preprocessor.py`)

Постобработка текста после парсинга. Версия V3.0. Применяется к каждой странице в `app.py`
после завершения парсинга.

**Шаги обработки:**
1. NFC-нормализация Unicode (`unicodedata.normalize`)
2. Замена проблемных символов по `CHAR_MAP` (U+FFFD → пробел, U+2014 → дефис и др.)
3. Удаление строк состоящих только из цифры (номера страниц)
4. Склейка OCR-переносов строк (`\w+-\n\w` → слитно)
5. Сохранение двойных `\n\n` (абзацы), схлопывание одиночных `\n` в пробел
6. Нормализация пробелов и trailing whitespace

Файл намеренно **дублируется** из `rag-indexer/parser/preprocessing/preprocessor.py`
для сохранения автономности sidecar. При изменении оригинала — синхронизировать.

**Детектор подозрительных символов:** логирует первое появление символов вне разрешённых
диапазонов (Latin, Cyrillic, пунктуация, математика). Помогает диагностировать кодировочные
проблемы PDF.

---

## Reranker (`reranker.py`)

CrossEncoder-реранкер на базе `sentence-transformers`.

**Модель по умолчанию:** `BAAI/bge-reranker-v2-m3` (переопределяется через `RERANKER_MODEL_ID`)

**Device-автоопределение:**
| Условие | Устройство |
|---|---|
| `RERANKER_FORCE_CPU=1` | CPU (рекомендуется для macOS) |
| Apple Silicon, MPS доступен | MPS + `PYTORCH_ENABLE_MPS_FALLBACK=1` |
| CUDA доступна | CUDA |
| Фоллбэк | CPU |

> На macOS MPS для bge-reranker даёт тихий CPU-fallback для большинства операций
> с оверхедом на передачу данных. `RERANKER_FORCE_CPU=1` часто быстрее.

Модель загружается **один раз** при старте (`lifespan` хук → `load_reranker()`).
`rerank()` вызывает `CrossEncoder.predict()` с `batch_size=8`.
Ответ совместим с openai_compatible `/rerank` провайдерами (`retrieval.py` в rag-backend).

---

## Жизненный цикл приложения (Lifespan)

При старте (FastAPI `lifespan` hook) последовательно выполняется прогрев:

1. **`warmup_models()`** (parser.py) — загружает spaCy tokenizer, YOLO, Table Transformer
2. **`load_reranker()`** (reranker.py) — загружает CrossEncoder в память

Ошибки прогрева **не фатальны** — логируются как `WARNING`, сервис стартует.
Прогрев устраняет cold start на первом реальном запросе.

---

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `PDF_SIDECAR_PORT` | `8765` | Порт HTTP-сервера |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `PDF_SIDECAR_MAX_WORKERS` | `4` | Максимум параллельных воркер-процессов |
| `PDF_RENDER_DPI` | `200` | DPI рендеринга страниц PDF |
| `UNSTRUCTURED_HI_RES_MODEL_NAME` | `yolox` | Модель YOLO для layout detection |
| `PDF_GS_TIMEOUT` | `120` | Таймаут Ghostscript нормализации (секунды) |
| `RERANKER_MODEL_ID` | `BAAI/bge-reranker-v2-m3` | Модель CrossEncoder для /rerank |
| `RERANKER_FORCE_CPU` | `0` | Принудительный CPU для reranker (`1` рекомендуется на macOS) |

---

## Ключевые зависимости

| Пакет | Назначение |
|---|---|
| `fastapi`, `uvicorn` | HTTP-сервер |
| `unstructured[pdf]>=0.14.0` | Парсинг PDF (hi_res strategy) |
| `onnxruntime>=1.17.0` | YOLO inference (ONNX Runtime) |
| `torch>=2.2.0` | Table Transformer MPS, Reranker device |
| `sentence-transformers>=3.0.0` | CrossEncoder для reranker |
| `ghostscript>=0.7` | Fallback нормализация битых PDF |
| `pypdfium2` | Быстрый счётчик страниц и разрезка батчей |
| `lxml>=5.0.0` | Ускоренный парсинг HTML-таблиц из unstructured |
| `pytesseract` | OCR (системный Tesseract, устанавливается через install.sh) |

---

## Интеграция с Mercer

`pdf-sidecar` вызывается из **`rag-indexer`** при индексации PDF-документов:
- `/parse` или `/parse/stream` — для извлечения текста и структуры документа
- `/rerank` — вызывается из `rag-backend` (retrieval pipeline) для финального ранжирования

Сервис **не имеет общих Python-пакетов** с другими компонентами — запускается в
собственном virtualenv (`pdf-sidecar/.venv`). `preprocessor.py` дублируется из
`rag-indexer` для сохранения этой автономности.

---

## Известные ограничения и решения

| Проблема | Решение |
|---|---|
| Утечка потоков при TimeoutError в streaming | asyncio.Queue вместо SimpleQueue+run_in_executor (v3.1) |
| UnboundLocalError при логировании ошибки | `exc_info=exc` (объект) вместо `exc_info=True` (v3.2) |
| Дублированный вывод логов от uvicorn | dictConfig с пустыми handlers у uvicorn-логгеров (propagate=True) |
| yolox_quantized деградирует на русских PDF | Жёсткий дефолт на yolox FP32 |
| MPS тихий fallback для reranker | `RERANKER_FORCE_CPU=1` рекомендуется на macOS |
| Битые PDF (PDFium: Data format error) | Ghostscript нормализация перед повторным парсингом |
