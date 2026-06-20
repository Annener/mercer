# Намеренное дублирование: этот файл является копией rag-backend/app/logging_config.py.
# Оба сервиса используют одинаковую конфигурацию логирования, но shared_contracts
# не монтируется в rag-indexer как Python-пакет на уровне приложения,
# поэтому вынос в shared_contracts потребовал бы изменения точки входа indexer.
# При изменении формата логов — обновляй оба файла синхронно.
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


NOISY_LOGGERS = ("pdfminer", "unstructured", "watchdog", "httpx", "httpcore", "uvicorn.access")


def setup_logging(service_name: str, log_dir: str = "/app/logs", level: str = "INFO") -> None:
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level.upper())

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        log_path / f"{service_name}.log",
        maxBytes=50 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    for logger_name in NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
