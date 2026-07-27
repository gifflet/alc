# test_env_refresh_drain.py — End-to-end drain proof that the env-refresh fix makes
# "checks are law" hold for dependency bumps.
#
# The scenario is the deps-refresh loop's false green: a gitignored node_modules is
# `link:`-shared into the worktree, a run bumps package.json, and the checks would
# otherwise run against the STALE, already-installed packages — so a breaking bump
# passes green. With the fix, ALC materializes an ISOLATED clone of node_modules and
# runs the ecosystem install BEFORE the checks, so the checks test the NEW versions.
#
# Hermetic: a real local git repo in tmp_path, a MockEngine scripted to bump
# package.json, and a stub `sh -c` "install" that rewrites the dep + lockfile. No
# real model, no network.
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from alc import queue as queue_mod
from alc.intake import load_manifest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@alc.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "ALC Test"],
        check=True,
        capture_output=True,
    )


def _commit_all(root: Path, message: str = "init") -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message], check=True, capture_output=True
    )


_MANIFEST_TMPL = """\
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
queue_dir: .alc/queue
generate_commit_messages: false
worktree_provision:
  - link: node_modules
    refresh:
{refresh_items}
    when_changed: [package.json, package-lock.json]
"""

_BUMP_TMPL = """\
---
name: bump
purpose: Bump a dependency.
compute_tier: standard
max_repairs: 0
checks:
  - name: api-compat
    shell: {check_shell}
---
# Workflow
Bump the dependency.
"""

_FLOW = """\
name: deps
description: Bump a dependency.
stages:
  - name: bump
    blueprint: bump
commit:
  enabled: true
  message: "chore(deps): {name}"
"""


def _refresh_items(argv: list[str]) -> str:
    # Render the refresh argv as a YAML block sequence, JSON-quoting each item so a
    # shell one-liner with spaces / `;` / `>` stays a single valid scalar.
    return "\n".join(f"      - {json.dumps(a)}" for a in argv)


def _setup_repo(
    tmp_path: Path,
    check_shell: str,
    refresh_argv: list[str],
) -> Path:
    """Build a git repo with a gitignored (stale) node_modules, a Node dep manifest,
    and a committing `deps` flow whose `bump` blueprint runs *check_shell*."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git(repo)

    # A gitignored, already-installed node_modules holding the STALE API surface.
    # The no-slash form matches the provisioned SYMLINK too (a `node_modules/`
    # directory-only pattern would leave the link untracked and trip the committing
    # flow's clean-tree guard — an orthogonal gitignore quirk, not this fix).
    (repo / ".gitignore").write_text("node_modules\n")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "lib.txt").write_text("oldAPI\n")

    # A tracked dependency manifest the engine will bump.
    (repo / "package.json").write_text('{"v": "1"}\n')

    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(
        _MANIFEST_TMPL.format(refresh_items=_refresh_items(refresh_argv))
    )
    (alc / "blueprints" / "bump.md").write_text(
        _BUMP_TMPL.format(check_shell=json.dumps(check_shell))
    )
    (alc / "flows" / "deps.yaml").write_text(_FLOW)

    _commit_all(repo)  # commits .gitignore + .alc + package.json; node_modules stays untracked
    return repo


def _bumping_engine(change: str = "package.json"):
    """A MockEngine-like engine that makes *change* on every turn."""
    from alc.engine import Capabilities, EngineResult

    class _Engine:
        name = "mock"

        def capabilities(self) -> Capabilities:
            return Capabilities()

        def health_check(self) -> bool:
            return True

        def run(self, request):
            if change == "package.json":
                (request.workdir / "package.json").write_text('{"v": "2"}\n')
            else:
                target = request.workdir / change
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("edited\n")
            return EngineResult(ok=True, output_text="[mock] bumped")

    return _Engine()


def _enqueue_deps_task(repo: Path) -> None:
    queue_dir = repo / ".alc" / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "t1.yaml").write_text(
        'flow: deps\ntask: "bump the dep to a breaking major"\nengine: mock\nisolate: true\n'
    )


def _install_script(tmp_path: Path, new_api: str = "newAPI") -> tuple[list[str], Path]:
    """A stub 'npm install': rewrite the dep's API surface + the lockfile, and record
    that it ran into a log OUTSIDE the repo (so its presence/absence is observable
    after the worktree is torn down)."""
    log = tmp_path / "refresh-ran.log"
    cmd = (
        f"echo {new_api} > node_modules/lib.txt; "
        f"echo locked-v2 > package-lock.json; "
        f"echo ran >> {log}"
    )
    return ["sh", "-c", cmd], log


def _drain(repo: Path, monkeypatch, engine) -> list:
    monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)
    operator_layer = repo / ".alc"
    manifest = load_manifest(operator_layer)
    return queue_mod.process_queue(manifest, operator_layer)


def _git_show(repo: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "show", ref],
        capture_output=True,
        text=True,
    ).stdout


# ---------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------


class TestEnvRefreshDrain:
    def test_false_green_is_killed(self, tmp_path: Path, monkeypatch) -> None:
        # The check passes against the STALE (oldAPI) node_modules — the exact false
        # green that landed green before this fix. After the fix the refresh installs
        # the NEW version (newAPI), the check correctly FAILS, and the branch is
        # discarded.
        refresh_argv, log = _install_script(tmp_path)
        repo = _setup_repo(
            tmp_path,
            check_shell="grep -q oldAPI node_modules/lib.txt",
            refresh_argv=refresh_argv,
        )
        _enqueue_deps_task(repo)

        results = _drain(repo, monkeypatch, _bumping_engine())

        assert len(results) == 1
        result = results[0]
        # The refresh DID fire (the run bumped package.json)...
        assert log.exists()
        # ...and the check now fails against the refreshed env -> the run fails and
        # nothing lands (before the fix this passed green and the branch landed).
        assert result.success is False
        assert result.branch is None
        assert result.merged is not True

    def test_passing_bump_lands_with_refreshed_lockfile(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # The check requires the NEW API (newAPI) — it fails against the stale env
        # and passes only once the refresh has installed the new version. The landed
        # commit carries the bumped manifest AND the refreshed lockfile.
        refresh_argv, log = _install_script(tmp_path)
        repo = _setup_repo(
            tmp_path,
            check_shell="grep -q newAPI node_modules/lib.txt",
            refresh_argv=refresh_argv,
        )
        _enqueue_deps_task(repo)

        results = _drain(repo, monkeypatch, _bumping_engine())

        result = results[0]
        assert log.exists()
        assert result.success is True
        assert result.merged is True
        # The merged commit (now HEAD) contains the bumped manifest AND the
        # refreshed lockfile the install produced.
        head_pkg = _git_show(repo, "HEAD:package.json")
        head_lock = _git_show(repo, "HEAD:package-lock.json")
        assert '"v": "2"' in head_pkg
        assert "locked-v2" in head_lock

    def test_operator_deps_are_isolated_from_the_install(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # The install rewrites node_modules/lib.txt to newAPI INSIDE the worktree's
        # isolated clone; the operator's shared node_modules must be byte-identical
        # after the drain (materialize_isolated broke the symlink first).
        refresh_argv, _log = _install_script(tmp_path)
        repo = _setup_repo(
            tmp_path,
            check_shell="grep -q newAPI node_modules/lib.txt",
            refresh_argv=refresh_argv,
        )
        _enqueue_deps_task(repo)

        _drain(repo, monkeypatch, _bumping_engine())

        assert (repo / "node_modules" / "lib.txt").read_text() == "oldAPI\n"

    def test_non_deps_task_never_refreshes(self, tmp_path: Path, monkeypatch) -> None:
        # The run changes a source file, not the dependency manifest — the refresh
        # must never fire (the scope guard), and the stale-passing check succeeds.
        refresh_argv, log = _install_script(tmp_path)
        repo = _setup_repo(
            tmp_path,
            check_shell="grep -q oldAPI node_modules/lib.txt",
            refresh_argv=refresh_argv,
        )
        _enqueue_deps_task(repo)

        results = _drain(repo, monkeypatch, _bumping_engine(change="src/foo.txt"))

        assert results[0].success is True
        # The refresh never ran -> node_modules was never materialized (stayed a
        # symlink), and its log was never written.
        assert not log.exists()
        assert (repo / "node_modules" / "lib.txt").read_text() == "oldAPI\n"

    def test_refresh_failure_surfaces_in_the_report(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # A non-zero install fails the demand with `env-refresh` in the report — no
        # crash, and the checks are never run against the broken env.
        repo = _setup_repo(
            tmp_path,
            check_shell="true",  # would pass — but must never be reached
            refresh_argv=["sh", "-c", "echo install-boom >&2; exit 1"],
        )
        _enqueue_deps_task(repo)

        results = _drain(repo, monkeypatch, _bumping_engine())

        result = results[0]
        assert result.success is False
        assert result.branch is None
        # `env-refresh` is the failing check recorded in the stage's report.
        failed_names = {
            name
            for stage in result.report.stages
            for attempt in stage.attempts
            for name in attempt.failed_checks
        }
        assert "env-refresh" in failed_names
