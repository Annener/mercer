"""Filesystem and git primitives for Campaign Update Mode.

Rules enforced here:
- Only rag-indexer reads/writes /data/vaults.
- All paths validated via Path.resolve() containment, never prefix string checks.
- Git subprocess always uses argument list, never shell=True.
- git add . / git add -A / git add -f are never used.
- No automatic initial commit.
- Snapshot and apply commits stage only explicit .md path lists.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)

VAULT_ROOT = Path("/data/vaults")

_FORBIDDEN_FILENAME_CHARS = frozenset(["\x00", "/", "\\"])
_MAX_REL_PATH_LEN = 512


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class UpdateModeError(Exception):
    """Base for all update-mode errors."""
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class PathValidationError(UpdateModeError):
    pass


class FileReadError(UpdateModeError):
    pass


class AtomicWriteError(UpdateModeError):
    pass


class GitError(UpdateModeError):
    pass


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def resolve_vault_root(vault_id: str) -> Path:
    """Return absolute vault root, validated to be directly under VAULT_ROOT.

    Raises PathValidationError for any traversal or invalid vault_id.
    """
    if not vault_id or "/" in vault_id or "\\" in vault_id or "\x00" in vault_id:
        raise PathValidationError("vault_root_missing", f"Invalid vault_id={vault_id!r}")
    candidate = (VAULT_ROOT / vault_id).resolve()
    # Must be a direct child of VAULT_ROOT
    if candidate.parent != VAULT_ROOT.resolve():
        raise PathValidationError("vault_root_missing", f"vault_id resolves outside vault root: {vault_id!r}")
    if not candidate.is_dir():
        raise PathValidationError("vault_root_missing", f"Vault directory does not exist: {candidate}")
    return candidate


def resolve_file_path(vault_root: Path, rel_path: str) -> Path:
    """Validate and resolve a relative .md path within vault_root.

    Raises PathValidationError for:
    - absolute paths
    - paths containing ..
    - paths containing NUL, raw slash/backslash in filename component
    - .git path segments
    - non-.md extension
    - paths longer than _MAX_REL_PATH_LEN
    - paths that resolve outside vault_root
    """
    if len(rel_path) > _MAX_REL_PATH_LEN:
        raise PathValidationError("invalid_path", "rel_path exceeds 512 characters")
    if not rel_path or rel_path.strip() == "":
        raise PathValidationError("invalid_path", "rel_path is empty")
    if os.path.isabs(rel_path):
        raise PathValidationError("invalid_path", "rel_path must be relative")
    if "\x00" in rel_path:
        raise PathValidationError("invalid_path", "rel_path contains NUL byte")

    parts = Path(rel_path).parts
    for part in parts:
        if part == "..":
            raise PathValidationError("invalid_path", "rel_path contains '..' component")
        if part == ".git" or part.startswith(".git/"):
            raise PathValidationError("invalid_path", "rel_path contains .git segment")

    # Validate filename component
    filename = Path(rel_path).name
    for ch in _FORBIDDEN_FILENAME_CHARS:
        if ch in filename:
            raise PathValidationError("invalid_path", f"filename contains forbidden character")
    if Path(rel_path).suffix.lower() != ".md":
        raise PathValidationError("invalid_path", f"only .md files are supported, got: {rel_path!r}")

    resolved = (vault_root / rel_path).resolve()
    # Containment check — must not escape vault_root
    vault_root_resolved = vault_root.resolve()
    try:
        resolved.relative_to(vault_root_resolved)
    except ValueError:
        raise PathValidationError("invalid_path", "rel_path resolves outside vault root")

    return resolved


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def read_original_utf8(path: Path) -> str:
    """Read original .md file as UTF-8 string."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileReadError("file_not_found", str(path))
    except OSError as exc:
        raise FileReadError("file_read_error", str(exc))


def sha256_bytes(data: bytes) -> str:
    """Return hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return hex SHA-256 of file at path (raw bytes)."""
    try:
        return sha256_bytes(path.read_bytes())
    except FileNotFoundError:
        raise FileReadError("file_not_found", str(path))
    except OSError as exc:
        raise FileReadError("file_read_error", str(exc))


def build_unified_diff(original: str, proposed: str, rel_path: str) -> str:
    """Return unified diff between original and proposed content."""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
    )


def atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via a sibling temp file + rename.

    Creates parent directories if needed (only _campaign_notes/ is permitted
    to be auto-created; callers must enforce this policy before calling).
    """
    path.parent.mkdir(parents=False, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=".~update_mode_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise AtomicWriteError("write_error", str(exc))


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GitIdentity:
    name: str
    email: str


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run git with explicit argument list. Never uses shell=True."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        shell=False,
    )


def git_check_available() -> bool:
    """Return True if git binary is available."""
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            shell=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def git_init_if_needed(vault_root: Path) -> bool:
    """Run `git init` inside vault_root if not already a git repository.

    Returns True if init was performed, False if already initialised.
    Raises GitError if the directory does not exist or git fails.
    """
    if not vault_root.is_dir():
        raise GitError("vault_root_missing", str(vault_root))
    git_dir = vault_root / ".git"
    if git_dir.is_dir():
        return False
    result = _run_git(["init"], cwd=vault_root)
    if result.returncode != 0:
        log.error("git init failed", extra={"vault_root": str(vault_root)})
        raise GitError("git_init_failed", "git init returned non-zero")
    return True


def _identity_env(identity: GitIdentity) -> dict[str, str]:
    """Return env dict with GIT_AUTHOR_* and GIT_COMMITTER_* set.

    Does not modify global/local git config.
    """
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": identity.name,
        "GIT_AUTHOR_EMAIL": identity.email,
        "GIT_COMMITTER_NAME": identity.name,
        "GIT_COMMITTER_EMAIL": identity.email,
    }


def _resolve_identity(vault_identity: GitIdentity | None) -> GitIdentity:
    """Resolve git identity:
    1. vault DB override (passed in)
    2. deployment env GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL
    3. raise GitError git_identity_missing
    """
    if vault_identity is not None:
        return vault_identity
    name = os.environ.get("GIT_AUTHOR_NAME", "").strip()
    email = os.environ.get("GIT_AUTHOR_EMAIL", "").strip()
    if name and email:
        return GitIdentity(name=name, email=email)
    raise GitError("git_identity_missing", "No vault or env git identity configured")


def git_snapshot(
    vault_root: Path,
    paths: Sequence[Path],
    vault_identity: GitIdentity | None,
    message: str = "update-mode: snapshot",
) -> str:
    """Stage only explicit paths and create a snapshot commit.

    Returns the commit SHA.
    Raises GitError on failure.
    Never uses git add . / git add -A / git add -f.
    """
    identity = _resolve_identity(vault_identity)
    env = _identity_env(identity)

    for path in paths:
        rel = str(path.relative_to(vault_root))
        result = subprocess.run(
            ["git", "add", "--", rel],
            cwd=vault_root,
            capture_output=True,
            text=True,
            shell=False,
            env=env,
        )
        if result.returncode != 0:
            raise GitError("git_add_failed", f"git add failed for {rel!r}")

    result = subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=vault_root,
        capture_output=True,
        text=True,
        shell=False,
        env=env,
    )
    if result.returncode != 0:
        log.error("git snapshot commit failed", extra={"vault_root": str(vault_root)})
        raise GitError("git_commit_failed", "git commit returned non-zero")

    sha_result = _run_git(["rev-parse", "HEAD"], cwd=vault_root)
    return sha_result.stdout.strip()


def git_apply_commit(
    vault_root: Path,
    paths: Sequence[Path],
    vault_identity: GitIdentity | None,
    message: str,
) -> str:
    """Stage only the explicitly listed paths and create an apply commit.

    Returns the commit SHA.
    Raises GitError on failure.
    """
    identity = _resolve_identity(vault_identity)
    env = _identity_env(identity)

    for path in paths:
        rel = str(path.relative_to(vault_root))
        result = subprocess.run(
            ["git", "add", "--", rel],
            cwd=vault_root,
            capture_output=True,
            text=True,
            shell=False,
            env=env,
        )
        if result.returncode != 0:
            raise GitError("git_add_failed", f"git add failed for {rel!r}")

    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=vault_root,
        capture_output=True,
        text=True,
        shell=False,
        env=env,
    )
    if result.returncode != 0:
        log.error("git apply commit failed", extra={"vault_root": str(vault_root)})
        raise GitError("git_commit_failed", "git commit returned non-zero")

    sha_result = _run_git(["rev-parse", "HEAD"], cwd=vault_root)
    return sha_result.stdout.strip()
