"""The isolated branch must reach the run log.

`alc run --isolate` commits onto ``alc/<label>-<random>``. The name is
unguessable from the run alone, so without an event the UI can tell an operator
their change is committed but never where to read it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from alc import cli as cli_mod

_MANIFEST = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
engines:
  mock:
    type: mock
blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
"""

_CHORE = """\
---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
1. Make the smallest change that satisfies the task.
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".alc" / "blueprints").mkdir(parents=True)
    (repo / ".alc" / "flows").mkdir(parents=True)
    (repo / ".alc" / "manifest.yaml").write_text(_MANIFEST)
    (repo / ".alc" / "blueprints" / "chore.md").write_text(_CHORE)
    (repo / "README.md").write_text("hello\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _events(repo: Path) -> list[dict]:
    logs = sorted((repo / ".alc" / "runs").glob("*.jsonl"))
    assert logs, "the run wrote no event log"
    return [json.loads(line) for line in logs[-1].read_text().splitlines()]


def _args(**over) -> argparse.Namespace:
    base = dict(
        blueprint="chore",
        task="tidy",
        engine="mock",
        isolate=True,
        tier=None,
        primer=None,
        bundle=False,
        from_bundle=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


class _Engine:
    """A mock engine that optionally writes a file, so the worktree has (or has
    not) something to commit."""

    name = "mock"

    def __init__(self, *, change: bool) -> None:
        self.change = change

    def capabilities(self):
        from alc.engine import Capabilities

        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request):
        from alc.engine import EngineResult

        if self.change:
            (request.workdir / "touched.txt").write_text("changed\n")
        return EngineResult(ok=True, output_text="[mock] done")


def test_branch_reaches_the_run_log(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _Engine(change=True))
    monkeypatch.chdir(repo)

    assert cli_mod.cmd_run(_args()) == 0

    iso = [e for e in _events(repo) if e["event"] == "isolation_finished"]
    assert len(iso) == 1
    assert iso[0]["committed"] is True
    assert iso[0]["branch"].startswith("alc/run-")


def test_no_branch_when_nothing_changed(tmp_path: Path, monkeypatch) -> None:
    # committed:false must not carry a branch — a name with nothing on it would
    # send the operator to a diff that does not exist.
    repo = _repo(tmp_path)
    monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _Engine(change=False))
    monkeypatch.chdir(repo)

    cli_mod.cmd_run(_args())

    iso = [e for e in _events(repo) if e["event"] == "isolation_finished"]
    assert len(iso) == 1
    assert iso[0]["committed"] is False
    assert iso[0]["branch"] is None


class _InterruptingEngine(_Engine):
    """Writes, then the run is interrupted — exactly the Ctrl-C shape."""

    def run(self, request):
        (request.workdir / "touched.txt").write_text("changed\n")
        raise KeyboardInterrupt


def test_an_interrupted_run_still_reports_where_the_work_went(tmp_path: Path, monkeypatch, capsys) -> None:
    # The worktree's exit commits on the way out, so a branch exists whether the
    # run finished or not. Saying nothing leaves it to be met later by
    # `alc land` with no record of where it came from.
    repo = _repo(tmp_path)
    monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _InterruptingEngine(change=True))
    monkeypatch.chdir(repo)

    try:
        cli_mod.cmd_run(_args())
    except KeyboardInterrupt:
        pass  # re-raised for main() to turn into exit 130

    out = capsys.readouterr().out
    assert "Isolated changes committed on branch: alc/run-" in out

    iso = [e for e in _events(repo) if e["event"] == "isolation_finished"]
    assert len(iso) == 1, "the UI reads this event; without it there is no branch to name"
    assert iso[0]["committed"] is True

    # And the edits are NOT where the UI used to say they were.
    assert not (repo / "touched.txt").exists()


def test_the_interrupt_still_propagates(tmp_path: Path, monkeypatch) -> None:
    # Reporting the branch must not swallow the interrupt: Ctrl-C still stops.
    import pytest

    repo = _repo(tmp_path)
    monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _InterruptingEngine(change=True))
    monkeypatch.chdir(repo)

    with pytest.raises(KeyboardInterrupt):
        cli_mod.cmd_run(_args())
