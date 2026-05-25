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
**внутри sidecar** — `preprocessor.py` является точной копией
`rag-indexer/parser/preprocessing/preprocessor.py`.

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
{"status": "ok", "service": "pdf-sidecar"}
```

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
    "metadata": {"source": "document.pdf", "parser": "unstructured-hi_res"},
    "page_count": 5
}
```

Поля `y0` и `font_size` в `headings` могут быть `0.0` — они используются
rag-indexer только для сортировки заголовков внутри страницы.

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

## Структура файлов

```
pdf-sidecar/
├── app.py            — FastAPI HTTP-сервер
├── parser.py         — парсер (unstructured → унифицированный формат)
├── preprocessor.py   — копия preprocessor.py из rag-indexer
├── requirements.txt  — Python-зависимости
├── install.sh        — скрипт установки venv + deps
├── start.sh          — запуск в фоне (nohup)
├── stop.sh           — остановка
├── status.sh         — проверка статуса
├── README.md         — эта документация
└── logs/             — логи (создаётся автоматически)
    └── sidecar.log
```

## Синхронизация preprocessor.py

`preprocessor.py` — намеренная копия `rag-indexer/parser/preprocessing/preprocessor.py`.
При изменении оригинала необходимо вручную обновить эту копию.
В будущем можно вынести в `shared_contracts/` или отдельный пакет.
