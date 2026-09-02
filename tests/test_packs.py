# test_packs.py — Hermetic tests for packs.py: the Archetype Pack data table.
from __future__ import annotations

from pathlib import Path

import pytest

from alc.intake import load_all_blueprints, load_manifest
from alc.packs import PACKS, hired_archetypes, pack_files, split_pack_files
from alc.policy import lint
from alc.scaffold import detect_stacks, scaffold


class TestPacksRegistry:
    def test_builder_is_registered(self) -> None:
        assert "builder" in PACKS

    def test_registry_is_a_plain_dict_of_callables(self) -> None:
        # No class hierarchy, no plugin system — a data table.
        assert isinstance(PACKS, dict)
        assert callable(PACKS["builder"])


class TestPackFilesUnknownArchetype:
    def test_raises_key_error_with_available_packs_listed(self) -> None:
        with pytest.raises(KeyError, match="builder"):
            pack_files("nosuchpack", stacks=[])


class TestHiredArchetypes:
    """The shared membership test: a pack is hired once ANY of its files exists."""

    def test_fresh_scaffold_has_nothing_hired(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        assert hired_archetypes(tmp_path) == []

    def test_reflects_a_present_pack_file(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        # Write a single one of builder's pack files — that alone hires builder.
        files = pack_files("builder", detect_stacks(tmp_path))
        rel = next(iter(files))
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(files[rel])

        assert hired_archetypes(tmp_path) == ["builder"]

    def test_result_is_sorted_across_several_hired_packs(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        stacks = detect_stacks(tmp_path)
        for archetype in ("sweeper", "builder"):
            for rel, content in pack_files(archetype, stacks).items():
                target = tmp_path / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)

        assert hired_archetypes(tmp_path) == ["builder", "sweeper"]

    def test_matches_the_cli_wrapper_it_backs(self, tmp_path: Path) -> None:
        from alc.cli import _hired_archetypes

        scaffold(tmp_path)
        for rel, content in pack_files("builder", detect_stacks(tmp_path)).items():
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        assert _hired_archetypes(tmp_path) == hired_archetypes(tmp_path) == ["builder"]


class TestSplitPackFiles:
    """`split_pack_files` partitions a pack into (missing, present) — the read-only
    computation behind `alc team hire`'s additive default (write missing, keep
    present)."""

    def test_empty_project_is_all_missing_none_present(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        stacks = detect_stacks(tmp_path)
        missing, present = split_pack_files("builder", stacks, tmp_path)

        # Nothing of the pack is on disk yet: every file is missing, none present.
        assert set(missing) == set(pack_files("builder", stacks))
        assert present == {}

    def test_partial_presence_partitions_exactly(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        stacks = detect_stacks(tmp_path)
        files = pack_files("builder", stacks)

        # Put exactly ONE of the pack's files on disk.
        present_rel = sorted(files)[0]
        target = tmp_path / present_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(files[present_rel])

        missing, present = split_pack_files("builder", stacks, tmp_path)

        assert set(present) == {present_rel}
        assert set(missing) == set(files) - {present_rel}
        # Both carry the PACK content, so a caller can compare on-disk bytes to
        # flag drift.
        assert present[present_rel] == files[present_rel]
        assert missing == {r: files[r] for r in missing}

    def test_fully_present_has_no_missing(self, tmp_path: Path) -> None:
        scaffold(tmp_path)
        stacks = detect_stacks(tmp_path)
        for rel, content in pack_files("builder", stacks).items():
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        missing, present = split_pack_files("builder", stacks, tmp_path)

        assert missing == {}
        assert set(present) == set(pack_files("builder", stacks))


class TestPackFilesBuilder:
    def test_returns_the_expected_relative_paths(self) -> None:
        files = pack_files("builder", stacks=[])
        assert set(files) == {
            ".alc/blueprints/test.md",
            ".alc/blueprints/qa.md",
            ".alc/flows/ship-hardened.yaml",
        }

    def test_test_blueprint_references_the_primary_stack_check_set(self) -> None:
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        files = pack_files("builder", stacks)
        assert "check_set: python" in files[".alc/blueprints/test.md"]

    def test_qa_blueprint_also_references_the_primary_stack_check_set(self) -> None:
        stacks = [("Go", "go", [("build", ["go", "build", "./..."])])]
        files = pack_files("builder", stacks)
        assert "check_set: go" in files[".alc/blueprints/qa.md"]

    def test_no_check_set_line_when_no_stack_was_detected(self) -> None:
        files = pack_files("builder", stacks=[])
        assert "check_set:" not in files[".alc/blueprints/test.md"]
        assert "check_set:" not in files[".alc/blueprints/qa.md"]

    def test_uses_the_first_stack_when_several_are_detected(self) -> None:
        stacks = [
            ("Go", "go", [("build", ["go", "build", "./..."])]),
            ("Python", "python", [("test", ["pytest", "-q"])]),
        ]
        files = pack_files("builder", stacks)
        assert "check_set: go" in files[".alc/blueprints/test.md"]
        assert "check_set: python" not in files[".alc/blueprints/test.md"]

    def test_test_blueprint_keeps_an_inline_check_regardless_of_check_set(self) -> None:
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        files = pack_files("builder", stacks)
        assert '["true"]' in files[".alc/blueprints/test.md"]

    def test_qa_blueprint_declares_needs_service_and_an_inline_e2e_check(self) -> None:
        files = pack_files("builder", stacks=[])
        content = files[".alc/blueprints/qa.md"]
        assert "needs_service: true" in content
        assert "ALC_BASE_URL" in content

    def test_both_blueprints_carry_the_builder_archetype_label(self) -> None:
        files = pack_files("builder", stacks=[])
        assert "archetype: builder" in files[".alc/blueprints/test.md"]
        assert "archetype: builder" in files[".alc/blueprints/qa.md"]

    def test_ship_hardened_flow_chains_plan_build_harden_and_a_verify_only_gate(self) -> None:
        content = pack_files("builder", stacks=[])[".alc/flows/ship-hardened.yaml"]
        assert "blueprint: plan" in content
        assert "blueprint: feature" in content
        assert content.count("blueprint: test") == 2
        assert "verify_only: true" in content


# ---------------------------------------------------------------------------
# Every scaffolded pack must pass `alc lint` first time — a contract
#. Parametrized over every registered pack, every
# detectable stack (plus none), and BOTH binary-availability scenarios: the trap
# found while verifying Wave 1 is that with no scanner (or ANY) binary on PATH, a
# check_set can resolve to an empty list, so a pack Blueprint must never depend
# on a check_set alone.
# ---------------------------------------------------------------------------

_STACK_MARKERS: dict[str, tuple[str, str] | None] = {
    "none": None,
    "python": ("pyproject.toml", "[project]\nname = 'x'\n"),
    "go": ("go.mod", "module example\n"),
    "node": ("package.json", '{"name": "x"}\n'),
    "rust": ("Cargo.toml", '[package]\nname = "hello"\n'),
}


def _write_stack_marker(tmp_path: Path, stack_key: str) -> None:
    marker = _STACK_MARKERS[stack_key]
    if marker is None:
        return
    filename, content = marker
    (tmp_path / filename).write_text(content)


def _hire_pack_files(tmp_path: Path, archetype: str) -> None:
    """Write archetype's pack files (blueprints only) into an already-scaffolded tmp_path."""
    files = pack_files(archetype, detect_stacks(tmp_path))
    for rel_path, text in files.items():
        target = tmp_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def _lint_errors(tmp_path: Path) -> list:
    operator_layer = tmp_path / ".alc"
    manifest = load_manifest(operator_layer)
    blueprints = load_all_blueprints(manifest, operator_layer)
    violations = lint(manifest, blueprints)
    return [v for v in violations if v.severity == "error"]


class TestEveryPackLintsClean:
    """Every scaffolded pack must pass `alc lint` first time."""

    @pytest.mark.parametrize("archetype", sorted(PACKS))
    @pytest.mark.parametrize("stack_key", sorted(_STACK_MARKERS))
    @pytest.mark.parametrize("binaries_available", [True, False], ids=["binaries", "no-binaries"])
    def test_pack_lints_clean(
        self,
        archetype: str,
        stack_key: str,
        binaries_available: bool,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        which = (lambda cmd: f"/usr/bin/{cmd}") if binaries_available else (lambda cmd: None)
        monkeypatch.setattr("alc.scaffold.shutil.which", which)

        _write_stack_marker(tmp_path, stack_key)
        scaffold(tmp_path)
        _hire_pack_files(tmp_path, archetype)

        errors = _lint_errors(tmp_path)
        assert not errors, f"{archetype}/{stack_key}/binaries={binaries_available}: {errors}"
