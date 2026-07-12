# test_watch.py — File-watching classification and run-log tailing.
#
# The watch logic is split so it is covered DETERMINISTICALLY without watchfiles:
# classify_change() is a pure function and Watcher._handle/_emit_run_lines are
# driven directly. A real watchfiles end-to-end test was intentionally left out:
# it proved timing-flaky in this environment (the OS notification is not
# guaranteed within a bounded wait), so the plan's "só se for estável" clause
# applies — the wiring that feeds these functions from awatch is exercised
# manually via `alc ui`.
from __future__ import annotations

from pathlib import Path

from alc.ui.watch import Watcher, classify_change


class _RecordingBus:
    """Minimal bus stub capturing every published message."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def publish(self, message: dict) -> None:
        self.messages.append(message)


def _alc(tmp_path: Path) -> Path:
    alc = tmp_path / ".alc"
    alc.mkdir(parents=True, exist_ok=True)
    return alc


class TestClassifyChange:
    def test_manifest(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "manifest.yaml") == {
            "type": "config_changed",
            "resource": "manifest",
        }

    def test_blueprint(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "blueprints" / "chore.md") == {
            "type": "config_changed",
            "resource": "blueprints",
        }

    def test_queue_pending(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "queue" / "job.yaml") == {"type": "queue_changed"}

    def test_queue_done_report(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        result = classify_change(alc, alc / "queue" / "done" / "job.report.json")
        assert result == {"type": "report_added", "stem": "job"}

    def test_run_log(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        result = classify_change(alc, alc / "runs" / "20250101T000000-run-x-abc123.jsonl")
        assert result == {"type": "run", "stem": "20250101T000000-run-x-abc123"}

    def test_loop_state(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "loops" / "deliver.state.json") == {
            "type": "loop_changed",
            "name": "deliver",
        }

    def test_run_configs(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "ui" / "run-configs.json") == {
            "type": "run_configs_changed",
        }

    def test_unrelated_path_is_none(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, tmp_path / "README.md") is None
        assert classify_change(alc, alc / "bundles" / "x.jsonl") is None
        assert classify_change(alc, alc / "ui" / "layout.json") is None


class TestRunTailing:
    def test_emit_only_new_lines(self, tmp_path: Path) -> None:
        bus = _RecordingBus()
        watcher = Watcher(registry=None, bus=bus)  # type: ignore[arg-type]
        runs = _alc(tmp_path) / "runs"
        runs.mkdir()
        log = runs / "20250101T000000-run-x-abc123.jsonl"
        log.write_text('{"event": "act_started", "attempt": 1}\n')

        watcher._emit_run_lines("p1", log)
        assert len(bus.messages) == 1
        assert bus.messages[0]["type"] == "run_event"
        assert bus.messages[0]["event"]["event"] == "act_started"

        with log.open("a") as fh:
            fh.write('{"event": "act_finished", "attempt": 1, "ok": true}\n')
        watcher._emit_run_lines("p1", log)
        assert len(bus.messages) == 2
        assert bus.messages[1]["event"]["event"] == "act_finished"

    def test_handle_classifies_and_tags_project(self, tmp_path: Path) -> None:
        bus = _RecordingBus()
        watcher = Watcher(registry=None, bus=bus)  # type: ignore[arg-type]
        alc = _alc(tmp_path)
        blueprint = alc / "blueprints" / "chore.md"
        blueprint.parent.mkdir(parents=True)
        blueprint.write_text("x")

        watcher._handle(blueprint, {alc.resolve(): "p1"})
        assert bus.messages[-1] == {
            "type": "config_changed",
            "resource": "blueprints",
            "project_id": "p1",
        }
