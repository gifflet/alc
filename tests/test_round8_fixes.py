# test_round8_fixes.py — dogfood round 8's findings, pinned with their
# regression guards: every fix here must ALSO prove the old path unchanged.
#
# 32: a failure lineage can be dismissed without a retry (and only then).
# 34: pack blueprints target a DECLARED check_set on onboarded manifests —
#     and stay byte-identical on manifests that declare the stack set.
# 38: an isolated specialist task resolves an UNCOMMITTED specialist from the
#     project root instead of raising FileNotFoundError from the worktree.
# 39: signals are provisioned into worktrees; declared provisions untouched.
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest
import yaml

from alc.intake import load_manifest
from alc.models import ProvisionSpec
from alc.packs import pack_files, remove_pack, retarget_pack_content, split_pack_files
from alc.queue import dismiss_failure, outstanding_failures, process_queue
from alc.scaffold import scaffold
from alc.worktree import IsolatedWorktree, runtime_provisions


def _git(root: Path, *argv: str) -> None:
    subprocess.run(["git", *argv], cwd=root, check=True, capture_output=True)


def _git_layer(root: Path) -> None:
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


# ---------------------------------------------------------------------------
# 34 — check_set retargeting
# ---------------------------------------------------------------------------


class TestCheckSetRetarget:
    def _onboarded_project(self, tmp_path: Path) -> Path:
        """A python-stack project whose manifest declares only harvested sets."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
        scaffold(tmp_path)
        manifest_file = tmp_path / ".alc" / "manifest.yaml"
        data = yaml.safe_load(manifest_file.read_text())
        # The onboard shape: the stack-named set is GONE; 'project' carries the
        # real battery, 'security' is declared but empty.
        data["check_sets"] = {
            "project": [{"name": "test", "command": ["true"]}],
            "security": [],
        }
        manifest_file.write_text(yaml.safe_dump(data))
        return tmp_path

    def test_hire_targets_the_declared_populated_set(self, tmp_path: Path, monkeypatch) -> None:
        root = self._onboarded_project(tmp_path)
        monkeypatch.chdir(root)
        from alc.cli import cmd_team

        ns = argparse.Namespace(
            team_action="hire", archetype="sweeper", member="sweeper", force=False, json=False
        )
        assert cmd_team(ns) == 0
        content = (root / ".alc" / "blueprints" / "refactor.md").read_text()
        assert "check_set: project" in content
        assert "check_set: python" not in content

    def test_hire_report_names_the_retarget(self, tmp_path: Path, monkeypatch, capsys) -> None:
        root = self._onboarded_project(tmp_path)
        monkeypatch.chdir(root)
        from alc.cli import cmd_team

        ns = argparse.Namespace(
            team_action="hire", archetype="sweeper", member="sweeper", force=False, json=False
        )
        cmd_team(ns)
        out = capsys.readouterr().out
        assert "Pointed" in out and "project" in out

    def test_hire_leaves_no_check_set_exists_error(self, tmp_path: Path, monkeypatch) -> None:
        root = self._onboarded_project(tmp_path)
        monkeypatch.chdir(root)
        from alc.cli import cmd_team
        from alc.intake import load_all_blueprints
        from alc.policy import lint

        ns = argparse.Namespace(
            team_action="hire", archetype="builder", member="builder", force=False, json=False
        )
        assert cmd_team(ns) == 0
        manifest = load_manifest(root / ".alc")
        violations = lint(manifest, load_all_blueprints(manifest, root / ".alc"))
        assert not any(v.rule == "blueprint-check-set-exists" for v in violations)

    def test_regression_matching_manifest_hire_is_byte_identical(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # A scaffold that DECLARES the stack set must hire the pack default,
        # untouched — the retarget is a no-op, not a rewrite.
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
        scaffold(tmp_path)
        monkeypatch.chdir(tmp_path)
        from alc.cli import cmd_team
        from alc.scaffold import detect_stacks

        ns = argparse.Namespace(
            team_action="hire", archetype="sweeper", member="sweeper", force=False, json=False
        )
        assert cmd_team(ns) == 0
        default = pack_files("sweeper", detect_stacks(tmp_path))[".alc/blueprints/refactor.md"]
        assert (tmp_path / ".alc" / "blueprints" / "refactor.md").read_text() == default

    def test_remove_sees_retargeted_files_as_unmodified(self, tmp_path: Path, monkeypatch) -> None:
        root = self._onboarded_project(tmp_path)
        monkeypatch.chdir(root)
        from alc.cli import cmd_team
        from alc.scaffold import detect_stacks

        ns = argparse.Namespace(
            team_action="hire", archetype="sweeper", member="sweeper", force=False, json=False
        )
        assert cmd_team(ns) == 0
        manifest = load_manifest(root / ".alc")
        removed, kept = remove_pack(
            "sweeper", detect_stacks(root), root, manifest.loops_dir,
            check_sets=manifest.check_sets,
        )
        assert kept == [], f"retargeted files must read as unmodified, kept: {kept}"
        assert removed

    def test_service_hire_returns_next_and_retargeted(self, tmp_path: Path) -> None:
        root = self._onboarded_project(tmp_path)
        from alc.ui import service

        result = service.team_hire(root, "sweeper")
        assert result["next"], "the UI needs the CLI's Next line to say it"
        assert ".alc/blueprints/refactor.md" in result["retargeted"]
        assert result["retargeted"][".alc/blueprints/refactor.md"] == "project"

    def test_pure_retarget_prefers_the_biggest_populated_set(self) -> None:
        files = {"b.md": "---\ncheck_set: python\n---\n"}
        out, ret = retarget_pack_content(
            files, {"small": [1], "big": [1, 2], "empty": []}
        )
        assert ret == {"b.md": "big"}
        assert "check_set: big" in out["b.md"]

    def test_pure_retarget_no_populated_set_is_a_no_op(self) -> None:
        files = {"b.md": "---\ncheck_set: python\n---\n"}
        out, ret = retarget_pack_content(files, {"empty": []})
        assert ret == {} and out == files

    def test_split_without_check_sets_is_unchanged(self, tmp_path: Path) -> None:
        # Regression: the old call shape (no check_sets) behaves exactly as before.
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
        scaffold(tmp_path)
        from alc.scaffold import detect_stacks

        stacks = detect_stacks(tmp_path)
        missing_old, _ = split_pack_files("sweeper", stacks, tmp_path)
        assert missing_old[".alc/blueprints/refactor.md"] == pack_files("sweeper", stacks)[
            ".alc/blueprints/refactor.md"
        ]


# ---------------------------------------------------------------------------
# 32 — dismiss a failure lineage
# ---------------------------------------------------------------------------


def _archive_failure(done_dir: Path, stem: str, retry_of: str | None = None) -> None:
    done_dir.mkdir(parents=True, exist_ok=True)
    task = {"kind": "run", "name": "chore", "task": f"do {stem}", "isolate": False}
    if retry_of:
        task["retry_of"] = retry_of
        task["retries"] = 1
    (done_dir / f"{stem}.yaml").write_text(yaml.safe_dump(task))
    (done_dir / f"{stem}.report.json").write_text(
        '{"flow": "chore", "engine": "mock", "success": false, "stages": [], '
        '"scorecard": {"span": 0, "passes": 0, "streak": 0, "touch": 0}}'
    )


class TestDismissFailure:
    def test_dismissed_lineage_leaves_outstanding(self, tmp_path: Path) -> None:
        done = tmp_path / "done"
        _archive_failure(done, "t1")
        assert len(outstanding_failures(done)) == 1

        root = dismiss_failure(done, "t1")

        assert root == "t1"
        assert outstanding_failures(done) == []
        # Nothing deleted — archives stay for audit.
        assert (done / "t1.yaml").exists() and (done / "t1.report.json").exists()
        assert (done / "t1.dismissed").exists()

    def test_dismissing_a_retry_closes_the_root_lineage(self, tmp_path: Path) -> None:
        done = tmp_path / "done"
        _archive_failure(done, "t1")
        _archive_failure(done, "t1-r1", retry_of="t1")
        assert len(outstanding_failures(done)) == 1

        root = dismiss_failure(done, "t1-r1")

        assert root == "t1"
        assert outstanding_failures(done) == []

    def test_unknown_stem_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            dismiss_failure(tmp_path, "nope")

    def test_regression_undismissed_failures_still_listed(self, tmp_path: Path) -> None:
        done = tmp_path / "done"
        _archive_failure(done, "t1")
        _archive_failure(done, "t2")
        dismiss_failure(done, "t1")
        remaining = outstanding_failures(done)
        assert [f.stem for f in remaining] == ["t2"]

    def test_service_dismiss_and_404(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        from alc.ui import service
        from alc.ui.errors import ApiError

        done = tmp_path / ".alc" / "queue" / "done"
        _archive_failure(done, "t9")
        assert service.dismiss_queue_failure(tmp_path, "t9") == {"dismissed": "t9"}
        with pytest.raises(ApiError):
            service.dismiss_queue_failure(tmp_path, "missing")

    def test_cli_dismiss(self, tmp_path: Path, monkeypatch, capsys) -> None:
        scaffold(tmp_path)
        monkeypatch.chdir(tmp_path)
        _archive_failure(tmp_path / ".alc" / "queue" / "done", "t3")
        from alc.cli import cmd_retry

        ns = argparse.Namespace(stem="t3", all=False, json=False, dismiss=True)
        assert cmd_retry(ns) == 0
        out = capsys.readouterr().out
        assert "Dismissed 't3'" in out
        assert "Nothing was deleted" in out


# ---------------------------------------------------------------------------
# 38 — isolated specialist resolves the ROOT operator layer when the worktree
#      lacks the file (uncommitted hire)
# ---------------------------------------------------------------------------


_SPEC_TASK_ISOLATED = """\
kind: specialist
name: db
task: "document the area"
engine: mock
isolate: true
"""


def _write_specialist(operator_layer: Path, name: str = "db") -> None:
    specialists_dir = operator_layer / "specialists"
    specialists_dir.mkdir(exist_ok=True)
    data = {
        "name": name,
        "area": "the database access layer",
        "blueprint": "chore",
        "knowledge_path": f".alc/specialists/{name}.knowledge.md",
    }
    (specialists_dir / f"{name}.yaml").write_text(yaml.safe_dump(data))


class TestIsolatedSpecialistResolution:
    def test_uncommitted_specialist_drains_from_the_root(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        root = operator_layer.parent
        _git_layer(root)  # commit the scaffold FIRST
        _write_specialist(operator_layer)  # then hire, uncommitted
        monkeypatch.chdir(root)
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "spec.yaml").write_text(_SPEC_TASK_ISOLATED)

        results = process_queue(manifest, operator_layer)

        assert len(results) == 1
        assert results[0].success is True, "an uncommitted specialist must not 404 the drain"

    def test_regression_committed_specialist_still_drains(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        root = operator_layer.parent
        _write_specialist(operator_layer)
        _git_layer(root)  # specialist IS committed -> worktree carries it
        monkeypatch.chdir(root)
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "spec.yaml").write_text(_SPEC_TASK_ISOLATED)

        results = process_queue(manifest, operator_layer)

        assert results[0].success is True


# ---------------------------------------------------------------------------
# 39 — signals provisioned into worktrees
# ---------------------------------------------------------------------------


class TestSignalsProvision:
    def test_runtime_provisions_appends_signals_copy(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        manifest = load_manifest(tmp_path / ".alc")
        provisions = runtime_provisions(manifest)
        signal_specs = [p for p in provisions if p.path == manifest.signals_dir]
        assert len(signal_specs) == 1
        assert signal_specs[0].kind == "copy"

    def test_declared_signals_provision_wins(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        manifest = load_manifest(tmp_path / ".alc")
        manifest.worktree_provision.append(ProvisionSpec(link=manifest.signals_dir))
        provisions = runtime_provisions(manifest)
        signal_specs = [p for p in provisions if p.path == manifest.signals_dir]
        assert len(signal_specs) == 1
        assert signal_specs[0].kind == "link", "the operator's declaration must win"

    def test_worktree_carries_the_signals(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        # signals are gitignored runtime state: write AFTER the commit.
        _git_layer(tmp_path)
        signals = tmp_path / ".alc" / "signals"
        signals.mkdir(parents=True, exist_ok=True)
        (signals / "feedback-x.json").write_text('{"kind": "feedback"}')
        manifest = load_manifest(tmp_path / ".alc")

        with IsolatedWorktree(
            repo_root=tmp_path, label="t", provisions=runtime_provisions(manifest)
        ) as wt:
            inside = wt / ".alc" / "signals" / "feedback-x.json"
            assert inside.exists(), "an isolated run must SEE the root's signals"
            # A copy, not a link: worktree writes must not touch the root.
            inside.write_text("mutated")
        assert (signals / "feedback-x.json").read_text() == '{"kind": "feedback"}'

    def test_regression_no_signals_dir_is_a_no_op(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        _git_layer(tmp_path)
        manifest = load_manifest(tmp_path / ".alc")
        with IsolatedWorktree(
            repo_root=tmp_path, label="t", provisions=runtime_provisions(manifest)
        ) as wt:
            assert not (wt / ".alc" / "signals").exists()


# ---------------------------------------------------------------------------
# 40 — a handled signal can be archived from either surface
# ---------------------------------------------------------------------------


class TestSignalArchive:
    def _ingest(self, root: Path, title: str = "loud buttons") -> str:
        from alc.models import Signal
        from alc.signals import ingest

        path = ingest(
            root / ".alc" / "signals",
            Signal(kind="feedback", source="operator", title=title, body="x"),
        )
        return path.name

    def test_cli_archive_moves_into_done(self, tmp_path: Path, monkeypatch, capsys) -> None:
        scaffold(tmp_path)
        monkeypatch.chdir(tmp_path)
        name = self._ingest(tmp_path)
        from alc.cli import cmd_signal

        ns = argparse.Namespace(signal_action="archive", name=name)
        assert cmd_signal(ns) == 0
        assert "Archived" in capsys.readouterr().out
        assert (tmp_path / ".alc" / "signals" / "done" / name).exists()
        assert not (tmp_path / ".alc" / "signals" / name).exists()

    def test_cli_archive_unknown_name_errors(self, tmp_path: Path, monkeypatch, capsys) -> None:
        scaffold(tmp_path)
        monkeypatch.chdir(tmp_path)
        from alc.cli import cmd_signal

        ns = argparse.Namespace(signal_action="archive", name="nope.json")
        assert cmd_signal(ns) == 1
        assert "no pending signal" in capsys.readouterr().err

    def test_cli_list_prints_the_addressable_name(self, tmp_path: Path, monkeypatch, capsys) -> None:
        scaffold(tmp_path)
        monkeypatch.chdir(tmp_path)
        name = self._ingest(tmp_path)
        from alc.cli import cmd_signal

        ns = argparse.Namespace(signal_action="list", json=False)
        assert cmd_signal(ns) == 0
        assert name in capsys.readouterr().out

    def test_service_archive_and_404_and_no_escape(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        from alc.ui import service
        from alc.ui.errors import ApiError

        name = self._ingest(tmp_path)
        # A path-shaped name is reduced to its basename — never an escape.
        assert service.archive_pending_signal(tmp_path, f"../../{name}") == {"archived": name}
        with pytest.raises(ApiError):
            service.archive_pending_signal(tmp_path, name)  # already archived -> 404

    def test_regression_replenish_archive_untouched(self, tmp_path: Path) -> None:
        # The loop replenish path calls signals.archive_signal directly; the
        # new verb sits BESIDE it, not inside it.
        from alc.models import Signal
        from alc.signals import archive_signal, ingest, read_signals

        signals_dir = tmp_path / "sig"
        path = ingest(signals_dir, Signal(kind="issue", source="t", title="x", body=""))
        archive_signal(signals_dir, path)
        assert read_signals(signals_dir) == []
        assert (signals_dir / "done" / path.name).exists()


# ---------------------------------------------------------------------------
# Round 10 — 42: autonomous demands are ALWAYS isolated (pinned in
# test_replenish_*/test_loop.py); 44: `alc init --engine` pins the manifest.
# ---------------------------------------------------------------------------


class TestInitEngineFlag:
    def test_explicit_engine_beats_the_probe(self, tmp_path: Path, monkeypatch) -> None:
        import alc.scaffold as scaffold_mod

        monkeypatch.setattr(scaffold_mod, "detect_default_engine", lambda: "claude-code")
        scaffold_mod.scaffold(tmp_path, engine="mock")
        manifest = load_manifest(tmp_path / ".alc")
        assert manifest.default_engine == "mock"

    def test_cmd_init_engine_flag_reaches_the_manifest(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(tmp_path)
        from alc.cli import cmd_init

        ns = argparse.Namespace(force=False, setup=False, engine="mock", stage=None)
        assert cmd_init(ns) == 0
        manifest = load_manifest(tmp_path / ".alc")
        assert manifest.default_engine == "mock"
        # The output credits the flag, not the probe (finding 44: the flag used
        # to configure only --setup while READING as "choose my engine").
        assert "Engine: mock (--engine flag)." in capsys.readouterr().out

    def test_regression_no_flag_keeps_the_probe(self, tmp_path: Path, monkeypatch, capsys) -> None:
        import alc.cli as cli_mod
        import alc.scaffold as scaffold_mod

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(scaffold_mod, "detect_default_engine", lambda: "gemini")
        ns = argparse.Namespace(force=False, setup=False, engine=None, stage=None)
        assert cli_mod.cmd_init(ns) == 0
        manifest = load_manifest(tmp_path / ".alc")
        assert manifest.default_engine == "gemini"
        assert "found on PATH" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Round 11 — 46: the loop budget brakes MID-cycle, between demands
# ---------------------------------------------------------------------------


_MOCK_TASK = "flow: ship\ntask: \"t{n}\"\nengine: mock\nisolate: false\n"


class TestMidCycleBudgetBrake:
    def _seed(self, operator_layer: Path, n: int) -> Path:
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (queue_dir / f"t{i}.yaml").write_text(_MOCK_TASK.replace("{n}", str(i)))
        return queue_dir

    def test_process_queue_stop_when_leaves_the_rest_pending(
        self, operator_layer: Path
    ) -> None:
        from alc.intake import load_manifest
        from alc.queue import process_queue

        manifest = load_manifest(operator_layer)
        queue_dir = self._seed(operator_layer, 3)

        results = process_queue(manifest, operator_layer, stop_when=lambda r: True)

        assert len(results) == 1, "the brake stops LAUNCHING after the first result"
        assert len(sorted(queue_dir.glob("*.yaml"))) == 2, "unlaunched tasks stay pending"

    def test_regression_no_stop_when_drains_everything(self, operator_layer: Path) -> None:
        from alc.intake import load_manifest
        from alc.queue import process_queue

        manifest = load_manifest(operator_layer)
        queue_dir = self._seed(operator_layer, 3)

        results = process_queue(manifest, operator_layer)

        assert len(results) == 3
        assert list(queue_dir.glob("*.yaml")) == []

    def test_cycle_budget_brakes_between_demands(self, operator_layer: Path) -> None:
        import yaml as yaml_mod

        from alc.intake import load_manifest, load_loop
        from alc.loop import load_loop_state, loops_dir, run_cycle, state_path

        manifest = load_manifest(operator_layer)
        loops = operator_layer / "loops"
        loops.mkdir(exist_ok=True)
        # Mode B (drain-only) loop. The fixture's ship flow spends TWO engine
        # calls per demand (two stages), so a cap of 3 crosses after demand
        # two (4 >= 3) — the third must never launch.
        (loops / "cap.yaml").write_text(
            yaml_mod.safe_dump(
                {
                    "name": "cap",
                    "stop": {"max_cycles": 5, "budget": {"unit": "engine_calls", "max": 3}},
                }
            )
        )
        queue_dir = self._seed(operator_layer, 3)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "cap")
        state = load_loop_state(state_path(loops_dir(manifest, operator_layer), "cap"), "cap")

        new_state, record = run_cycle(manifest, operator_layer, loop_def, state, engine_override="mock")

        assert record.drained == 2, "the cap crossed after demand two — three never ran"
        assert len(sorted(queue_dir.glob("*.yaml"))) == 1
        assert new_state.stopped_reason == "budget"

    def test_regression_unbudgeted_loop_drains_the_whole_cycle(
        self, operator_layer: Path
    ) -> None:
        import yaml as yaml_mod

        from alc.intake import load_manifest, load_loop
        from alc.loop import load_loop_state, loops_dir, run_cycle, state_path

        manifest = load_manifest(operator_layer)
        loops = operator_layer / "loops"
        loops.mkdir(exist_ok=True)
        (loops / "free.yaml").write_text(
            yaml_mod.safe_dump({"name": "free", "stop": {"max_cycles": 5}})
        )
        queue_dir = self._seed(operator_layer, 3)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "free")
        state = load_loop_state(state_path(loops_dir(manifest, operator_layer), "free"), "free")

        _, record = run_cycle(manifest, operator_layer, loop_def, state, engine_override="mock")

        assert record.drained == 3
        assert list(queue_dir.glob("*.yaml")) == []
