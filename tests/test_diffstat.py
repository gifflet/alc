# test_diffstat.py — Hermetic tests for the diffstat feature.
# Covers the _diffstat helper directly and its wiring into execute_mandate's
# RunReport.diffstat. No real model is called; uses the mock engine (or a small
# file-mutating fake) via the operator_layer fixture.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alc.engine import Capabilities, EngineResult
from alc.models import Diffstat
from alc.runner import _diffstat, _git_state, execute_mandate


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True
    )


# ---------------------------------------------------------------------------
# Unit tests: _diffstat
# ---------------------------------------------------------------------------


class TestDiffstatUnit:
    def test_no_changed_files_returns_none(self, tmp_path: Path) -> None:
        assert _diffstat(tmp_path, [], {}) is None

    def test_outside_git_repo_returns_none(self, tmp_path: Path) -> None:
        """A non-git workdir makes `git diff --numstat HEAD` fail -> None, never raise."""
        result = _diffstat(tmp_path, ["some_file.txt"], {"some_file.txt": "??"})
        assert result is None

    def test_git_missing_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A missing git binary degrades to None instead of raising."""
        def _raise(*args: object, **kwargs: object):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr("alc.runner.subprocess.run", _raise)
        result = _diffstat(tmp_path, ["f.txt"], {"f.txt": " M"})
        assert result is None

    def test_modified_tracked_file_counts_adds_and_dels(self, tmp_path: Path) -> None:
        """3 lines -> 4 lines, dropping the middle one: 2 added, 1 deleted."""
        _init_repo(tmp_path)
        target = tmp_path / "f.txt"
        target.write_text("line1\nline2\nline3\n")
        _commit_all(tmp_path, "seed")

        target.write_text("line1\nline3\nline4\nline5\n")
        state_after = _git_state(tmp_path)
        assert state_after is not None

        result = _diffstat(tmp_path, ["f.txt"], state_after)
        assert result == Diffstat(adds=2, dels=1, files_deleted=0)

    def test_deleted_tracked_file_counts_files_deleted_and_dels(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        target = tmp_path / "g.txt"
        target.write_text("a\nb\nc\n")
        _commit_all(tmp_path, "seed")

        target.unlink()
        state_after = _git_state(tmp_path)
        assert state_after is not None

        result = _diffstat(tmp_path, ["g.txt"], state_after)
        assert result == Diffstat(adds=0, dels=3, files_deleted=1)

    def test_new_untracked_file_contributes_nothing(self, tmp_path: Path) -> None:
        """git diff --numstat HEAD does not see untracked content — a known,
        documented limitation: diffstat measures TRACKED changes (the metric this
        wave cares about is shrinkage, not new-file line counts)."""
        _init_repo(tmp_path)
        (tmp_path / "seed.txt").write_text("seed\n")
        _commit_all(tmp_path, "seed")

        (tmp_path / "new.txt").write_text("brand\nnew\n")
        state_after = _git_state(tmp_path)
        assert state_after is not None

        result = _diffstat(tmp_path, ["new.txt"], state_after)
        assert result == Diffstat(adds=0, dels=0, files_deleted=0)


# ---------------------------------------------------------------------------
# Integration: execute_mandate wires diffstat onto RunReport
# ---------------------------------------------------------------------------


class _WriteFileEngine:
    """A fake engine that overwrites one file with new content on every turn."""

    name = "mock"

    def __init__(self, rel_path: str, content: str) -> None:
        self._rel_path = rel_path
        self._content = content

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request) -> EngineResult:
        (request.workdir / self._rel_path).write_text(self._content)
        return EngineResult(ok=True, output_text="[mock] wrote file")


class _DeleteFileEngine:
    """A fake engine that removes one tracked file on every turn."""

    name = "mock"

    def __init__(self, rel_path: str) -> None:
        self._rel_path = rel_path

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request) -> EngineResult:
        (request.workdir / self._rel_path).unlink()
        return EngineResult(ok=True, output_text="[mock] deleted file")


class TestExecuteMandateDiffstat:
    def test_diffstat_none_outside_git_repo(
        self, tmp_path: Path, operator_layer: Path
    ) -> None:
        from alc.intake import load_blueprint, load_manifest

        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        report = execute_mandate(
            manifest=manifest,
            blueprint=blueprint,
            directive="do nothing",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.diffstat is None

    def test_diffstat_none_when_nothing_changed(
        self, tmp_path: Path, operator_layer: Path
    ) -> None:
        """Inside a git repo but the (no-op) mock engine writes nothing -> no diffstat."""
        from alc.intake import load_blueprint, load_manifest

        _init_repo(tmp_path)
        (tmp_path / "seed.txt").write_text("seed")
        _commit_all(tmp_path, "seed")

        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        report = execute_mandate(
            manifest=manifest,
            blueprint=blueprint,
            directive="do nothing",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.diffstat is None

    def test_diffstat_populated_when_tracked_file_modified(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        from alc.intake import load_blueprint, load_manifest

        _init_repo(tmp_path)
        (tmp_path / "f.txt").write_text("line1\nline2\nline3\n")
        _commit_all(tmp_path, "seed")

        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        engine = _WriteFileEngine("f.txt", "line1\nline3\nline4\nline5\n")
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        report = execute_mandate(
            manifest=manifest,
            blueprint=blueprint,
            directive="do nothing",
            workdir=tmp_path,
        )
        assert report.diffstat == Diffstat(adds=2, dels=1, files_deleted=0)

    def test_diffstat_files_deleted_when_tracked_file_removed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        from alc.intake import load_blueprint, load_manifest

        _init_repo(tmp_path)
        (tmp_path / "g.txt").write_text("a\nb\nc\n")
        _commit_all(tmp_path, "seed")

        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        engine = _DeleteFileEngine("g.txt")
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        report = execute_mandate(
            manifest=manifest,
            blueprint=blueprint,
            directive="do nothing",
            workdir=tmp_path,
        )
        assert report.diffstat == Diffstat(adds=0, dels=3, files_deleted=1)
