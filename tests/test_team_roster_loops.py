"""The roster reports the disk, not the pack a member came from.

Retiring a member MOVES its loop into `loops/retired/`. The roster built its
loop list from `pack_files` — the pack definition — so a retired loop kept being
listed, with a state, for a file that was no longer there. Both `alc team list`
and the web UI showed it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from alc import cli as cli_mod
from alc.ui import service


# main() dispatches on args.command with an if/elif chain and calls sys.exit;
# the cmd_* functions are the testable unit.
def run(*argv: str) -> None:
    """Parse one command line and call the cmd_* function it names."""
    args = cli_mod._build_parser().parse_args(list(argv))
    fn = {"init": cli_mod.cmd_init, "team": cli_mod.cmd_team}[args.command]
    fn(args)


def test_a_retired_loop_leaves_the_roster(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    monkeypatch.chdir(root)
    run("init", "--engine", "mock")
    run("team", "hire", "sweeper")

    before = service.team_roster(root)
    sweeper = next(m for m in before["members"] if m["archetype"] == "sweeper")
    assert [lp["name"] for lp in sweeper["loops"]] == ["sweep"], "hired sweeper should have its loop"

    run("team", "retire", "sweeper")

    after = service.team_roster(root)
    sweeper = next(m for m in after["members"] if m["archetype"] == "sweeper")
    # The file is in loops/retired/ now. Listing it as a live loop is the roster
    # reporting a state the project is not in.
    assert sweeper["loops"] == []
    # The member itself stays: retire never touches blueprints/flows/specialists.
    assert sweeper["files"], "retire must not remove the member from the roster"
    assert (root / ".alc" / "loops" / "retired" / "sweep.yaml").exists()


def test_a_pack_with_no_loops_reports_none(tmp_path: Path, monkeypatch) -> None:
    # builder ships zero loops, so retiring it can never do anything — the UI
    # needs this to be visible rather than discovered by pressing a dead button.
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    monkeypatch.chdir(root)
    run("init", "--engine", "mock")
    run("team", "hire", "builder")

    roster = service.team_roster(root)
    builder = next(m for m in roster["members"] if m["archetype"] == "builder")
    assert builder["loops"] == []
    assert service.team_retire(root, "builder") == {"moved": []}
