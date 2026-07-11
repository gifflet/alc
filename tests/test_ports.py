# test_ports.py — Part B: dynamic free-port RANGE injection into a worktree run.
#
# Covers the allocator + its disjointness registry, env threading through
# execute_mandate / FlowRunner.run / run_specialist, and the queue wiring that
# injects ALC_PORT / ALC_PORT_2 / ALC_PORTS for an isolated task. Fully hermetic:
# no real model, and the git test uses a local repo in tmp_path.
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from alc import worktree as worktree_mod
from alc.engine import Capabilities, EngineRequest, EngineResult
from alc.flow import FlowRunner
from alc.intake import load_manifest
from alc.models import (
    Blueprint,
    Check,
    FlowDefinition,
    FlowStage,
    Manifest,
)
from alc.queue import process_queue
from alc.runner import execute_mandate
from alc.worktree import allocate_free_ports, release_ports

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


class _RecordingEngine:
    """Spy engine that records every EngineRequest's env it receives."""

    name = "recording"

    def __init__(self) -> None:
        self.received: list[EngineRequest] = []

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request: EngineRequest) -> EngineResult:
        self.received.append(request)
        return EngineResult(ok=True, output_text="[recording] ok")


# ---------------------------------------------------------------------------
# The allocator + its disjointness registry
# ---------------------------------------------------------------------------


class TestAllocateFreePorts:
    def test_returns_n_distinct_ports(self) -> None:
        ports = allocate_free_ports(3)
        try:
            assert len(ports) == 3
            assert len(set(ports)) == 3  # distinct
        finally:
            release_ports(ports)

    def test_concurrent_allocations_are_disjoint(self) -> None:
        # A second allocate BEFORE releasing the first proves the _ALLOCATED_PORTS
        # registry hands out disjoint sets across in-flight allocations.
        first = allocate_free_ports(3)
        second = allocate_free_ports(3)
        try:
            assert set(first).isdisjoint(set(second))
        finally:
            release_ports(first)
            release_ports(second)

    def test_release_frees_ports_from_registry(self) -> None:
        ports = allocate_free_ports(2)
        for p in ports:
            assert p in worktree_mod._ALLOCATED_PORTS
        release_ports(ports)
        for p in ports:
            assert p not in worktree_mod._ALLOCATED_PORTS
        # A subsequent allocate still returns valid distinct ports.
        again = allocate_free_ports(2)
        assert len(set(again)) == 2
        release_ports(again)

    def test_zero_ports_returns_empty(self) -> None:
        assert allocate_free_ports(0) == []
        assert allocate_free_ports(-1) == []

    def test_default_manifest_worktree_ports_is_zero(self) -> None:
        # Default 0 = OFF = byte-identical to today (no ports injected).
        assert _MINIMAL_MANIFEST.worktree_ports == 0


# ---------------------------------------------------------------------------
# env threading — execute_mandate -> EngineRequest.env
# ---------------------------------------------------------------------------


class TestExecuteMandateEnv:
    def _bp(self) -> Blueprint:
        return Blueprint(
            name="chore",
            purpose="a mandate",
            checks=[Check(name="smoke", command=["true"])],
            workflow="# do it",
        )

    def test_env_reaches_request_env(self, monkeypatch, tmp_path: Path) -> None:
        engine = _RecordingEngine()
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=self._bp(),
            directive="# t",
            workdir=tmp_path,
            env={"ALC_PORT": "5555"},
        )

        assert len(engine.received) == 1
        assert engine.received[0].env == {"ALC_PORT": "5555"}

    def test_env_none_is_empty_dict(self, monkeypatch, tmp_path: Path) -> None:
        engine = _RecordingEngine()
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=self._bp(),
            directive="# t",
            workdir=tmp_path,
        )

        assert engine.received[0].env == {}


# ---------------------------------------------------------------------------
# env threading — FlowRunner.run / run_specialist thread it to every stage
# ---------------------------------------------------------------------------


class TestFlowRunnerEnvThreading:
    def _write_dev_specialist(self, operator_layer: Path) -> None:
        specialists_dir = operator_layer / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        data = {
            "name": "dev",
            "area": "the implementation area",
            "blueprint": "chore",
            "knowledge_path": ".alc/specialists/dev.knowledge.md",
        }
        (specialists_dir / "dev.yaml").write_text(yaml.safe_dump(data))

    def test_env_reaches_specialist_and_blueprint_stages(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        """A demand flow [dev(specialist) -> qa(blueprint)] run with env -> BOTH
        stages' engine turns carry ALC_PORT."""
        self._write_dev_specialist(operator_layer)

        flow = FlowDefinition(
            name="demand",
            stages=[
                FlowStage(name="implement", specialist="dev"),
                FlowStage(name="validate", blueprint="chore"),
            ],
        )

        act_envs: list[dict[str, str]] = []

        class _EnvRecordingEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request: EngineRequest) -> EngineResult:
                act_envs.append(dict(request.env))
                return EngineResult(ok=True, output_text="ok")

        # Patch resolve_engine everywhere the flow path resolves it (runner binds it
        # at import; specialist imports it lazily from the registry for its Learn turn).
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, cfg: _EnvRecordingEngine()
        )
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, cfg: _EnvRecordingEngine(),
        )

        manifest = load_manifest(operator_layer)
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=flow,
            task="ship the thing",
            engine_override="mock",
            env={"ALC_PORT": "7001"},
        )

        assert report.success is True
        # Both Act engine turns (the specialist stage's Act + the blueprint stage)
        # carried ALC_PORT. The specialist's Learn turn builds its own request and is
        # out of scope for the port env, so we assert the count of port-carrying turns
        # (>= the 2 stages) rather than that EVERY captured turn has it.
        port_turns = [e for e in act_envs if e.get("ALC_PORT") == "7001"]
        assert len(port_turns) >= 2


# ---------------------------------------------------------------------------
# Queue wiring — worktree_ports injects the range for an isolated task
# ---------------------------------------------------------------------------


def _make_git_repo_with_operator_layer(base: Path) -> Path:
    """Init a git repo, copy the operator layer's `.alc/` into it, return `.alc/`."""
    repo = base / "repo"
    repo.mkdir()
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
    return repo


def _seed_operator_layer(repo: Path, src_alc: Path) -> Path:
    """Copy the hermetic `.alc/` fixture into *repo*, commit it, return the `.alc/`."""
    import shutil

    dst_alc = repo / ".alc"
    shutil.copytree(src_alc, dst_alc)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True
    )
    return dst_alc


class _EnvSpyEngine:
    """Records the env of the FIRST engine turn it sees (the demand's Act)."""

    name = "mock"
    seen: list[dict[str, str]] = []

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request: EngineRequest) -> EngineResult:
        type(self).seen.append(dict(request.env))
        return EngineResult(ok=True, output_text="ok")


def _run_queue_with_ports(
    tmp_path: Path, operator_layer: Path, monkeypatch, worktree_ports: int
) -> list[dict[str, str]]:
    """Drain one isolated non-committing flow task in a git repo, return the env(s)
    the engine saw. Uses worktree_ports as configured."""
    repo = _make_git_repo_with_operator_layer(tmp_path)
    alc = _seed_operator_layer(repo, operator_layer)

    # Load + override worktree_ports on the manifest.
    manifest = load_manifest(alc)
    manifest = manifest.model_copy(update={"worktree_ports": worktree_ports})

    # Drop one isolate:true flow task (the fixture `ship` flow is non-committing).
    queue_dir = alc / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "t1.yaml").write_text(
        "flow: ship\ntask: \"tidy\"\nengine: mock\nisolate: true\n"
    )

    _EnvSpyEngine.seen = []
    monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _EnvSpyEngine())

    results = process_queue(manifest, alc)
    assert len(results) == 1
    assert results[0].success is True
    return _EnvSpyEngine.seen


class TestQueuePortInjection:
    def test_ports_injected_for_isolated_task(
        self, tmp_path: Path, operator_layer: Path, monkeypatch
    ) -> None:
        envs = _run_queue_with_ports(
            tmp_path, operator_layer, monkeypatch, worktree_ports=2
        )
        assert envs, "the engine must have run at least once"
        env = envs[0]
        assert "ALC_PORT" in env
        assert "ALC_PORT_2" in env
        assert "ALC_PORTS" in env
        # The two ports are distinct.
        assert env["ALC_PORT"] != env["ALC_PORT_2"]
        # ALC_PORTS is the comma list of both.
        assert env["ALC_PORTS"] == f"{env['ALC_PORT']},{env['ALC_PORT_2']}"
        # The primary port is ALSO exposed under the conventional `PORT` (F1).
        assert env["PORT"] == env["ALC_PORT"]

    def test_ports_released_after_run(
        self, tmp_path: Path, operator_layer: Path, monkeypatch
    ) -> None:
        envs = _run_queue_with_ports(
            tmp_path, operator_layer, monkeypatch, worktree_ports=2
        )
        used = {int(envs[0]["ALC_PORT"]), int(envs[0]["ALC_PORT_2"])}
        # After the run the ports were released, so none remain reserved.
        assert used.isdisjoint(worktree_mod._ALLOCATED_PORTS)
        # A fresh allocate still succeeds.
        again = allocate_free_ports(2)
        assert len(set(again)) == 2
        release_ports(again)

    def test_worktree_ports_zero_is_byte_identical(
        self, tmp_path: Path, operator_layer: Path, monkeypatch
    ) -> None:
        """worktree_ports=0 injects NO ALC_PORT — byte-identical to today."""
        envs = _run_queue_with_ports(
            tmp_path, operator_layer, monkeypatch, worktree_ports=0
        )
        assert envs
        for env in envs:
            assert "ALC_PORT" not in env
            assert "ALC_PORTS" not in env

    def test_non_isolate_path_never_injects_ports(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        """A non-isolate task shares the workdir and never gets ports injected,
        even when worktree_ports > 0."""
        manifest = load_manifest(operator_layer)
        manifest = manifest.model_copy(update={"worktree_ports": 2})

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(
            "flow: ship\ntask: \"tidy\"\nengine: mock\nisolate: false\n"
        )

        _EnvSpyEngine.seen = []
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, cfg: _EnvSpyEngine()
        )

        results = process_queue(manifest, operator_layer)
        assert len(results) == 1
        assert _EnvSpyEngine.seen
        for env in _EnvSpyEngine.seen:
            assert "ALC_PORT" not in env


# ---------------------------------------------------------------------------
# F1 — the embedded `runtime-conventions` prompt is appended to the directive
# exactly when ALC injected a port into the run's env (core-owned enforcement).
# ---------------------------------------------------------------------------


class TestRuntimeConventions:
    def _bp(self) -> Blueprint:
        return Blueprint(
            name="chore",
            purpose="a mandate",
            checks=[Check(name="smoke", command=["true"])],
            workflow="# do it",
        )

    def _mandate(self, engine, operator_layer, tmp_path, monkeypatch, env):
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)
        execute_mandate(
            manifest=load_manifest(operator_layer),
            blueprint=self._bp(),
            directive="# original",
            workdir=tmp_path,
            operator_layer=operator_layer,
            env=env,
        )
        return engine.received[0].directive

    def test_appended_when_alc_port_in_env(
        self, monkeypatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        directive = self._mandate(
            _RecordingEngine(), operator_layer, tmp_path, monkeypatch, {"ALC_PORT": "5555"}
        )
        assert "# original" in directive
        assert "Runtime conventions" in directive
        assert "$PORT" in directive

    def test_appended_for_bare_PORT(
        self, monkeypatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        directive = self._mandate(
            _RecordingEngine(), operator_layer, tmp_path, monkeypatch, {"PORT": "5555"}
        )
        assert "Runtime conventions" in directive

    def test_not_appended_without_port(
        self, monkeypatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        # No port in env -> directive is byte-identical to what the caller passed.
        directive = self._mandate(
            _RecordingEngine(), operator_layer, tmp_path, monkeypatch, {}
        )
        assert directive == "# original"

    def test_runtime_conventions_is_a_reserved_prompt(
        self, operator_layer: Path
    ) -> None:
        from alc.prompts import resolve_prompt

        text = resolve_prompt(
            "runtime-conventions", operator_layer, load_manifest(operator_layer)
        )
        assert "Runtime conventions" in text
        assert "$PORT" in text
