# test_priority.py — roadmap-phase-3.md T8: `priority: int = 0` on QueueTask.
# The drain orders each dependency WAVE by (-priority, filename); dependency
# ordering stays authoritative — priority only breaks ties among tasks already
# ready in the same wave. Covers the pure `_topological_waves` scheduler and
# the `alc enqueue --priority N` CLI wiring.
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from alc.cli import cmd_enqueue
from alc.intake import load_manifest
from alc.models import QueueTask
from alc.queue import _topological_waves


def _write_task(
    queue_dir: Path,
    stem: str,
    *,
    id: str | None = None,
    depends_on: list[str] | None = None,
    priority: int | None = None,
) -> Path:
    """Write a minimal task file with optional id/depends_on/priority."""
    lines = ["flow: demand", f'task: "{stem}"', "engine: mock", "isolate: true"]
    if id is not None:
        lines.append(f"id: {id}")
    if depends_on is not None:
        lines.append(f"depends_on: [{', '.join(depends_on)}]")
    if priority is not None:
        lines.append(f"priority: {priority}")
    path = queue_dir / f"{stem}.yaml"
    path.write_text("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------------------
# _topological_waves — priority breaks ties WITHIN a wave, never across waves.
# ---------------------------------------------------------------------------


class TestPriorityOrdersWithinAWave:
    def test_default_priority_is_filename_order(self, tmp_path: Path) -> None:
        # Byte-identical invariant: nobody sets priority -> today's ordering.
        _write_task(tmp_path, "b")
        _write_task(tmp_path, "a")
        _write_task(tmp_path, "c")
        pending = sorted(tmp_path.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [sorted(pending)]

    def test_higher_priority_runs_first_in_the_same_wave(self, tmp_path: Path) -> None:
        # "b" sorts before "z" by filename, but "z" has higher priority and must
        # go first.
        b = _write_task(tmp_path, "b", priority=0)
        z = _write_task(tmp_path, "z", priority=5)
        pending = sorted(tmp_path.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [[z, b]]

    def test_equal_priority_falls_back_to_filename(self, tmp_path: Path) -> None:
        b = _write_task(tmp_path, "b", priority=3)
        a = _write_task(tmp_path, "a", priority=3)
        pending = sorted(tmp_path.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [[a, b]]

    def test_negative_priority_runs_last(self, tmp_path: Path) -> None:
        a = _write_task(tmp_path, "a", priority=-1)
        b = _write_task(tmp_path, "b", priority=0)
        pending = sorted(tmp_path.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [[b, a]]

    def test_priority_never_jumps_a_dependency_wave(self, tmp_path: Path) -> None:
        # "b" depends on "a", so it must land in the SECOND wave no matter how
        # high its priority is — dependency ordering is authoritative.
        a = _write_task(tmp_path, "a", id="A", priority=0)
        b = _write_task(tmp_path, "b", id="B", depends_on=["A"], priority=100)
        pending = sorted(tmp_path.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [[a], [b]]

    def test_priority_orders_within_a_later_wave_too(self, tmp_path: Path) -> None:
        root = _write_task(tmp_path, "root", id="R")
        low = _write_task(
            tmp_path, "low", id="L", depends_on=["R"], priority=0
        )
        high = _write_task(
            tmp_path, "high", id="H", depends_on=["R"], priority=10
        )
        pending = sorted(tmp_path.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [[root], [high, low]]

    def test_priority_also_orders_the_cycle_collapse_wave(
        self, tmp_path: Path, capsys
    ) -> None:
        a = _write_task(tmp_path, "a", id="A", depends_on=["B"], priority=1)
        b = _write_task(tmp_path, "b", id="B", depends_on=["A"], priority=9)
        pending = sorted(tmp_path.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [[b, a]]
        assert "dependency cycle" in capsys.readouterr().err

    def test_unreadable_file_defaults_to_priority_zero(self, tmp_path: Path) -> None:
        garbage = tmp_path / "garbage.yaml"
        garbage.write_text("not: [valid, yaml super broken :::")
        high = _write_task(tmp_path, "z", priority=5)
        pending = sorted(tmp_path.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [[high, garbage]]


# ---------------------------------------------------------------------------
# QueueTask model — default and explicit priority.
# ---------------------------------------------------------------------------


class TestQueueTaskPriorityDefault:
    def test_default_priority_is_zero(self) -> None:
        qt = QueueTask(task="x")
        assert qt.priority == 0

    def test_explicit_priority_round_trips(self) -> None:
        qt = QueueTask(task="x", priority=7)
        assert qt.priority == 7


# ---------------------------------------------------------------------------
# CLI — `alc enqueue --priority N`.
# ---------------------------------------------------------------------------


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
        "priority": 0,
        "from_file": None,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _pending(operator_layer: Path) -> list[Path]:
    manifest = load_manifest(operator_layer)
    queue_dir = operator_layer.parent / manifest.queue_dir
    return sorted(queue_dir.glob("*.yaml")) if queue_dir.is_dir() else []


class TestEnqueuePriorityFlag:
    def test_priority_flag_written_to_the_task_file(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns(priority=5)) == 0

        qt = QueueTask.model_validate(yaml.safe_load(_pending(operator_layer)[0].read_text()))
        assert qt.priority == 5

    def test_default_priority_omitted_from_the_written_file(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # 0 = today's behavior -> the key is not written at all (legacy-clean file).
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_enqueue(_ns()) == 0

        raw = yaml.safe_load(_pending(operator_layer)[0].read_text())
        assert "priority" not in raw

    def test_missing_priority_attr_defaults_to_zero(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # A Namespace built without a `priority` attribute (e.g. an older caller)
        # must not crash `cmd_enqueue` — getattr degrades to 0.
        monkeypatch.chdir(operator_layer.parent)
        ns = _ns()
        del ns.priority

        assert cmd_enqueue(ns) == 0

        raw = yaml.safe_load(_pending(operator_layer)[0].read_text())
        assert "priority" not in raw
