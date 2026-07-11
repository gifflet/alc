# test_changed_files.py — Hermetic tests for the changed-files feature.
# Covers _git_state, _changed_between, and the execute_mandate integration.
# No real model is called; uses the mock engine via the operator_layer fixture.
from __future__ import annotations

import subprocess
from pathlib import Path


from alc.runner import _changed_between, _git_state


# ---------------------------------------------------------------------------
# Unit tests: _git_state
# ---------------------------------------------------------------------------


class TestGitState:
    def test_returns_none_outside_git_repo(self, tmp_path: Path) -> None:
        """_git_state must return None when the directory is not a git work tree."""
        result = _git_state(tmp_path)
        assert result is None

    def test_returns_empty_dict_for_clean_repo(self, tmp_path: Path) -> None:
        """_git_state returns an empty dict (not None) for a clean git repo."""
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        # Commit an initial file so HEAD exists.
        readme = tmp_path / "README.md"
        readme.write_text("hello")
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", "README.md"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )

        state = _git_state(tmp_path)
        assert state == {}

    def test_detects_modified_and_untracked_files(self, tmp_path: Path) -> None:
        """_git_state returns entries for both modified tracked and new untracked files."""
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        tracked = tmp_path / "tracked.txt"
        tracked.write_text("original")
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )

        # Modify the tracked file and add an untracked file.
        tracked.write_text("modified")
        untracked = tmp_path / "new_file.py"
        untracked.write_text("# new")

        state = _git_state(tmp_path)
        assert state is not None
        assert "tracked.txt" in state
        assert "new_file.py" in state


# ---------------------------------------------------------------------------
# Unit tests: _changed_between
# ---------------------------------------------------------------------------


class TestChangedBetween:
    def test_empty_before_and_after(self) -> None:
        assert _changed_between({}, {}) == []

    def test_new_path_appears_in_after(self) -> None:
        result = _changed_between({}, {"new.py": "??"})
        assert result == ["new.py"]

    def test_changed_status_is_reported(self) -> None:
        before = {"file.py": "??"}
        after = {"file.py": " M"}
        result = _changed_between(before, after)
        assert result == ["file.py"]

    def test_unchanged_path_is_not_reported(self) -> None:
        before = {"file.py": " M"}
        after = {"file.py": " M"}
        result = _changed_between(before, after)
        assert result == []

    def test_result_is_sorted(self) -> None:
        before: dict[str, str] = {}
        after = {"zebra.py": "??", "alpha.py": "??", "middle.py": "??"}
        result = _changed_between(before, after)
        assert result == ["alpha.py", "middle.py", "zebra.py"]

    def test_detects_both_new_and_modified(self, tmp_path: Path) -> None:
        """Integration: real git repo — modified tracked file + new untracked file."""
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        tracked = tmp_path / "tracked.txt"
        tracked.write_text("original")
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )

        # Snapshot before changes.
        before = _git_state(tmp_path)
        assert before == {}

        # Make changes.
        tracked.write_text("modified")
        (tmp_path / "brand_new.py").write_text("# added")

        # Snapshot after changes.
        after = _git_state(tmp_path)
        assert after is not None

        changed = _changed_between(before, after)
        assert "tracked.txt" in changed
        assert "brand_new.py" in changed
        assert len(changed) == 2


# ---------------------------------------------------------------------------
# Integration test: execute_mandate inside a git repo
# ---------------------------------------------------------------------------


class TestExecuteMandateChangedFiles:
    def test_changed_files_empty_when_mock_engine_writes_nothing(
        self, tmp_path: Path, operator_layer: Path
    ) -> None:
        """execute_mandate with the no-op mock engine inside a git repo -> changed_files == []."""
        from alc.intake import load_blueprint, load_manifest
        from alc.runner import execute_mandate

        # Set up a minimal git repo in tmp_path.
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        seed = tmp_path / "seed.txt"
        seed.write_text("seed")
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", "seed.txt"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "seed"],
            check=True,
            capture_output=True,
        )

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

        # The mock engine writes no files, so the git state does not change.
        assert report.changed_files == []
