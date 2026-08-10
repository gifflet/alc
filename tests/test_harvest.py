# test_harvest.py — Hermetic tests for the read-only HARVEST layer (harvest.py):
# scanning a project for the check commands it ALREADY declares (package.json
# scripts, Makefile/justfile/Taskfile targets, pre-commit, tox/nox) so a future
# `alc onboard` can adopt them. harvest() never writes and NEVER executes a
# project command — every assertion here is against a returned HarvestReport.
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from alc.harvest import HarvestedCheck, HarvestReport, harvest


@pytest.fixture(autouse=True)
def _which_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `shutil.which` deterministic (everything on PATH) by default, so a
    test that does not care about availability is not host-dependent. Tests that
    assert on `available` re-patch it themselves."""
    monkeypatch.setattr("alc.harvest.shutil.which", lambda cmd: f"/usr/bin/{cmd}")


def _by_name(report: HarvestReport) -> dict[str, HarvestedCheck]:
    return {c.name: c for c in report.checks}


# ---------------------------------------------------------------------------
# package.json
# ---------------------------------------------------------------------------


class TestPackageJson:
    def test_only_checkish_scripts_are_harvested(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            '{"scripts": {"test": "jest", "lint": "eslint .", '
            '"build": "tsc", "dev": "vite"}}'
        )

        report = harvest(tmp_path)
        checks = _by_name(report)

        assert set(checks) == {"test", "lint", "build"}  # "dev" excluded
        assert "package.json" in report.scanned

    def test_npm_run_is_the_default_runner(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')

        check = _by_name(harvest(tmp_path))["test"]

        assert check.command == ["npm", "run", "test"]
        assert check.shell is None
        assert check.source == "package-json"
        assert check.source_path == "package.json"
        assert check.confidence == "high"

    def test_pnpm_runner_when_pnpm_lock_present(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")

        assert _by_name(harvest(tmp_path))["test"].command == ["pnpm", "run", "test"]

    def test_yarn_runner_when_yarn_lock_present(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
        (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n")

        assert _by_name(harvest(tmp_path))["test"].command == ["yarn", "test"]

    def test_tool_available_is_public_and_reflects_which(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`tool_available` is the ONE public availability lookup other modules
        (onboard) reuse instead of duplicating the which() dance."""
        from alc.harvest import tool_available

        monkeypatch.setattr(
            "alc.harvest.shutil.which", lambda cmd: "/bin/npm" if cmd == "npm" else None
        )
        assert tool_available(["npm", "test"]) is True
        assert tool_available(["pytest", "-q"]) is False
        assert tool_available(None, "npm test") is True
        assert tool_available(None, None) is False

    def test_available_reflects_shutil_which(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')

        monkeypatch.setattr(
            "alc.harvest.shutil.which", lambda cmd: "/bin/npm" if cmd == "npm" else None
        )
        assert _by_name(harvest(tmp_path))["test"].available is True

        monkeypatch.setattr("alc.harvest.shutil.which", lambda cmd: None)
        assert _by_name(harvest(tmp_path))["test"].available is False

    def test_write_mode_formatter_is_not_harvested(self, tmp_path: Path) -> None:
        # A `format`/`fmt` script is a write-mode formatter (`prettier --write`)
        # that MUTATES files and exits 0 regardless — as a check it always passes
        # and proves nothing. A formatter is not a gate, so harvest never adopts it.
        (tmp_path / "package.json").write_text(
            '{"scripts": {"format": "prettier --write \\"src/**/*.ts\\"", '
            '"fmt": "prettier --write .", "test": "jest"}}'
        )

        checks = _by_name(harvest(tmp_path))

        assert "format" not in checks
        assert "fmt" not in checks
        assert "test" in checks  # a real gate is still harvested

    def test_hyphen_and_colon_typecheck_variants_are_harvested(
        self, tmp_path: Path
    ) -> None:
        # Node's typecheck script has no canonical spelling: `type-check` and
        # `type:check` are the SAME gate as `typecheck` and must be adopted, not
        # missed. The runner keeps the exact script spelling so `npm run` resolves.
        (tmp_path / "package.json").write_text(
            '{"scripts": {"type-check": "tsc --noEmit"}}'
        )
        checks = _by_name(harvest(tmp_path))
        assert "type-check" in checks
        assert checks["type-check"].command == ["npm", "run", "type-check"]

        (tmp_path / "package.json").write_text(
            '{"scripts": {"type:check": "tsc --noEmit"}}'
        )
        commands = [c.command for c in harvest(tmp_path).checks]
        assert ["npm", "run", "type:check"] in commands


# ---------------------------------------------------------------------------
# Makefile / justfile / Taskfile — TARGET NAMES only, never recipe bodies
# ---------------------------------------------------------------------------


class TestTargetFiles:
    def test_makefile_targets(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text(
            ".PHONY: test lint\n"
            "test:\n\tpytest -q\n"
            "lint: ## run the linter\n\truff check .\n"
            "deploy:\n\t./deploy.sh\n"
        )

        report = harvest(tmp_path)
        checks = _by_name(report)

        assert set(checks) == {"test", "lint"}  # "deploy" excluded; ".PHONY" ignored
        assert checks["test"].command == ["make", "test"]
        assert checks["lint"].command == ["make", "lint"]
        assert checks["test"].source == "makefile"
        assert report.scanned == ["Makefile"]

    def test_justfile_recipes(self, tmp_path: Path) -> None:
        (tmp_path / "justfile").write_text(
            "test:\n    pytest -q\n"
            "lint:\n    ruff check .\n"
            "publish:\n    ./publish.sh\n"
        )

        checks = _by_name(harvest(tmp_path))

        assert set(checks) == {"test", "lint"}  # "publish" excluded
        assert checks["test"].command == ["just", "test"]
        assert checks["lint"].source == "justfile"

    def test_taskfile_tasks(self, tmp_path: Path) -> None:
        (tmp_path / "Taskfile.yml").write_text(
            "version: '3'\n"
            "tasks:\n"
            "  test:\n    cmds:\n      - go test ./...\n"
            "  vet:\n    cmds:\n      - go vet ./...\n"
            "  release:\n    cmds:\n      - ./release.sh\n"
        )

        checks = _by_name(harvest(tmp_path))

        assert set(checks) == {"test", "vet"}  # "release" excluded
        assert checks["test"].command == ["task", "test"]
        assert checks["vet"].source == "taskfile"


# ---------------------------------------------------------------------------
# pre-commit
# ---------------------------------------------------------------------------


class TestPreCommit:
    def test_single_run_all_files_check(self, tmp_path: Path) -> None:
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")

        report = harvest(tmp_path)

        assert len(report.checks) == 1
        check = report.checks[0]
        assert check.command == ["pre-commit", "run", "--all-files"]
        assert check.source == "pre-commit"
        assert check.source_path == ".pre-commit-config.yaml"


# ---------------------------------------------------------------------------
# tox / nox
# ---------------------------------------------------------------------------


class TestToxNox:
    def test_tox_envlist_becomes_one_check_per_env(self, tmp_path: Path) -> None:
        (tmp_path / "tox.ini").write_text("[tox]\nenvlist = py311, lint\n")

        checks = _by_name(harvest(tmp_path))

        assert set(checks) == {"py311", "lint"}
        assert checks["py311"].command == ["tox", "-e", "py311"]
        assert checks["lint"].command == ["tox", "-e", "lint"]
        assert checks["py311"].source == "tox"

    def test_nox_sessions_become_one_check_each(self, tmp_path: Path) -> None:
        (tmp_path / "noxfile.py").write_text(
            "import nox\n\n"
            "@nox.session\n"
            "def tests(session):\n    session.run('pytest')\n\n"
            '@nox.session(python="3.12")\n'
            "def lint(session):\n    session.run('ruff', 'check')\n"
        )

        checks = _by_name(harvest(tmp_path))

        assert set(checks) == {"tests", "lint"}
        assert checks["tests"].command == ["nox", "-s", "tests"]
        assert checks["lint"].command == ["nox", "-s", "lint"]
        assert checks["lint"].source == "nox"

    def test_slug_collisions_within_a_source_are_de_collided(self, tmp_path: Path) -> None:
        # Two DISTINCT tox envs that slugify to the same string ("py3-11") are
        # different commands, so BOTH survive dedup; the name de-collider then
        # keeps them uniquely named rather than dropping one.
        (tmp_path / "tox.ini").write_text("[tox]\nenvlist = py3.11, py3-11\n")

        report = harvest(tmp_path)
        names = [c.name for c in report.checks]
        commands = [c.command for c in report.checks]

        assert len(names) == len(set(names)) == 2  # unique names
        assert ["tox", "-e", "py3.11"] in commands
        assert ["tox", "-e", "py3-11"] in commands


# ---------------------------------------------------------------------------
# Dedup across sources
# ---------------------------------------------------------------------------


class TestDedup:
    def test_same_named_task_from_two_sources_is_listed_once(self, tmp_path: Path) -> None:
        # A `test` script and a `test` Makefile target are the SAME underlying
        # check; the dedup rule keeps the direct package-runner form (npm run
        # test) and drops the Makefile duplicate. A Makefile-only `lint` target
        # (no package.json counterpart) is NOT a duplicate and survives.
        (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
        (tmp_path / "Makefile").write_text("test:\n\tmake-test\nlint:\n\tmake-lint\n")

        checks = _by_name(harvest(tmp_path))

        assert set(checks) == {"test", "lint"}
        assert checks["test"].command == ["npm", "run", "test"]  # package-runner wins
        assert checks["lint"].command == ["make", "lint"]
        assert ["make", "test"] not in [c.command for c in checks.values()]


# ---------------------------------------------------------------------------
# Empty project
# ---------------------------------------------------------------------------


class TestEmptyProject:
    def test_no_known_files_yields_empty_report(self, tmp_path: Path) -> None:
        report = harvest(tmp_path)

        assert report.checks == []
        assert report.scanned == []
        assert report.skipped == []


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestMalformedFiles:
    def test_malformed_files_are_skipped_not_raised(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{ this is not valid json ")
        (tmp_path / "tox.ini").write_text("not valid ini at all")

        report = harvest(tmp_path)  # must NOT raise

        assert report.checks == []
        assert any("package.json" in entry for entry in report.skipped)
        assert any("tox.ini" in entry for entry in report.skipped)
        assert "package.json" not in report.scanned
        assert "tox.ini" not in report.scanned


# ---------------------------------------------------------------------------
# HARD SAFETY INVARIANT: harvest PARSES + shutil.which only; it NEVER executes
# a project command.
# ---------------------------------------------------------------------------


class TestSafetyNeverExecutes:
    def test_harvest_does_not_execute_any_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: object, **kwargs: object) -> object:
            raise AssertionError("harvest executed a project command")

        for attr in ("run", "Popen", "call", "check_call", "check_output"):
            monkeypatch.setattr(subprocess, attr, _boom)
        monkeypatch.setattr(os, "system", _boom)
        monkeypatch.setattr(os, "popen", _boom)

        # A project that declares checks in every supported source.
        (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
        (tmp_path / "Makefile").write_text("lint:\n\truff check .\n")
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        (tmp_path / "tox.ini").write_text("[tox]\nenvlist = py312\n")
        (tmp_path / "noxfile.py").write_text("@nox.session\ndef vet(session):\n    pass\n")

        report = harvest(tmp_path)  # patched exec surfaces would raise if touched

        assert report.checks  # work was actually done, purely by parsing
