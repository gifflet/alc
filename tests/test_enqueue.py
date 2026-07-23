# test_enqueue.py — Hermetic tests for `alc enqueue`: direct queue writes, no
# planner turn. Uses the conftest `operator_layer` fixture (ships a `ship` flow);
# specialists are added inline where needed. No model is called.
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from alc.cli import cmd_enqueue
from alc.intake import load_manifest
from alc.models import QueueTask


def _write_specialist(operator_layer: Path, name: str = "db") -> None:
    """Write a specialist yaml whose Act blueprint is the fixture's chore blueprint."""
    specialists_dir = operator_layer / "specialists"
    specialists_dir.mkdir(exist_ok=True)
    data = {
        "name": name,
        "area": "the db layer",
        "blueprint": "chore",
        "knowledge_path": f".alc/specialists/{name}.knowledge.md",
    }
    (specialists_dir / f"{name}.yaml").write_text(yaml.safe_dump(data))


def _ns(**overrides) -> argparse.Namespace:
    defaults = {
        "name": "ship",
        "task": "do the thing",
        "kind": "flow",
        "engine": None,
        "isolate": True,
        "id": None,
        "depends_on": [],
        "touches": [],
        "from_file": None,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _pending(operator_layer: Path) -> list[Path]:
    manifest = load_manifest(operator_layer)
    queue_dir = operator_layer.parent / manifest.queue_dir
    return sorted(queue_dir.glob("*.yaml")) if queue_dir.is_dir() else []


# ---------------------------------------------------------------------------
# Single task — the base `alc enqueue <name> "<task>"` path.
# ---------------------------------------------------------------------------


class TestEnqueueSingleTask:
    def test_writes_one_queue_file(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns()) == 0

        pending = _pending(operator_layer)
        assert len(pending) == 1
        qt = QueueTask.model_validate(yaml.safe_load(pending[0].read_text()))
        assert qt.flow == "ship"
        assert qt.task == "do the thing"
        assert qt.isolate is True

    def test_prints_written_filename_and_tick_hint(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns()) == 0

        out = capsys.readouterr().out
        assert "Enqueued 1 task(s):" in out
        assert _pending(operator_layer)[0].name in out
        assert "Run: alc tick" in out

    def test_json_output_lists_filenames(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(json=True)) == 0

        data = json.loads(capsys.readouterr().out)
        assert data == [_pending(operator_layer)[0].name]

    def test_no_isolate_flag_written(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(isolate=False)) == 0

        qt = QueueTask.model_validate(yaml.safe_load(_pending(operator_layer)[0].read_text()))
        assert qt.isolate is False

    def test_engine_override_written(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(engine="mock")) == 0

        raw = yaml.safe_load(_pending(operator_layer)[0].read_text())
        assert raw["engine"] == "mock"

    def test_id_and_depends_on_written(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(id="u1")) == 0
        assert cmd_enqueue(_ns(id="u2", depends_on=["u1"])) == 0

        # Each `cmd_enqueue` call is an independent dispatch_enqueue (its own
        # index-0 file with a random uid suffix), so the two files do NOT sort
        # in call order — select by id, not by position.
        raws = [yaml.safe_load(p.read_text()) for p in _pending(operator_layer)]
        assert len(raws) == 2
        raw2 = next(r for r in raws if r["id"] == "u2")
        assert raw2["depends_on"] == ["u1"]

    def test_requires_task_without_from_file(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None)) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "TASK is required" in err
        assert _pending(operator_layer) == []


# ---------------------------------------------------------------------------
# Unit existence — validated BEFORE anything is written.
# ---------------------------------------------------------------------------


class TestEnqueueValidatesUnitExists:
    def test_missing_flow_is_a_clear_error_and_writes_nothing(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(name="nosuchflow")) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert _pending(operator_layer) == []

    def test_missing_specialist_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(kind="specialist", name="nosuchspecialist")) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert _pending(operator_layer) == []

    def test_specialist_kind_writes_a_valid_task(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        _write_specialist(operator_layer, "db")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(kind="specialist", name="db", task="document")) == 0

        raw = yaml.safe_load(_pending(operator_layer)[0].read_text())
        assert raw["kind"] == "specialist"
        assert raw["name"] == "db"


# ---------------------------------------------------------------------------
# --from-file — .jsonl batch (one JSON object per line).
# ---------------------------------------------------------------------------


class TestEnqueueFromFileJsonl:
    def test_writes_one_file_per_line(
        self, operator_layer: Path, monkeypatch, tmp_path: Path
    ) -> None:
        batch = tmp_path / "tasks.jsonl"
        batch.write_text('{"task": "alpha"}\n{"task": "beta"}\n')
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(batch))) == 0

        pending = _pending(operator_layer)
        assert len(pending) == 2
        tasks = {yaml.safe_load(p.read_text())["task"] for p in pending}
        assert tasks == {"alpha", "beta"}

    def test_entry_overrides_fall_back_to_cli_defaults(
        self, operator_layer: Path, monkeypatch, tmp_path: Path
    ) -> None:
        _write_specialist(operator_layer, "db")
        batch = tmp_path / "tasks.jsonl"
        # First entry overrides kind+name; second falls back to the CLI defaults.
        batch.write_text(
            '{"kind": "specialist", "name": "db", "task": "document"}\n'
            '{"task": "plain flow task"}\n'
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(batch))) == 0

        pending = _pending(operator_layer)
        raws = [yaml.safe_load(p.read_text()) for p in pending]
        specialist_task = next(r for r in raws if r["task"] == "document")
        flow_task = next(r for r in raws if r["task"] == "plain flow task")
        assert specialist_task["kind"] == "specialist"
        assert specialist_task["name"] == "db"
        assert flow_task["flow"] == "ship"

    def test_missing_task_key_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, tmp_path: Path, capsys
    ) -> None:
        batch = tmp_path / "tasks.jsonl"
        batch.write_text('{"kind": "flow"}\n')
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(batch))) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "task" in err

    def test_malformed_json_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, tmp_path: Path, capsys
    ) -> None:
        batch = tmp_path / "tasks.jsonl"
        batch.write_text("not json\n")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(batch))) == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_one_bad_entry_writes_nothing_at_all(
        self, operator_layer: Path, monkeypatch, tmp_path: Path
    ) -> None:
        batch = tmp_path / "tasks.jsonl"
        # The second entry references a flow that does not exist.
        batch.write_text('{"task": "ok"}\n{"task": "bad", "name": "nosuchflow"}\n')
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(batch))) == 1
        assert _pending(operator_layer) == []

    def test_blank_lines_are_skipped(
        self, operator_layer: Path, monkeypatch, tmp_path: Path
    ) -> None:
        batch = tmp_path / "tasks.jsonl"
        batch.write_text('{"task": "alpha"}\n\n\n{"task": "beta"}\n')
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(batch))) == 0
        assert len(_pending(operator_layer)) == 2

    def test_touches_overlap_is_serialized(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # Same-file touches must depend on the earlier item — dispatch_enqueue's
        # derive_dependencies, exercised end to end through the CLI.
        batch_content = (
            '{"task": "alpha", "touches": ["src/app.js"]}\n'
            '{"task": "beta", "touches": ["src/app.js"]}\n'
        )
        batch = operator_layer.parent / "tasks.jsonl"
        batch.write_text(batch_content)
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(batch))) == 0

        pending = _pending(operator_layer)
        assert len(pending) == 2
        raws = [yaml.safe_load(p.read_text()) for p in pending]
        second = next(r for r in raws if r["task"] == "beta")
        assert second["depends_on"] == ["d0"]


# ---------------------------------------------------------------------------
# --from-file — plain text (any other extension).
# ---------------------------------------------------------------------------


class TestEnqueueFromFilePlainText:
    def test_one_task_per_line(
        self, operator_layer: Path, monkeypatch, tmp_path: Path
    ) -> None:
        batch = tmp_path / "tasks.txt"
        batch.write_text("first task\nsecond task\n")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(batch))) == 0

        pending = _pending(operator_layer)
        tasks = {yaml.safe_load(p.read_text())["task"] for p in pending}
        assert tasks == {"first task", "second task"}

    def test_blank_lines_and_comments_are_skipped(
        self, operator_layer: Path, monkeypatch, tmp_path: Path
    ) -> None:
        batch = tmp_path / "tasks.txt"
        batch.write_text("# a comment\n\nreal task\n   \n# another\nsecond task\n")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(batch))) == 0

        pending = _pending(operator_layer)
        tasks = {yaml.safe_load(p.read_text())["task"] for p in pending}
        assert tasks == {"real task", "second task"}

    def test_uses_cli_kind_and_name_for_every_line(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        _write_specialist(operator_layer, "db")
        batch = operator_layer.parent / "tasks.txt"
        batch.write_text("first\nsecond\n")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, kind="specialist", name="db", from_file=str(batch))) == 0

        pending = _pending(operator_layer)
        for p in pending:
            raw = yaml.safe_load(p.read_text())
            assert raw["kind"] == "specialist"
            assert raw["name"] == "db"


class TestEnqueueFromFileMissing:
    def test_missing_file_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, tmp_path: Path, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(task=None, from_file=str(tmp_path / "nope.txt"))) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert _pending(operator_layer) == []
