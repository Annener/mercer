"""pytest config for rag-indexer unit tests.

Adds repo root and rag-indexer/ to sys.path so that bare imports like
``from indexer_worker import run_indexing``, ``from parser.state.redis_state_manager import RedisStateManager``,
and ``from app.main import app`` work without PYTHONPATH tweaks.

NB: tests/unit/rag_backend/conftest.py installs ``mercer/rag-backend`` in sys.path.
Both ``mercer/rag-backend`` and ``mercer/rag-indexer`` contain a top-level ``app``
package — running them in the SAME pytest process would cause Python to resolve
``from app.xxx`` to whichever ``app/`` appears first in sys.path.

This is solved at the Makefile level: ``make test`` invokes ``test-rag-backend``
and ``test-rag-indexer`` as separate pytest processes.
"""
import sys
from pathlib import Path

# tests/unit/rag_indexer/conftest.py → parents[2] = tests/, parents[3] = mercer/
TESTS_DIR = Path(__file__).resolve().parents[2]
ROOT = TESTS_DIR.parent
INDEXER = ROOT / "rag-indexer"

for p in (INDEXER, ROOT):
    sp = str(p)
    if sp in sys.path:
        sys.path.remove(sp)
    sys.path.insert(0, sp)
