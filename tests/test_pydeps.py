# test_pydeps.py — Hermetic tests for alc.pydeps: the read-only readers that
# resolve a Python project's environment manager (lockfile -> runner prefix)
# and its locked package names, plus resolve_python_checks() — the piece that
# lets `alc init` scaffold `uv run pytest -q` LIVE instead of commenting out a
# bare `pytest` that only lives inside the project's .venv.
#
# Everything here is parse-only: no test executes a project command, mirroring
# the harvest safety invariant pydeps inherits.
from __future__ import annotations

from pathlib import Path

from alc.pydeps import locked_packages, python_runner, resolve_python_checks

_UV_LOCK_WITH_PYTEST = """\
version = 1

[[package]]
name = "iniconfig"
version = "2.0.0"

[[package]]
name = "pytest"
version = "9.1.1"
"""

_POETRY_LOCK_WITH_PYTEST = """\
[[package]]
name = "pytest"
version = "9.1.1"

[metadata]
lock-version = "2.0"
"""

_PIPFILE_LOCK_WITH_PYTEST = """\
{
    "default": {"requests": {"version": "==2.32.0"}},
    "develop": {"pytest": {"version": "==9.1.1"}}
}
"""


class TestPythonRunner:
    def test_uv_lock_resolves_to_uv_run(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("version = 1\n")
        assert python_runner(tmp_path) == ["uv", "run"]

    def test_poetry_lock_resolves_to_poetry_run(self, tmp_path: Path) -> None:
        (tmp_path / "poetry.lock").write_text("")
        assert python_runner(tmp_path) == ["poetry", "run"]

    def test_pdm_lock_resolves_to_pdm_run(self, tmp_path: Path) -> None:
        (tmp_path / "pdm.lock").write_text("")
        assert python_runner(tmp_path) == ["pdm", "run"]

    def test_pipfile_lock_resolves_to_pipenv_run(self, tmp_path: Path) -> None:
        (tmp_path / "Pipfile.lock").write_text("{}")
        assert python_runner(tmp_path) == ["pipenv", "run"]

    def test_no_lockfile_means_no_runner(self, tmp_path: Path) -> None:
        assert python_runner(tmp_path) == []

    def test_uv_wins_when_several_lockfiles_present(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("version = 1\n")
        (tmp_path / "poetry.lock").write_text("")
        assert python_runner(tmp_path) == ["uv", "run"]


class TestLockedPackages:
    def test_uv_lock_package_names_are_read(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text(_UV_LOCK_WITH_PYTEST)
        assert locked_packages(tmp_path) == frozenset({"iniconfig", "pytest"})

    def test_poetry_lock_package_names_are_read(self, tmp_path: Path) -> None:
        (tmp_path / "poetry.lock").write_text(_POETRY_LOCK_WITH_PYTEST)
        assert locked_packages(tmp_path) == frozenset({"pytest"})

    def test_pipfile_lock_merges_default_and_develop(self, tmp_path: Path) -> None:
        (tmp_path / "Pipfile.lock").write_text(_PIPFILE_LOCK_WITH_PYTEST)
        assert locked_packages(tmp_path) == frozenset({"requests", "pytest"})

    def test_package_names_are_pep503_normalized(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text(
            'version = 1\n\n[[package]]\nname = "Pytest_Cov"\nversion = "5.0"\n'
        )
        assert locked_packages(tmp_path) == frozenset({"pytest-cov"})

    def test_missing_lockfile_yields_empty_set(self, tmp_path: Path) -> None:
        assert locked_packages(tmp_path) == frozenset()

    def test_malformed_lockfile_yields_empty_set_never_raises(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("this is [ not toml")
        assert locked_packages(tmp_path) == frozenset()

    def test_malformed_pipfile_lock_yields_empty_set(self, tmp_path: Path) -> None:
        (tmp_path / "Pipfile.lock").write_text("not json")
        assert locked_packages(tmp_path) == frozenset()


class TestResolvePythonChecks:
    _BATTERY = [
        ("test", ["pytest", "-q"]),
        ("lint", ["ruff", "check", "."]),
    ]

    def test_locked_tool_gains_runner_prefix(self, tmp_path: Path) -> None:
        """pytest is IN uv.lock -> `uv run pytest -q`; ruff is NOT -> stays bare,
        so the PATH check still decides its fate (the honesty gate: never wrap a
        tool the lockfile cannot actually provide)."""
        (tmp_path / "uv.lock").write_text(_UV_LOCK_WITH_PYTEST)
        resolved = resolve_python_checks(self._BATTERY, tmp_path)
        assert resolved == [
            ("test", ["uv", "run", "pytest", "-q"]),
            ("lint", ["ruff", "check", "."]),
        ]

    def test_no_lockfile_is_identity(self, tmp_path: Path) -> None:
        assert resolve_python_checks(self._BATTERY, tmp_path) == self._BATTERY

    def test_malformed_lockfile_is_identity(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("this is [ not toml")
        assert resolve_python_checks(self._BATTERY, tmp_path) == self._BATTERY

    def test_original_battery_is_not_mutated(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text(_UV_LOCK_WITH_PYTEST)
        battery = [("test", ["pytest", "-q"])]
        resolve_python_checks(battery, tmp_path)
        assert battery == [("test", ["pytest", "-q"])]
