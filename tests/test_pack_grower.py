# test_pack_grower.py — Hermetic tests for the Grower Archetype Pack
# (packs.py's `grower` entry): a DIY issue/error-sweep Specialist whose
# Knowledge File accumulates what users keep hitting. Deliberately PARTIAL
# (roadmap-phase-2.md T12) — real signal intake, metric checks, and the
# `regression` replenish kind are Phases 4-5.
from __future__ import annotations

from pathlib import Path

from alc.intake import load_all_blueprints, load_manifest, load_specialist
from alc.packs import PACKS, pack_files
from alc.scaffold import scaffold


class TestPackRegistration:
    def test_grower_is_registered(self) -> None:
        assert "grower" in PACKS
        assert callable(PACKS["grower"])


class TestPackFilesGrower:
    def test_returns_the_expected_relative_paths(self) -> None:
        files = pack_files("grower", stacks=[])
        assert set(files) == {".alc/specialists/listen.yaml"}

    def test_listen_specialist_uses_the_default_plan_blueprint(self) -> None:
        content = pack_files("grower", stacks=[])[".alc/specialists/listen.yaml"]
        assert "blueprint: plan" in content

    def test_content_is_the_same_regardless_of_detected_stacks(self) -> None:
        # listen.yaml is stack-agnostic — the sweep is DIY, not stack-specific.
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        assert (
            pack_files("grower", stacks=[])[".alc/specialists/listen.yaml"]
            == pack_files("grower", stacks)[".alc/specialists/listen.yaml"]
        )

    def test_declares_itself_diy_and_partial(self) -> None:
        # T12: "Say plainly, in the pack's own files, that it is partial."
        content = pack_files("grower", stacks=[])[".alc/specialists/listen.yaml"]
        assert "DIY" in content
        assert "Phase" in content  # names the later phase(s) that complete it


# ---------------------------------------------------------------------------
# Loading is strict: Specialists are pydantic-validated YAML — a pack file
# that fails its loader is a defect (roadmap-phase-2.md).
# ---------------------------------------------------------------------------


def _hire(tmp_path: Path) -> Path:
    """Scaffold a default Operator Layer, then hire the grower pack into it."""
    scaffold(tmp_path)
    files = pack_files("grower", stacks=[])
    for rel_path, text in files.items():
        target = tmp_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return tmp_path / ".alc"


class TestGrowerPackLoadsThroughTheRealLoaders:
    def test_listen_loads_as_a_specialist(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        specialist = load_specialist(operator_layer / "specialists", "listen")
        assert specialist.name == "listen"
        assert specialist.blueprint == "plan"
        assert specialist.knowledge_path == ".alc/specialists/listen.knowledge.md"

    def test_listen_references_an_existing_blueprint(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer)
        specialist = load_specialist(operator_layer / "specialists", "listen")
        blueprints = {b.name for b in load_all_blueprints(manifest, operator_layer)}
        assert specialist.blueprint in blueprints
