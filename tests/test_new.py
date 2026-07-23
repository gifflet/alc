# test_new.py — Hermetic tests for `alc new <kind> <name>`: authoring a unit
# from the core scaffolds (alc.authoring), validated through the real loader
# before anything is written. Uses the conftest `operator_layer` fixture.
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from alc.cli import cmd_new
from alc.intake import load_manifest


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"kind": "flow", "name": "demo", "force": False, "from_name": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Scaffold creation, one class per kind — path, content, and loader validity.
# ---------------------------------------------------------------------------


class TestNewCreatesEachKind:
    def test_blueprint(self, operator_layer: Path, monkeypatch, capsys) -> None:
        from alc.intake import load_blueprint

        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="blueprint", name="triage")) == 0

        path = operator_layer / "blueprints" / "triage.md"
        assert path.is_file()
        assert capsys.readouterr().out.strip() == str(path)
        assert load_blueprint(operator_layer / "blueprints", "triage").name == "triage"

    def test_flow(self, operator_layer: Path, monkeypatch) -> None:
        from alc.intake import load_flow

        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="flow", name="deploy")) == 0

        path = operator_layer / "flows" / "deploy.yaml"
        assert path.is_file()
        assert load_flow(operator_layer / "flows", "deploy").name == "deploy"

    def test_specialist(self, operator_layer: Path, monkeypatch) -> None:
        from alc.intake import load_specialist

        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="specialist", name="db")) == 0

        path = operator_layer / "specialists" / "db.yaml"
        assert path.is_file()
        assert load_specialist(operator_layer / "specialists", "db").name == "db"

    def test_loop(self, operator_layer: Path, monkeypatch) -> None:
        from alc.intake import load_loop

        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="loop", name="deliver")) == 0

        path = operator_layer / "loops" / "deliver.yaml"
        assert path.is_file()
        assert load_loop(operator_layer / "loops", "deliver").name == "deliver"

    def test_primer(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="primer", name="overview")) == 0

        path = operator_layer / "primers" / "overview.md"
        assert path.is_file()
        assert "overview" in path.read_text()

    def test_creates_the_collection_dir_if_missing(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # The fixture never creates specialists_dir; `alc new` must create it.
        monkeypatch.chdir(operator_layer.parent)
        assert not (operator_layer / "specialists").exists()

        assert cmd_new(_ns(kind="specialist", name="db")) == 0

        assert (operator_layer / "specialists" / "db.yaml").is_file()


# ---------------------------------------------------------------------------
# Overwrite protection — refuses without --force.
# ---------------------------------------------------------------------------


class TestNewRefusesOverwrite:
    def test_existing_unit_without_force_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_new(_ns(kind="flow", name="ship")) == 1  # 'ship' already exists

        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "already exists" in err
        # Untouched — the fixture's ship.yaml is still there, unmodified.
        manifest = load_manifest(operator_layer)
        original = (operator_layer.parent / manifest.flows_dir / "ship.yaml").read_text()
        assert "description: Plan a change" in original

    def test_force_overwrites(self, operator_layer: Path, monkeypatch) -> None:
        from alc.intake import load_flow

        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="flow", name="ship", force=True)) == 0

        flow = load_flow(operator_layer / "flows", "ship")
        assert flow.name == "ship"
        assert [s.blueprint for s in flow.stages] == ["chore"]  # replaced by the scaffold


# ---------------------------------------------------------------------------
# Validation through the real loader — nothing invalid ever touches disk.
# ---------------------------------------------------------------------------


class TestNewValidatesBeforeWriting:
    def test_clone_from_a_kind_with_an_invalid_source_never_writes(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        # A hand-written flow that fails FlowDefinition validation (no stages).
        (operator_layer / "flows" / "broken.yaml").write_text("name: broken\n")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="flow", name="clone-of-broken", from_name="broken")) == 1

        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert not (operator_layer / "flows" / "clone-of-broken.yaml").exists()


# ---------------------------------------------------------------------------
# --from NAME — clone an existing unit, replacing its name: field.
# ---------------------------------------------------------------------------


class TestNewFromClonesExistingUnit:
    def test_clones_and_replaces_name_field(self, operator_layer: Path, monkeypatch) -> None:
        from alc.intake import load_flow

        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="flow", name="ship2", from_name="ship")) == 0

        cloned = load_flow(operator_layer / "flows", "ship2")
        assert cloned.name == "ship2"
        # The rest of the source's content (stages) is preserved verbatim.
        assert [s.blueprint for s in cloned.stages] == ["plan", "chore"]

    def test_clone_source_missing_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="flow", name="x", from_name="nosuchflow")) == 1

        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert not (operator_layer / "flows" / "x.yaml").exists()

    def test_clone_respects_overwrite_protection(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_new(_ns(kind="flow", name="ship2", from_name="ship")) == 0

        # Cloning again into the same target without --force is refused.
        assert cmd_new(_ns(kind="flow", name="ship2", from_name="ship")) == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_clone_specialist_replaces_name_field(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        from alc.intake import load_specialist

        specialists_dir = operator_layer / "specialists"
        specialists_dir.mkdir()
        (specialists_dir / "db.yaml").write_text(
            yaml.safe_dump({
                "name": "db",
                "area": "the db layer",
                "blueprint": "chore",
                "knowledge_path": ".alc/specialists/db.knowledge.md",
            })
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_new(_ns(kind="specialist", name="db2", from_name="db")) == 0

        cloned = load_specialist(specialists_dir, "db2")
        assert cloned.name == "db2"
        assert cloned.area == "the db layer"
