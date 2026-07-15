"""Tests for rag-indexer/app/update_mode/fs_git.py

All tests use tmp_path (pytest built-in) and do not require a running
Docker environment. Real git subprocess is used for git tests because
we test the actual subprocess integration, not a mock.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from app.update_mode.fs_git import (
    VAULT_ROOT,
    AtomicWriteError,
    FileReadError,
    GitError,
    GitIdentity,
    PathValidationError,
    atomic_write,
    build_unified_diff,
    git_apply_commit,
    git_check_available,
    git_init_if_needed,
    git_snapshot,
    read_original_utf8,
    resolve_file_path,
    resolve_vault_root,
    sha256_bytes,
    sha256_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(tmp_path: Path, vault_id: str = "vault-1") -> Path:
    """Create a fake vault root inside tmp_path and patch VAULT_ROOT."""
    import app.update_mode.fs_git as module
    fake_root = tmp_path / "vaults"
    fake_root.mkdir()
    vault_dir = fake_root / vault_id
    vault_dir.mkdir()
    module.VAULT_ROOT = fake_root
    return vault_dir


def _restore_vault_root():
    import app.update_mode.fs_git as module
    module.VAULT_ROOT = Path("/data/vaults")


@pytest.fixture(autouse=True)
def restore_vault_root():
    yield
    _restore_vault_root()


def _git_config(repo: Path) -> None:
    """Configure git user for a test repo."""
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    _git_config(repo)


# ---------------------------------------------------------------------------
# resolve_vault_root
# ---------------------------------------------------------------------------

class TestResolveVaultRoot:
    def test_valid_vault(self, tmp_path):
        vault = _make_vault(tmp_path)
        result = resolve_vault_root("vault-1")
        assert result == vault.resolve()

    def test_missing_directory_raises(self, tmp_path):
        _make_vault(tmp_path)
        with pytest.raises(PathValidationError) as exc:
            resolve_vault_root("nonexistent")
        assert exc.value.code == "vault_root_missing"

    def test_traversal_in_vault_id_raises(self, tmp_path):
        _make_vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_vault_root("../etc")

    def test_slash_in_vault_id_raises(self, tmp_path):
        _make_vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_vault_root("foo/bar")

    def test_nul_in_vault_id_raises(self, tmp_path):
        _make_vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_vault_root("vault\x00id")

    def test_empty_vault_id_raises(self, tmp_path):
        _make_vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_vault_root("")


# ---------------------------------------------------------------------------
# resolve_file_path
# ---------------------------------------------------------------------------

class TestResolveFilePath:
    def _vault(self, tmp_path):
        return _make_vault(tmp_path)

    def test_valid_md(self, tmp_path):
        vault = self._vault(tmp_path)
        (vault / "notes.md").write_text("x")
        result = resolve_file_path(vault, "notes.md")
        assert result == (vault / "notes.md").resolve()

    def test_valid_nested_md(self, tmp_path):
        vault = self._vault(tmp_path)
        (vault / "sub").mkdir()
        (vault / "sub" / "doc.md").write_text("x")
        result = resolve_file_path(vault, "sub/doc.md")
        assert result.name == "doc.md"

    def test_traversal_dotdot_raises(self, tmp_path):
        vault = self._vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_file_path(vault, "../outside.md")

    def test_absolute_path_raises(self, tmp_path):
        vault = self._vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_file_path(vault, "/etc/passwd.md")

    def test_git_segment_raises(self, tmp_path):
        vault = self._vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_file_path(vault, ".git/config.md")

    def test_nul_in_path_raises(self, tmp_path):
        vault = self._vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_file_path(vault, "note\x00s.md")

    def test_non_md_raises(self, tmp_path):
        vault = self._vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_file_path(vault, "notes.pdf")

    def test_non_md_txt_raises(self, tmp_path):
        vault = self._vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_file_path(vault, "notes.txt")

    def test_symlink_outside_vault_raises(self, tmp_path):
        vault = self._vault(tmp_path)
        outside = tmp_path / "secret.md"
        outside.write_text("secret")
        link = vault / "link.md"
        link.symlink_to(outside)
        with pytest.raises(PathValidationError):
            resolve_file_path(vault, "link.md")

    def test_too_long_path_raises(self, tmp_path):
        vault = self._vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_file_path(vault, "a" * 513 + ".md")

    def test_empty_path_raises(self, tmp_path):
        vault = self._vault(tmp_path)
        with pytest.raises(PathValidationError):
            resolve_file_path(vault, "")


# ---------------------------------------------------------------------------
# read_original_utf8 / sha256
# ---------------------------------------------------------------------------

class TestFileIO:
    def test_read_existing(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("hello", encoding="utf-8")
        assert read_original_utf8(f) == "hello"

    def test_read_missing_raises(self, tmp_path):
        with pytest.raises(FileReadError) as exc:
            read_original_utf8(tmp_path / "missing.md")
        assert exc.value.code == "file_not_found"

    def test_sha256_bytes(self):
        import hashlib
        data = b"hello"
        assert sha256_bytes(data) == hashlib.sha256(data).hexdigest()

    def test_sha256_file(self, tmp_path):
        import hashlib
        f = tmp_path / "doc.md"
        f.write_bytes(b"content")
        assert sha256_file(f) == hashlib.sha256(b"content").hexdigest()

    def test_sha256_file_missing_raises(self, tmp_path):
        with pytest.raises(FileReadError):
            sha256_file(tmp_path / "missing.md")


# ---------------------------------------------------------------------------
# build_unified_diff
# ---------------------------------------------------------------------------

class TestBuildUnifiedDiff:
    def test_produces_diff(self):
        diff = build_unified_diff("line1\n", "line2\n", "doc.md")
        assert "-line1" in diff
        assert "+line2" in diff

    def test_identical_produces_empty(self):
        diff = build_unified_diff("same\n", "same\n", "doc.md")
        assert diff == ""


# ---------------------------------------------------------------------------
# atomic_write
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_writes_content(self, tmp_path):
        target = tmp_path / "out.md"
        atomic_write(target, "hello")
        assert target.read_text(encoding="utf-8") == "hello"

    def test_overwrites_existing(self, tmp_path):
        target = tmp_path / "out.md"
        target.write_text("old")
        atomic_write(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_no_tmp_files_left_on_success(self, tmp_path):
        target = tmp_path / "out.md"
        atomic_write(target, "content")
        tmp_files = list(tmp_path.glob(".~update_mode_*"))
        assert tmp_files == []


# ---------------------------------------------------------------------------
# git_check_available
# ---------------------------------------------------------------------------

def test_git_check_available():
    assert git_check_available() is True


# ---------------------------------------------------------------------------
# git_init_if_needed
# ---------------------------------------------------------------------------

class TestGitInit:
    def test_init_creates_git_dir(self, tmp_path):
        vault = _make_vault(tmp_path)
        result = git_init_if_needed(vault)
        assert result is True
        assert (vault / ".git").is_dir()

    def test_init_idempotent(self, tmp_path):
        vault = _make_vault(tmp_path)
        git_init_if_needed(vault)
        result = git_init_if_needed(vault)
        assert result is False

    def test_init_missing_dir_raises(self, tmp_path):
        with pytest.raises(GitError) as exc:
            git_init_if_needed(tmp_path / "nonexistent")
        assert exc.value.code == "vault_root_missing"

    def test_no_initial_commit_after_init(self, tmp_path):
        vault = _make_vault(tmp_path)
        git_init_if_needed(vault)
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=vault,
            capture_output=True,
            text=True,
        )
        # No commits yet — git log returns non-zero or empty
        assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# git_snapshot / git_apply_commit
# ---------------------------------------------------------------------------

_IDENTITY = GitIdentity(name="Mercer Bot", email="mercer@local")


class TestGitSnapshot:
    def test_snapshot_commits_only_target_files(self, tmp_path):
        vault = _make_vault(tmp_path)
        _init_repo(vault)

        target = vault / "session.md"
        target.write_text("# Session")
        unrelated = vault / "other.md"
        unrelated.write_text("unrelated")

        sha = git_snapshot(vault, [target], _IDENTITY)
        assert len(sha) == 40

        # unrelated file must NOT be in the commit
        result = subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"],
            cwd=vault,
            capture_output=True,
            text=True,
        )
        committed_files = result.stdout.strip().splitlines()
        assert "session.md" in committed_files
        assert "other.md" not in committed_files

    def test_snapshot_identity_in_commit(self, tmp_path):
        vault = _make_vault(tmp_path)
        _init_repo(vault)
        target = vault / "doc.md"
        target.write_text("content")
        git_snapshot(vault, [target], _IDENTITY)
        result = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            cwd=vault,
            capture_output=True,
            text=True,
        )
        assert "Mercer Bot" in result.stdout
        assert "mercer@local" in result.stdout

    def test_snapshot_missing_identity_raises(self, tmp_path, monkeypatch):
        vault = _make_vault(tmp_path)
        _init_repo(vault)
        monkeypatch.delenv("GIT_AUTHOR_NAME", raising=False)
        monkeypatch.delenv("GIT_AUTHOR_EMAIL", raising=False)
        target = vault / "doc.md"
        target.write_text("content")
        with pytest.raises(GitError) as exc:
            git_snapshot(vault, [target], None)
        assert exc.value.code == "git_identity_missing"

    def test_snapshot_env_fallback_identity(self, tmp_path, monkeypatch):
        vault = _make_vault(tmp_path)
        _init_repo(vault)
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Env Bot")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "env@local")
        target = vault / "doc.md"
        target.write_text("env content")
        sha = git_snapshot(vault, [target], None)
        assert len(sha) == 40


class TestGitApplyCommit:
    def test_apply_commits_only_target(self, tmp_path):
        vault = _make_vault(tmp_path)
        _init_repo(vault)

        # Need at least one prior commit for apply to work on top of
        base = vault / "base.md"
        base.write_text("base")
        git_snapshot(vault, [base], _IDENTITY, message="base")

        target = vault / "changed.md"
        target.write_text("updated")
        dirty = vault / "dirty.md"
        dirty.write_text("should not be committed")

        sha = git_apply_commit(vault, [target], _IDENTITY, "apply: update changed.md")
        assert len(sha) == 40

        result = subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"],
            cwd=vault,
            capture_output=True,
            text=True,
        )
        committed = result.stdout.strip().splitlines()
        assert "changed.md" in committed
        assert "dirty.md" not in committed

    def test_apply_uses_explicit_message(self, tmp_path):
        vault = _make_vault(tmp_path)
        _init_repo(vault)
        base = vault / "b.md"
        base.write_text("b")
        git_snapshot(vault, [base], _IDENTITY, message="base")
        target = vault / "t.md"
        target.write_text("t")
        git_apply_commit(vault, [target], _IDENTITY, "apply: my message")
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=vault, capture_output=True, text=True,
        )
        assert "apply: my message" in result.stdout

    def test_no_shell_execution(self, tmp_path, monkeypatch):
        """Verify subprocess calls never use shell=True by monkeypatching."""
        import app.update_mode.fs_git as module
        calls = []
        original_run = subprocess.run

        def tracking_run(*args, **kwargs):
            calls.append(kwargs.get("shell", False))
            return original_run(*args, **kwargs)

        monkeypatch.setattr(subprocess, "run", tracking_run)
        vault = _make_vault(tmp_path)
        _init_repo(vault)
        target = vault / "x.md"
        target.write_text("x")
        git_snapshot(vault, [target], _IDENTITY)
        assert all(s is False for s in calls), "shell=True was used"
