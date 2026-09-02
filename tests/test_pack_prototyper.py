# test_pack_prototyper.py — Hermetic tests for the Prototyper Archetype Pack
# (packs.py's `prototyper` entry): a single throwaway `spike` Blueprint that
# declares `mode: spike` — the ONE relaxation of the checks gate, fenced by forced isolation, zero repairs, and no commit/auto-merge. This
# completes the five packs promised by `alc init --stage pre-pmf`.
from __future__ import annotations

from pathlib import Path

from alc.intake import load_all_blueprints, load_blueprint, load_manifest
from alc.packs import PACKS, pack_files
from alc.policy import lint
from alc.scaffold import scaffold


class TestPackRegistration:
    def test_prototyper_is_registered(self) -> None:
        assert "prototyper" in PACKS
        assert callable(PACKS["prototyper"])


class TestPackFilesPrototyper:
    def test_returns_the_expected_relative_paths(self) -> None:
        files = pack_files("prototyper", stacks=[])
        assert set(files) == {".alc/blueprints/spike.md"}

    def test_spike_blueprint_declares_mode_spike(self) -> None:
        content = pack_files("prototyper", stacks=[])[".alc/blueprints/spike.md"]
        assert "mode: spike" in content

    def test_spike_blueprint_carries_the_prototyper_archetype_label(self) -> None:
        content = pack_files("prototyper", stacks=[])[".alc/blueprints/spike.md"]
        assert "archetype: prototyper" in content

    def test_spike_blueprint_declares_no_checks(self) -> None:
        # The whole point of mode: spike is that checks are optional here — the
        # pack itself demonstrates the Policy Gate's rule-1 downgrade to warn.
        content = pack_files("prototyper", stacks=[])[".alc/blueprints/spike.md"]
        assert "checks:" not in content

    def test_content_is_the_same_regardless_of_detected_stacks(self) -> None:
        # No stack-specific check_set — a spike deliberately skips checks.
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        assert (
            pack_files("prototyper", stacks=[])[".alc/blueprints/spike.md"]
            == pack_files("prototyper", stacks)[".alc/blueprints/spike.md"]
        )


# ---------------------------------------------------------------------------
# Loading is strict: Blueprints are parsed via load_blueprint — a pack file
# that fails its loader is a defect.
# ---------------------------------------------------------------------------


def _hire(tmp_path: Path) -> Path:
    """Scaffold a default Operator Layer, then hire the prototyper pack into it."""
    scaffold(tmp_path)
    files = pack_files("prototyper", stacks=[])
    for rel_path, text in files.items():
        target = tmp_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return tmp_path / ".alc"


class TestPrototyperPackLoadsThroughTheRealLoaders:
    def test_spike_loads_as_a_blueprint(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        bp = load_blueprint(operator_layer / "blueprints", "spike")
        assert bp.name == "spike"
        assert bp.mode == "spike"
        assert bp.archetype == "prototyper"
        assert bp.checks == []


class TestPrototyperPackLintsAsWarnNotError:
    """T1's rule 1 downgrade is what makes a check-less spike Blueprint lint
    clean — the sweep in test_packs.py::TestEveryPackLintsClean only asserts
    errors are absent; this test spells out the WARN it expects instead, so the
    new pack doesn't just slip through the sweep unexamined."""

    def test_spike_blueprint_gets_a_warn_not_an_error(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        violations = lint(manifest, blueprints)

        matching = [v for v in violations if v.rule == "blueprint_has_checks"]
        assert len(matching) == 1
        assert matching[0].severity == "warn"
        assert not any(v.severity == "error" for v in violations)
