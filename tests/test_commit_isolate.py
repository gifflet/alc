# test_commit_isolate.py — CLI test for `alc flow --isolate` on a committing flow.
#
# T5: `cmd_flow` mirrors the committing-demand path `queue.py` already runs in
# production (queue.py:345-424) — the worktree exit-commit owns the SINGLE
# commit (rendered `flow.commit.message`, `.alc/` excluded), `skip_commit=True`
# stops the FlowRunner from also committing, and `commit_on_exit` is gated on
# the flow's success so a failed run discards the branch. A flow with no
# `commit:` block must keep today's exact (byte-identical) isolate behavior.
# Fully hermetic: local git repo in tmp_path + Mock engine.
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from alc.cli import cmd_flow

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

_CHORE_PASSING = """\
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

_CHORE_FAILING = """\
---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
  - name: always-fail
    command: ["false"]
---
# Workflow
1. Make the smallest change that satisfies the task.
"""

_DEMAND_FLOW = """\
name: demand
description: A unit of demand work that commits on success.
stages:
  - name: do
    blueprint: chore
commit:
  enabled: true
  message: "feat(auto): {task}"
"""

# A non-committing isolate flow (no commit: block) for the byte-identity check.
_SHIP_FLOW = """\
name: ship
description: A non-committing flow.
stages:
  - name: do
    blueprint: chore
"""


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@alc.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "ALC Test"],
        check=True,
        capture_output=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True
    )


def _build_repo(tmp_path: Path, chore: str) -> Path:
    """Build a git repo with an operator layer (demand + ship flows), seeded and
    committed; return the repo path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    # A tracked `.alc/` file so a stage that mutates it can prove the exclude.
    (alc / "state.txt").write_text("seed state\n")
    (alc / "manifest.yaml").write_text(_MANIFEST)
    (alc / "blueprints" / "chore.md").write_text(chore)
    (alc / "flows" / "demand.yaml").write_text(_DEMAND_FLOW)
    (alc / "flows" / "ship.yaml").write_text(_SHIP_FLOW)
    _commit_all(repo, "seed operator layer")
    return repo


def _write_files_engine(files: dict[str, str]):
    """Return a MockEngine-like class writing each rel_path->content into the
    request workdir on every turn."""
    from alc.engine import Capabilities, EngineResult

    class _WriteFilesEngine:
        name = "mock"

        def capabilities(self) -> Capabilities:
            return Capabilities()

        def health_check(self) -> bool:
            return True

        def run(self, request):
            for rel_path, content in files.items():
                dst = request.workdir / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content)
            return EngineResult(ok=True, output_text="[mock] wrote files")

    return _WriteFilesEngine


def _branch_tree_files(repo: Path, branch: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", branch],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def _list_branches(repo: Path, pattern: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", pattern],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.lstrip("* ").strip() for line in result.stdout.splitlines() if line.strip()]


def _flow_ns(**overrides) -> argparse.Namespace:
    defaults = {
        "flow_name": "demand",
        "task": "ship the widget",
        "engine": "mock",
        "isolate": True,
        "primer": None,
        "bundle": False,
        "from_bundle": None,
        "tier": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# A committing flow (commit.enabled) + --isolate SUCCEEDS: exactly ONE commit,
# the demand's rendered message, `.alc/` excluded, no refusal.
# ---------------------------------------------------------------------------


class TestCommittingFlowIsolateSuccess:
    def test_commits_once_and_excludes_alc(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        repo = _build_repo(tmp_path, chore=_CHORE_PASSING)
        engine = _write_files_engine(
            {"feature.txt": "the feature\n", ".alc/state.txt": "mutated by agent\n"}
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        exit_code = cmd_flow(_flow_ns())

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "not yet supported" not in out
        assert "Isolated changes committed on branch" in out

        # Exactly one non-merge commit carrying the rendered demand message.
        rev = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--all", "--no-merges", "--grep",
             "^feat(auto): ship the widget$"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert len(rev) == 1
        commit = rev[0]

        tree = _branch_tree_files(repo, commit)
        assert "feature.txt" in tree
        # `.alc/state.txt` is tracked, but its mutation must NOT be committed.
        show = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit}:.alc/state.txt"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert show.stdout == "seed state\n"


# ---------------------------------------------------------------------------
# A committing flow + --isolate FAILS: the worktree/branch is discarded.
# ---------------------------------------------------------------------------


class TestCommittingFlowIsolateFailure:
    def test_failure_discards_the_worktree(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING)
        engine = _write_files_engine({"feature.txt": "the feature\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        exit_code = cmd_flow(_flow_ns())

        assert exit_code == 1
        out = capsys.readouterr().out
        assert "No changes were made; nothing to isolate." in out
        assert _list_branches(repo, "alc/flow-*") == []
        # The demand's file change never landed anywhere (the worktree is gone).
        assert not (repo / "feature.txt").exists()


# ---------------------------------------------------------------------------
# Byte-identity: a NON-committing isolate flow still commits INCLUDING `.alc/`
# (exclude_paths=() default) — proving the gate only changes behavior for a
# flow that actually declares a commit block.
# ---------------------------------------------------------------------------


class TestNonCommittingFlowIsolateByteIdentical:
    def test_still_commits_including_alc(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        repo = _build_repo(tmp_path, chore=_CHORE_PASSING)
        engine = _write_files_engine(
            {"feature.txt": "the feature\n", ".alc/note.txt": "loop state\n"}
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        exit_code = cmd_flow(_flow_ns(flow_name="ship", task="tidy up"))

        assert exit_code == 0
        assert "Isolated changes committed on branch" in capsys.readouterr().out

        branches = _list_branches(repo, "alc/flow-*")
        assert len(branches) == 1
        tree = _branch_tree_files(repo, branches[0])
        assert "feature.txt" in tree
        assert ".alc/note.txt" in tree
