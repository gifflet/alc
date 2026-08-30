"""A committed branch is not the same as a verified one.

An interrupted run whose checks failed still commits its worktree, so the branch
exists and looks exactly like one from a run that passed. The Inbox offered both
with a Land button. The signal to tell them apart was already on disk: an
isolated `alc run` archives `<branch>.report.json` only when the report
succeeded.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from alc import cli as cli_mod
from alc.ui import inbox as inbox_mod
from alc.ui import service


def run(*argv: str) -> None:
    args = cli_mod._build_parser().parse_args(list(argv))
    {"init": cli_mod.cmd_init}[args.command](args)


def _project(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True)
    (root / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True, capture_output=True)
    monkeypatch.chdir(root)
    run("init", "--engine", "mock")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "alc"], cwd=root, check=True, capture_output=True)
    return root


def _branch(root: Path, name: str) -> None:
    """Create an alc/* branch with one commit, the way an isolated run leaves one.

    Returns to the default branch by asking git what it is. An earlier version
    tried `checkout main` "or" `checkout master`; CompletedProcess is always
    truthy, so the fallback never ran and the test stayed on the alc branch —
    which then made every later branch look already merged.
    """
    default = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", "-b", name], cwd=root, check=True, capture_output=True)
    (root / f"{name.replace('/', '-')}.txt").write_text("work\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", name], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-q", default], cwd=root, check=True, capture_output=True)


def test_a_run_branch_with_an_archived_report_is_verified(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path, monkeypatch)
    _branch(root, "alc/run-aaaa1111")
    (root / ".alc" / "runs").mkdir(parents=True, exist_ok=True)
    (root / ".alc" / "runs" / "alc-run-aaaa1111.report.json").write_text("{}")

    entry = next(b for b in service.list_branches(root)["branches"] if b["name"].endswith("aaaa1111"))
    assert entry["verified"] is True


def test_a_run_branch_without_one_is_not_verified(tmp_path, monkeypatch) -> None:
    # The reported case: interrupted at a failing check, committed anyway.
    root = _project(tmp_path, monkeypatch)
    _branch(root, "alc/run-bbbb2222")

    entry = next(b for b in service.list_branches(root)["branches"] if b["name"].endswith("bbbb2222"))
    assert entry["verified"] is False


def test_other_producers_make_no_claim(tmp_path, monkeypatch) -> None:
    # flow/tick/fanout never archive a branch-named report, so absence proves
    # nothing. Warning on them would put a false alarm on every drained task.
    root = _project(tmp_path, monkeypatch)
    for name in ("alc/flow-cccc3333", "alc/tick-dddd4444", "alc/fanout-x-eeee5555"):
        _branch(root, name)

    by_name = {b["name"]: b for b in service.list_branches(root)["branches"]}
    for name in ("alc/flow-cccc3333", "alc/tick-dddd4444", "alc/fanout-x-eeee5555"):
        assert by_name[name]["verified"] is None, name


def test_a_project_outside_git_still_degrades_cleanly(tmp_path) -> None:
    assert service.list_branches(tmp_path) == {"available": False, "branches": []}


def test_the_inbox_reason_says_the_checks_did_not_pass(tmp_path, monkeypatch) -> None:
    """The wording is produced in Python, so it is tested in Python.

    The frontend asserts this string too, but against a fixture I wrote. Only
    this test sees what the server actually sends.
    """
    root = _project(tmp_path, monkeypatch)
    _branch(root, "alc/run-ffff6666")

    item = next(i for i in inbox_mod._branches(root) if i["branch"].endswith("ffff6666"))
    assert item["verified"] is False
    assert "checks did not pass" in item["reason"]
    assert "ready to land" not in item["reason"]


def test_a_verified_branch_keeps_the_original_wording(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path, monkeypatch)
    _branch(root, "alc/run-7777aaaa")
    (root / ".alc" / "runs").mkdir(parents=True, exist_ok=True)
    (root / ".alc" / "runs" / "alc-run-7777aaaa.report.json").write_text("{}")

    item = next(i for i in inbox_mod._branches(root) if i["branch"].endswith("7777aaaa"))
    assert item["verified"] is True
    assert item["reason"] == "run work ready to land"


# ---------------------------------------------------------------------------
# The CLI has the same surface, and `--all` is the more dangerous one: it merges
# in bulk with no per-branch decision.
# ---------------------------------------------------------------------------


def _land(*argv: str) -> int:
    args = cli_mod._build_parser().parse_args(["land", *argv])
    return cli_mod.cmd_land(args)


def test_land_listing_marks_the_branch_that_never_passed(tmp_path, monkeypatch, capsys) -> None:
    root = _project(tmp_path, monkeypatch)
    _branch(root, "alc/run-1111aaaa")
    _branch(root, "alc/run-2222bbbb")
    (root / ".alc" / "runs").mkdir(parents=True, exist_ok=True)
    (root / ".alc" / "runs" / "alc-run-1111aaaa.report.json").write_text("{}")

    _land()
    out = capsys.readouterr().out
    assert "alc/run-1111aaaa   (run)\n" in out, "a verified branch keeps its plain line"
    assert "alc/run-2222bbbb   (run)  ← checks did not pass" in out


def test_land_all_warns_before_merging_unverified_work(tmp_path, monkeypatch, capsys) -> None:
    root = _project(tmp_path, monkeypatch)
    _branch(root, "alc/run-3333cccc")

    _land("--all")
    err = capsys.readouterr().err
    assert "checks did NOT pass" in err
    assert "alc/run-3333cccc" in err


def test_land_all_stays_quiet_when_every_branch_passed(tmp_path, monkeypatch, capsys) -> None:
    # The warning must be about this case only. Crying wolf on every drain would
    # train the operator to ignore it.
    root = _project(tmp_path, monkeypatch)
    _branch(root, "alc/run-4444dddd")
    (root / ".alc" / "runs").mkdir(parents=True, exist_ok=True)
    (root / ".alc" / "runs" / "alc-run-4444dddd.report.json").write_text("{}")

    _land("--all")
    assert "checks did NOT pass" not in capsys.readouterr().err


def test_land_json_carries_the_field(tmp_path, monkeypatch, capsys) -> None:
    import json as _json

    root = _project(tmp_path, monkeypatch)
    _branch(root, "alc/run-5555eeee")
    capsys.readouterr()  # drain init's output; json.loads cannot skip a prefix

    _land("--json")
    entries = _json.loads(capsys.readouterr().out)
    assert entries[0]["verified"] is False
