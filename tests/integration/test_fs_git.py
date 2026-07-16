"""Tests for rag-indexer/app/update_mode/fs_git.py path validation and in-memory ops.

Runs without Docker / git binary dependency where possible.
Git tests are skipped if `git` is not available.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Allow import from rag-indexer without installing package
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "rag-indexer"))

from app.update_mode.fs_git import (
    VAULT_ROOT,
    AtomicWriteError,
    FileReadError,
    GitIdentity,
    PathValidationError,
    _append_string_not_used,  # noqa: F401 — only used as import guard
    atomic_write,
    build_unified_diff,
    git_check_available,
    git_init_if_needed,
    read_original_utf8,
    resolve_file_path,
    sha256_bytes,
)


GIT_AVAILABLE = git_check_available()


# ---------------------------------------------------------------------------
# resolve_file_path
# ---------------------------------------------------------------------------

class TestResolveFilePath:
    def test_valid_path(self, tmp_path: Path):
        f = tmp_path / "note.md"
        f.write_text("hello")
        resolved = resolve_file_path(tmp_path, "note.md")
        assert resolved == f.resolve()

    def test_absolute_path_rejected(self, tmp_path: Path):
        with pytest.raises(PathValidationError, match="relative"):
            resolve_file_path(tmp_path, "/etc/passwd")

    def test_dotdot_rejected(self, tmp_path: Path):
        with pytest.raises(PathValidationError, match="'\\.\\.'"):
            resolve_file_path(tmp_path, "../escape.md")

    def test_dotgit_rejected(self, tmp_path: Path):
        with pytest.raises(PathValidationError, match="\\.git"):
            resolve_file_path(tmp_path, ".git/config")

    def test_non_md_rejected(self, tmp_path: Path):
        with pytest.raises(PathValidationError, match="\.md"):
            resolve_file_path(tmp_path, "script.py")

    def test_nul_byte_rejected(self, tmp_path: Path):
        with pytest.raises(PathValidationError):
            resolve_file_path(tmp_path, "note\x00.md")

    def test_traversal_via_symlink_rejected(self, tmp_path: Path):
        """Symlink that resolves outside vault_root must be rejected."""
        outside = tmp_path.parent / "outside"
        outside.mkdir(exist_ok=True)
        link = tmp_path / "link.md"
        link.symlink_to(outside / "secret.md")
        with pytest.raises(PathValidationError):
            resolve_file_path(tmp_path, "link.md")

    def test_subdir_valid(self, tmp_path: Path):
        sub = tmp_path / "_campaign_notes"
        sub.mkdir()
        f = sub / "note.md"
        f.write_text("content")
        resolved = resolve_file_path(tmp_path, "_campaign_notes/note.md")
        assert resolved == f.resolve()

    def test_empty_path_rejected(self, tmp_path: Path):
        with pytest.raises(PathValidationError):
            resolve_file_path(tmp_path, "")

    def test_too_long_path_rejected(self, tmp_path: Path):
        with pytest.raises(PathValidationError, match="512"):
            resolve_file_path(tmp_path, "a" * 513 + ".md")


# ---------------------------------------------------------------------------
# read_original_utf8
# ---------------------------------------------------------------------------

class TestReadOriginalUtf8:
    def test_reads_existing_file(self, tmp_path: Path):
        f = tmp_path / "note.md"
        f.write_text("hello world", encoding="utf-8")
        assert read_original_utf8(f) == "hello world"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileReadError, match="file_not_found"):
            read_original_utf8(tmp_path / "missing.md")


# ---------------------------------------------------------------------------
# atomic_write
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_creates_new_file(self, tmp_path: Path):
        target = tmp_path / "out.md"
        atomic_write(target, "content")
        assert target.read_text(encoding="utf-8") == "content"

    def test_overwrites_existing_file(self, tmp_path: Path):
        target = tmp_path / "out.md"
        target.write_text("old")
        atomic_write(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_no_temp_file_left_on_success(self, tmp_path: Path):
        target = tmp_path / "out.md"
        atomic_write(target, "x")
        remaining = list(tmp_path.glob(".~update_mode_*"))
        assert remaining == []


# ---------------------------------------------------------------------------
# build_unified_diff
# ---------------------------------------------------------------------------

class TestBuildUnifiedDiff:
    def test_diff_shows_added_line(self):
        diff = build_unified_diff("line1\n", "line1\nline2\n", "notes/note.md")
        assert "+line2" in diff

    def test_diff_empty_for_identical(self):
        diff = build_unified_diff("same\n", "same\n", "note.md")
        assert diff == ""

    def test_diff_shows_removed_line(self):
        diff = build_unified_diff("line1\nline2\n", "line1\n", "note.md")
        assert "-line2" in diff


# ---------------------------------------------------------------------------
# sha256_bytes
# ---------------------------------------------------------------------------

class TestSha256Bytes:
    def test_known_hash(self):
        # echo -n "" | sha256sum
        empty_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert sha256_bytes(b"") == empty_sha

    def test_different_inputs_differ(self):
        assert sha256_bytes(b"a") != sha256_bytes(b"b")


# ---------------------------------------------------------------------------
# git_init_if_needed (skipped if no git)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not GIT_AVAILABLE, reason="git not available")
class TestGitInitIfNeeded:
    def test_init_creates_git_dir(self, tmp_path: Path):
        result = git_init_if_needed(tmp_path)
        assert result is True
        assert (tmp_path / ".git").is_dir()

    def test_init_idempotent(self, tmp_path: Path):
        git_init_if_needed(tmp_path)
        result = git_init_if_needed(tmp_path)
        assert result is False

    def test_missing_dir_raises(self, tmp_path: Path):
        from app.update_mode.fs_git import GitError
        with pytest.raises(GitError):
            git_init_if_needed(tmp_path / "nonexistent")
