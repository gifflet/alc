# test_runner.py — End-to-end test via MandateRunner using a hermetic Operator
# Layer (built in tmp_path by the `operator_layer` fixture) with --engine mock.
# No real model is called.
from __future__ import annotations

import json
from pathlib import Path

from alc.intake import load_blueprint, load_manifest
from alc.models import ProvisionSpec
from alc.runner import MandateRunner, execute_mandate


class TestMandateRunnerEndToEnd:
    def test_chore_blueprint_with_mock_engine_succeeds(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            blueprint=blueprint,
            task="remove the unused export endpoint",
            engine_override="mock",
        )

        assert report.success is True
        assert report.engine == "mock"
        assert report.blueprint == "chore"

        # RunReport must be serialisable to JSON.
        raw = json.loads(report.model_dump_json())
        assert raw["success"] is True
        assert raw["scorecard"]["passes"] >= 1

    def test_report_scorecard_fields_present(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(blueprint=blueprint, task="tidy imports", engine_override="mock")

        sc = report.scorecard
        assert sc.span >= 0
        assert sc.passes >= 1
        assert sc.streak in (0, 1)
        assert sc.touch == 0


class TestEnvRefreshBinding:
    """execute_mandate binds the env-refresh closure iff a provision declares a
    refresh — opt-in, exactly like the other guard bindings."""

    def _spy_loop_kwargs(self, monkeypatch) -> dict:
        """Patch AssuranceLoop to capture the kwargs it is constructed with."""
        captured: dict = {}
        import alc.runner as runner_mod

        real_loop = runner_mod.AssuranceLoop

        def _spy(**kwargs):
            captured.update(kwargs)
            return real_loop(**kwargs)

        monkeypatch.setattr(runner_mod, "AssuranceLoop", _spy)
        return captured

    def test_refresh_provision_binds_the_closure(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        manifest = load_manifest(operator_layer)
        manifest = manifest.model_copy(
            update={
                "worktree_provision": [
                    ProvisionSpec(
                        link="node_modules",
                        refresh=["npm", "install"],
                        when_changed=["package.json"],
                    )
                ]
            }
        )
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        captured = self._spy_loop_kwargs(monkeypatch)
        execute_mandate(
            manifest, blueprint, "# directive", "mock", operator_layer=operator_layer
        )
        assert "env_refresh" in captured
        assert callable(captured["env_refresh"])

    def test_no_refresh_provision_leaves_it_unbound(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        manifest = load_manifest(operator_layer)
        manifest = manifest.model_copy(
            update={"worktree_provision": [ProvisionSpec(link="node_modules")]}
        )
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        captured = self._spy_loop_kwargs(monkeypatch)
        execute_mandate(
            manifest, blueprint, "# directive", "mock", operator_layer=operator_layer
        )
        assert "env_refresh" not in captured

    def test_non_git_workdir_is_a_graceful_noop(
        self, operator_layer: Path, monkeypatch, tmp_path: Path
    ) -> None:
        # operator_layer's parent (tmp_path) is NOT a git repo -> state_before is
        # None -> the bound closure lists nothing changed and never fires. The run
        # must still succeed without crashing.
        manifest = load_manifest(operator_layer)
        manifest = manifest.model_copy(
            update={
                "worktree_provision": [
                    ProvisionSpec(
                        link="node_modules",
                        refresh=["sh", "-c", "exit 1"],  # would fail IF it ever ran
                        when_changed=["package.json"],
                    )
                ]
            }
        )
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        report = execute_mandate(
            manifest, blueprint, "# directive", "mock", operator_layer=operator_layer
        )
        # The refresh never fired (no git -> no changed files), so the failing
        # install command was never run and the run succeeds.
        assert report.success is True
