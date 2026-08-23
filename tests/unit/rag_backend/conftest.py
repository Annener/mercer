"""pytest config for rag-backend unit tests.

Adds repo root and rag-backend to sys.path so that `from app.xxx import ...`
and `from shared_contracts.models import ...` work without PYTHONPATH tweaks.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # tests/unit → tests → корень
BACKEND = ROOT / "rag-backend"

for p in (ROOT, BACKEND):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)