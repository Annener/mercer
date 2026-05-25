from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".md", ".pdf"}
READ_BLOCK_SIZE = 8192


def _md5(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - SPEC-03 requires MD5 file checksums.
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(READ_BLOCK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_vault(vault_path: str) -> list[dict[str, Any]]:
    root = Path(vault_path)
    if not root.exists():
        raise FileNotFoundError(f"Vault path does not exist: {vault_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"Vault path is not a directory: {vault_path}")

    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue

        extension = path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            logger.debug("Skipping unsupported file extension: %s", path)
            continue

        stat = path.stat()
        files.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(root)),
                "extension": extension,
                "checksum": _md5(path),
                "last_modified": stat.st_mtime,
                "size_bytes": stat.st_size,
            }
        )
    return files
