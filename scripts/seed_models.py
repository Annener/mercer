#!/usr/bin/env python3
"""
Seed default embedding and reranker models into rag-backend.

Usage:
    python3 scripts/seed_models.py [--base-url http://localhost:8000]

Both calls are idempotent: existing records are silently skipped (HTTP 409/422).
After seeding, the reranker is activated automatically.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Default model definitions
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = {
    "model_id": "sidecar_bge_m3",
    "provider": "sidecar",
    "model_name": "BAAI/bge-m3",
    "base_url": "http://host.docker.internal:8765",
    "dimensions": 1024,
    "max_retries": 3,
    "timeout_seconds": 30,
}

RERANK_MODEL = {
    "model_id": "bge-reranker-v2-m3",
    "provider": "openai_compatible",
    "model_name": "BAAI/bge-reranker-v2-m3",
    "base_url": "http://host.docker.internal:8765",
    "api_key": "",
    "timeout_seconds": 30,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GREEN  = "\033[0;32m"
YELLOW = "\033[0;33m"
RED    = "\033[0;31m"
RESET  = "\033[0m"


def _request(method: str, url: str, data: dict | None = None) -> tuple[dict | None, int]:
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return (json.loads(raw) if raw else None), r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        return None, e.code


def wait_for_backend(base_url: str, retries: int = 15, delay: float = 2.0) -> None:
    """Block until rag-backend /health responds or raise SystemExit."""
    health = f"{base_url}/health"
    print(f"{YELLOW}→ Ожидаю rag-backend {health} ...{RESET}")
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(health, timeout=5) as r:
                if r.status == 200:
                    print(f"{GREEN}✓ Backend доступен.{RESET}")
                    return
        except Exception:
            pass
        print(f"  попытка {attempt}/{retries}, жду {delay}s...")
        time.sleep(delay)
    print(f"{RED}✗ Backend не отвечает после {retries} попыток. Прерываю.{RESET}")
    sys.exit(1)


def create_model(base_url: str, path: str, payload: dict, label: str) -> dict | None:
    url = f"{base_url}{path}"
    result, status = _request("POST", url, payload)
    if status in (200, 201):
        print(f"{GREEN}✓ {label} создана (HTTP {status}).{RESET}")
        return result
    if status in (409, 422):
        print(f"{YELLOW}~ {label} уже существует, пропускаю.{RESET}")
        return None
    print(f"{RED}✗ Ошибка создания {label}: HTTP {status}.{RESET}")
    sys.exit(1)


def activate_model(base_url: str, path: str, label: str) -> None:
    url = f"{base_url}{path}"
    _, status = _request("POST", url)
    if status in (200, 201, 204):
        print(f"{GREEN}✓ {label} активирована.{RESET}")
    elif status in (404,):
        # Уже могла быть активна или создана с is_active=True
        print(f"{YELLOW}~ {label}: activate вернул {status}, возможно уже активна.{RESET}")
    else:
        print(f"{RED}✗ Ошибка активации {label}: HTTP {status}.{RESET}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed default models into Mercer rag-backend.")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of rag-backend (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Skip waiting for backend health check",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    if not args.no_wait:
        wait_for_backend(base)

    print()
    print("=== Embedding model ===")
    create_model(
        base,
        "/api/settings/models/embedding",
        EMBEDDING_MODEL,
        f"Embedding [{EMBEDDING_MODEL['model_id']}]",
    )

    print()
    print("=== Rerank model ===")
    result = create_model(
        base,
        "/api/settings/models/rerank",
        RERANK_MODEL,
        f"Reranker [{RERANK_MODEL['model_id']}]",
    )
    # Activate regardless of whether we just created it or it already existed
    activate_model(
        base,
        f"/api/settings/models/rerank/{RERANK_MODEL['model_id']}/activate",
        f"Reranker [{RERANK_MODEL['model_id']}]",
    )

    print()
    print(f"{GREEN}✓ Seed завершён.{RESET}")


if __name__ == "__main__":
    main()
