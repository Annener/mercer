"""pytest config for pdf-sidecar unit tests.

Adds pdf-sidecar/ and repo root to sys.path so that bare imports like
``from preprocessor import preprocess`` and ``from shared_contracts.preprocessing import preprocess``
work without PYTHONPATH tweaks.

NB: pdf-sidecar/ contains ``app.py`` as a top-level module (not a package).
Neither rag-backend nor rag-indexer reference any pdf-sidecar module, so this
conftest does not collide with conftests in tests/unit/rag_backend or
tests/unit/rag_indexer — pytest invokes each directory in a separate process
per the Makefile, and pdf-sidecar tests can additionally run in any order.
"""
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[2]
ROOT = TESTS_DIR.parent
SIDECAR = ROOT / "pdf-sidecar"

for p in (SIDECAR, ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


# Защита от cross-test side-effects: test_app_*.py подменяют sys.modules
# ['reranker'/'embedder'/'parser'/'preprocessor'] на MagicMock, чтобы изолировать
# app.py. Без восстановления последующие test_reranker/test_embedder не смогут
# импортировать реальные модули. autouse fixture сбрасывает эти подмены после
# каждого теста.
@pytest.fixture(autouse=True)
def _restore_pdf_sidecar_modules():
    saved = {}
    for name in ("reranker", "embedder", "parser", "preprocessor", "app", "agent"):
        if name in sys.modules:
            saved[name] = sys.modules[name]
            del sys.modules[name]
    try:
        yield
    finally:
        for name in ("reranker", "embedder", "parser", "preprocessor", "app", "agent"):
            sys.modules.pop(name, None)
        sys.modules.update(saved)