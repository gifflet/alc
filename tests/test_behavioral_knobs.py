# test_behavioral_knobs.py — the five Part-C knobs: each has a config-schema default
# and a simple override. Every test also proves "unset == identical to before".
from __future__ import annotations

from pathlib import Path

from alc.conduct import conduct
from alc.engine import Capabilities, EngineResult
from alc.intake import load_manifest
from alc.models import Blueprint, ConductorPlan, FanoutReport, Manifest
from alc.runner import execute_mandate

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}, "deep": {"mock": "mock-large"}},
    engines={"mock": {"type": "mock"}},
)


class _TimeoutRecordingEngine:
    """Engine that records the timeout_s of the request it received."""

    name = "mock"

    def __init__(self) -> None:
        self.seen_timeout: int | None = None

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request):
        self.seen_timeout = request.timeout_s
        return EngineResult(ok=True, output_text="ok")


# ---------------------------------------------------------------------------
# Knob A — engine per-turn timeout
# ---------------------------------------------------------------------------


class TestEngineTimeout:
    def test_blueprint_timeout_reaches_engine_request(self, tmp_path, monkeypatch) -> None:
        eng = _TimeoutRecordingEngine()
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: eng)
        bp = Blueprint(name="t", purpose="p", workflow="x", timeout_s=42)
        execute_mandate(
            manifest=_MINIMAL_MANIFEST, blueprint=bp, directive="d", workdir=tmp_path
        )
        assert eng.seen_timeout == 42

    def test_unset_timeout_uses_manifest_default(self, tmp_path, monkeypatch) -> None:
        eng = _TimeoutRecordingEngine()
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: eng)
        manifest = _MINIMAL_MANIFEST.model_copy(update={"default_timeout_s": 99})
        bp = Blueprint(name="t", purpose="p", workflow="x")  # timeout_s None
        execute_mandate(
            manifest=manifest, blueprint=bp, directive="d", workdir=tmp_path
        )
        assert eng.seen_timeout == 99

    def test_default_manifest_timeout_is_1800(self) -> None:
        # Unset -> the former hardcoded value, so behavior is identical.
        assert _MINIMAL_MANIFEST.default_timeout_s == 1800


# ---------------------------------------------------------------------------
# Knob B — plan/Conductor parse retries
# ---------------------------------------------------------------------------


class TestPlanRetries:
    def test_conduct_passes_manifest_plan_retries(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        captured: dict = {}

        def fake_plan_flows(*args, max_retries=2, **kwargs):
            captured["max_retries"] = max_retries
            return ConductorPlan(items=[])

        monkeypatch.setattr("alc.conduct.plan_flows", fake_plan_flows)
        manifest = load_manifest(operator_layer).model_copy(update={"plan_retries": 7})
        conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="g",
            engine_override="mock",
            enqueue=True,
        )
        assert captured["max_retries"] == 7

    def test_default_plan_retries_is_2(self, operator_layer: Path) -> None:
        assert load_manifest(operator_layer).plan_retries == 2


# ---------------------------------------------------------------------------
# Knob C — parallel fan-out width
# ---------------------------------------------------------------------------


class TestFanoutConcurrency:
    def _patch(self, monkeypatch, captured: dict) -> None:
        monkeypatch.setattr("alc.worktree.is_git_repo", lambda p: True)
        monkeypatch.setattr(
            "alc.conduct.plan_flows", lambda *a, **k: ConductorPlan(items=[])
        )

        def fake_run_fanout(
            manifest, operator_layer, units, engine_override=None, max_workers=4
        ):
            captured["max_workers"] = max_workers
            return FanoutReport(units=[], success=True)

        monkeypatch.setattr("alc.fanout.run_fanout", fake_run_fanout)

    def test_concurrency_flag_reaches_fanout(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        captured: dict = {}
        self._patch(monkeypatch, captured)
        manifest = load_manifest(operator_layer).model_copy(
            update={"fanout_concurrency": 5}
        )
        conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="g",
            engine_override="mock",
            parallel=True,
            concurrency=3,
        )
        assert captured["max_workers"] == 3

    def test_unset_concurrency_uses_manifest_default(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        captured: dict = {}
        self._patch(monkeypatch, captured)
        manifest = load_manifest(operator_layer).model_copy(
            update={"fanout_concurrency": 5}
        )
        conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="g",
            engine_override="mock",
            parallel=True,
        )
        assert captured["max_workers"] == 5

    def test_default_fanout_concurrency_is_4(self, operator_layer: Path) -> None:
        assert load_manifest(operator_layer).fanout_concurrency == 4


# ---------------------------------------------------------------------------
# Knob E — tier for the Conductor planning turn (Learn tier is in test_specialist)
# ---------------------------------------------------------------------------


class TestPlanningTier:
    def _capture_model(self, operator_layer: Path, monkeypatch, tiers: dict) -> dict:
        captured: dict = {}

        def fake_plan_flows(engine, model, *a, **k):
            captured["model"] = model
            return ConductorPlan(items=[])

        monkeypatch.setattr("alc.conduct.plan_flows", fake_plan_flows)
        return captured

    def test_tier_flag_drives_planning_model(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        manifest = load_manifest(operator_layer)
        captured = self._capture_model(operator_layer, monkeypatch, manifest.compute_tiers)
        conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="g",
            engine_override="mock",
            enqueue=True,
            tier="deep",
        )
        assert captured["model"] == manifest.compute_tiers["deep"]["mock"]

    def test_manifest_plan_tier_drives_planning_model(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        manifest = load_manifest(operator_layer).model_copy(update={"plan_tier": "deep"})
        captured = self._capture_model(operator_layer, monkeypatch, manifest.compute_tiers)
        conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="g",
            engine_override="mock",
            enqueue=True,
        )
        assert captured["model"] == manifest.compute_tiers["deep"]["mock"]

    def test_default_plan_tier_is_standard(self, operator_layer: Path) -> None:
        assert load_manifest(operator_layer).plan_tier == "standard"
