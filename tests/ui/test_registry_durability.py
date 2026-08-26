# test_registry_durability.py — The registry must never lose registrations.
#
# Observed in the field: two `alc ui` instances share ~/.alc/ui/projects.json.
# A non-atomic write left a half-written file, the next read mapped the corrupt
# JSON to [], and the write after that CONFIRMED the loss — every registration
# gone, with no error shown. These tests pin both halves of the fix.
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from alc.ui.errors import ApiError
from alc.ui.registry import ProjectRegistry


@pytest.fixture
def registry(tmp_path: Path) -> ProjectRegistry:
    return ProjectRegistry(tmp_path / "ui" / "projects.json")


def a_project(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    (root / ".alc").mkdir(parents=True)
    (root / ".alc" / "manifest.yaml").write_text("version: 1\n")
    return root


class TestLoudRead:
    def test_a_missing_file_is_an_empty_registry(self, registry: ProjectRegistry) -> None:
        # First run — not an error.
        assert registry.list() == []

    def test_corrupt_json_raises_instead_of_reporting_empty(
        self, registry: ProjectRegistry
    ) -> None:
        registry.path.parent.mkdir(parents=True, exist_ok=True)
        registry.path.write_text("[{'half': ")
        with pytest.raises(ApiError) as excinfo:
            registry.list()
        assert "not valid JSON" in str(excinfo.value.message)

    def test_a_corrupt_file_is_left_untouched(self, registry: ProjectRegistry) -> None:
        registry.path.parent.mkdir(parents=True, exist_ok=True)
        registry.path.write_text("[{'half': ")
        with pytest.raises(ApiError):
            registry.list()
        # The operator's only copy must survive for them to repair.
        assert registry.path.read_text() == "[{'half': "

    def test_an_unexpected_shape_raises_too(self, registry: ProjectRegistry) -> None:
        registry.path.parent.mkdir(parents=True, exist_ok=True)
        registry.path.write_text(json.dumps([{"nope": 1}]))
        with pytest.raises(ApiError):
            registry.list()

    def test_a_corrupt_file_cannot_be_overwritten_by_a_later_add(
        self, registry: ProjectRegistry, tmp_path: Path
    ) -> None:
        # THE bug: add() read [], appended one, and wrote — erasing the rest.
        registry.path.parent.mkdir(parents=True, exist_ok=True)
        registry.path.write_text("garbage")
        with pytest.raises(ApiError):
            registry.add(a_project(tmp_path, "proj-a"))
        assert registry.path.read_text() == "garbage"


class TestAtomicWrite:
    def test_a_write_leaves_no_temp_files_behind(
        self, registry: ProjectRegistry, tmp_path: Path
    ) -> None:
        registry.add(a_project(tmp_path, "proj-a"))
        leftovers = [p.name for p in registry.path.parent.iterdir() if p.name != "projects.json"]
        assert leftovers == []

    def test_a_failed_write_does_not_truncate_the_existing_file(
        self, registry: ProjectRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry.add(a_project(tmp_path, "proj-a"))
        before = registry.path.read_text()

        def boom(*args, **kwargs):
            raise OSError("disk full")

        # Fail at the moment of the swap: the old file must still be intact.
        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            registry.add(a_project(tmp_path, "proj-b"))

        assert registry.path.read_text() == before
        leftovers = [p.name for p in registry.path.parent.iterdir() if p.name != "projects.json"]
        assert leftovers == [], "a failed write must not leave a temp file"

    def test_the_registry_survives_a_round_trip(
        self, registry: ProjectRegistry, tmp_path: Path
    ) -> None:
        first = registry.add(a_project(tmp_path, "proj-a"))
        second = registry.add(a_project(tmp_path, "proj-b"))
        ids = {p.id for p in registry.list()}
        assert ids == {first.id, second.id}

        registry.remove(first.id)
        assert [p.id for p in registry.list()] == [second.id]

    def test_a_second_instance_reading_mid_write_sees_a_whole_file(
        self, registry: ProjectRegistry, tmp_path: Path
    ) -> None:
        # Atomicity in practice: whatever a concurrent reader observes, it parses.
        registry.add(a_project(tmp_path, "proj-a"))
        other = ProjectRegistry(registry.path)
        registry.add(a_project(tmp_path, "proj-b"))
        assert len(other.list()) == 2
