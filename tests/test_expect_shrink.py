# test_expect_shrink.py — Hermetic tests for T4: `expect: shrink` on the
# Blueprint, plus the net-lines column on `alc runs list`. Diffstat's (Phase 2)
# first consumers, alongside archetype's mirror for the RunReport side.
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from alc.cli import cmd_runs
from alc.engine import Capabilities, EngineResult
from alc.events import bind_run_log
from alc.intake import load_blueprint
from alc.models import Blueprint, Check, Manifest
from alc.runner import execute_mandate
from alc.runs import list_runs

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


def _init_repo(repo: Path) -> None:
    import subprocess

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
    import subprocess

    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True
    )


class _WriteFileEngine:
    """A fake engine that overwrites one tracked file with new content."""

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


# ---------------------------------------------------------------------------
# (a) Front-matter round-trip
# ---------------------------------------------------------------------------


class TestLoadBlueprintExpect:
    def test_expect_shrink_round_trip(self, tmp_path: Path) -> None:
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "refactor.md").write_text(
            """\
---
name: refactor
purpose: Simplify.
compute_tier: standard
expect: shrink
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Do the task.
"""
        )
        bp = load_blueprint(blueprints_dir, "refactor")
        assert bp.expect == "shrink"

    def test_absent_expect_is_none(self, tmp_path: Path) -> None:
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "chore.md").write_text(
            """\
---
name: chore
purpose: A chore.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Do the task.
"""
        )
        bp = load_blueprint(blueprints_dir, "chore")
        assert bp.expect is None


# ---------------------------------------------------------------------------
# (b) execute_mandate: the warn is advisory, never blocks, and lands both on
# RunReport.warnings and the run log.
# ---------------------------------------------------------------------------


class TestExecuteMandateShrinkWarning:
    def _bp(self, expect: str | None) -> Blueprint:
        return Blueprint(
            name="refactor",
            purpose="Simplify.",
            checks=[Check(name="smoke", command=["true"])],
            workflow="# do the task",
            expect=expect,
        )

    def test_warns_when_expect_shrink_and_codebase_grew(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _init_repo(tmp_path)
        (tmp_path / "f.txt").write_text("line1\n")
        _commit_all(tmp_path, "seed")

        engine = _WriteFileEngine("f.txt", "line1\nline2\nline3\nline4\n")
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=self._bp("shrink"),
            directive="# test\ndo it",
            workdir=tmp_path,
        )
        assert report.diffstat.adds - report.diffstat.dels == 3
        assert len(report.warnings) == 1
        assert "expect: shrink" in report.warnings[0]
        assert "grew" in report.warnings[0]
        # Advisory only — never fails the run (checks still pass).
        assert report.success is True

    def test_no_warning_when_expect_is_none_even_if_grew(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _init_repo(tmp_path)
        (tmp_path / "f.txt").write_text("line1\n")
        _commit_all(tmp_path, "seed")

        engine = _WriteFileEngine("f.txt", "line1\nline2\nline3\n")
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=self._bp(None),
            directive="# test\ndo it",
            workdir=tmp_path,
        )
        assert report.warnings == []

    def test_no_warning_when_net_shrank(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _init_repo(tmp_path)
        (tmp_path / "f.txt").write_text("line1\nline2\nline3\nline4\n")
        _commit_all(tmp_path, "seed")

        engine = _WriteFileEngine("f.txt", "line1\n")
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=self._bp("shrink"),
            directive="# test\ndo it",
            workdir=tmp_path,
        )
        assert report.diffstat.adds - report.diffstat.dels < 0
        assert report.warnings == []

    def test_no_warning_when_diffstat_is_none(self, tmp_path: Path) -> None:
        """Outside a git repo diffstat is None — nothing to judge, so no warn."""
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=self._bp("shrink"),
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.diffstat is None
        assert report.warnings == []

    def test_warning_is_recorded_in_the_run_log(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _init_repo(tmp_path)
        (tmp_path / "f.txt").write_text("line1\n")
        _commit_all(tmp_path, "seed")

        engine = _WriteFileEngine("f.txt", "line1\nline2\nline3\n")
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        run_log = tmp_path / "run.jsonl"
        with bind_run_log(run_log):
            execute_mandate(
                manifest=_MINIMAL_MANIFEST,
                blueprint=self._bp("shrink"),
                directive="# test\ndo it",
                workdir=tmp_path,
            )

        events = [json.loads(ln) for ln in run_log.read_text().splitlines() if ln.strip()]
        warning_events = [e for e in events if e["event"] == "run_warning"]
        assert len(warning_events) == 1
        assert "expect: shrink" in warning_events[0]["message"]

        finished = next(e for e in events if e["event"] == "mandate_finished")
        assert finished["diffstat"]["adds"] == 2
        assert finished["diffstat"]["dels"] == 0


# ---------------------------------------------------------------------------
# (c) The Sweeper pack's `refactor` Blueprint declares expect: shrink.
# ---------------------------------------------------------------------------


class TestSweeperRefactorDeclaresShrink:
    def test_refactor_blueprint_declares_expect_shrink(self) -> None:
        from alc.packs import pack_files

        content = pack_files("sweeper", stacks=[])[".alc/blueprints/refactor.md"]
        assert "expect: shrink" in content

    def test_refactor_blueprint_loads_with_expect_shrink(self, tmp_path: Path) -> None:
        from alc.packs import pack_files

        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        content = pack_files("sweeper", stacks=[])[".alc/blueprints/refactor.md"]
        (blueprints_dir / "refactor.md").write_text(content)

        bp = load_blueprint(blueprints_dir, "refactor")
        assert bp.expect == "shrink"


# ---------------------------------------------------------------------------
# (d) `alc runs list` net-lines column: runs.py's list_runs() + the CLI print.
# ---------------------------------------------------------------------------


def _write_run(runs_dir: Path, stem: str, events: list[dict]) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(e) + "\n" for e in events)
    path = runs_dir / f"{stem}.jsonl"
    path.write_text(body)
    return path


class TestListRunsNetLines:
    def test_none_when_no_mandate_finished_event(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_run(runs_dir, "20260101T000000-run-x-aaaaaa", [{"event": "mandate_started"}])

        result = list_runs(runs_dir, stale_after=1e9)
        assert result["runs"][0]["net_lines"] is None

    def test_none_when_diffstat_is_null(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_run(
            runs_dir,
            "20260101T000000-run-x-aaaaaa",
            [{"event": "mandate_finished", "diffstat": None}],
        )

        result = list_runs(runs_dir, stale_after=1e9)
        assert result["runs"][0]["net_lines"] is None

    def test_computes_adds_minus_dels(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_run(
            runs_dir,
            "20260101T000000-run-x-aaaaaa",
            [{"event": "mandate_finished", "diffstat": {"adds": 5, "dels": 2, "files_deleted": 0}}],
        )

        result = list_runs(runs_dir, stale_after=1e9)
        assert result["runs"][0]["net_lines"] == 3

    def test_sums_across_multiple_stages_in_a_flow(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_run(
            runs_dir,
            "20260101T000000-flow-x-aaaaaa",
            [
                {"event": "flow_started"},
                {"event": "mandate_finished", "diffstat": {"adds": 5, "dels": 2, "files_deleted": 0}},
                {"event": "mandate_finished", "diffstat": {"adds": 1, "dels": 10, "files_deleted": 1}},
                {"event": "flow_finished"},
            ],
        )

        result = list_runs(runs_dir, stale_after=1e9)
        assert result["runs"][0]["net_lines"] == 3 + (1 - 10)


def _ns(**overrides) -> argparse.Namespace:
    defaults = {
        "runs_action": "list",
        "limit": 50,
        "offset": 0,
        "json": False,
        "stem": None,
        "lines": 20,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdRunsListNetLinesColumn:
    def test_human_output_shows_net_lines(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        runs_dir = operator_layer / "runs"
        _write_run(
            runs_dir,
            "20260101T000000-run-x-aaaaaa",
            [{"event": "mandate_finished", "diffstat": {"adds": 5, "dels": 8, "files_deleted": 1}}],
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="list")) == 0
        out = capsys.readouterr().out
        assert "net-lines=-3" in out

    def test_human_output_shows_n_a_with_no_diffstat(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        runs_dir = operator_layer / "runs"
        _write_run(runs_dir, "20260101T000000-run-x-aaaaaa", [{"event": "mandate_started"}])
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="list")) == 0
        out = capsys.readouterr().out
        assert "net-lines=n/a" in out

    def test_json_output_includes_net_lines_field(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        runs_dir = operator_layer / "runs"
        _write_run(
            runs_dir,
            "20260101T000000-run-x-aaaaaa",
            [{"event": "mandate_finished", "diffstat": {"adds": 5, "dels": 2, "files_deleted": 0}}],
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="list", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["runs"][0]["net_lines"] == 3

    def test_existing_kind_status_substring_still_present(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        """The net-lines column must not disturb the pre-existing `(kind, status)` shape."""
        runs_dir = operator_layer / "runs"
        _write_run(
            runs_dir,
            "20260101T000000-flow-done-aaaaaa",
            [{"event": "flow_started"}, {"event": "flow_finished"}],
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="list")) == 0
        out = capsys.readouterr().out
        assert "(flow, finished)" in out
