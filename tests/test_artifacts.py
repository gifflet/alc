# test_artifacts.py — Hermetic tests for `alc artifacts [<stem>] [--json]`
#: reads the e2e evidence a `needs_service` run's
# `capture:` command produced back out of the run logs' `mandate_finished`
# events. Pure/read-only — writes JSONL fixtures directly rather than running
# real mandates, mirroring how `alc checks history` is tested
# (test_check_history.py).
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from alc.artifacts import RunArtifacts, artifact_type, latest_run_with_artifacts, run_artifacts
from alc.cli import cmd_artifacts


def _write_log(runs_dir: Path, stem: str, events: list[dict]) -> Path:
    """Write one run-log .jsonl file with the given event dicts, one per line."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{stem}.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _mandate_finished(artifacts: list[str] | None = None) -> dict:
    event = {"event": "mandate_finished", "success": True}
    if artifacts is not None:
        event["artifacts"] = artifacts
    return event


# ---------------------------------------------------------------------------
# artifact_type — display classification, purely cosmetic.
# ---------------------------------------------------------------------------


class TestArtifactType:
    def test_image_extensions(self) -> None:
        for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            assert artifact_type(f"shot{ext}") == "image"

    def test_log_extensions(self) -> None:
        assert artifact_type("health-poll.log") == "log"
        assert artifact_type("notes.txt") == "log"

    def test_data_extensions(self) -> None:
        assert artifact_type("response.json") == "data"
        assert artifact_type("page.html") == "data"

    def test_unknown_extension_falls_back_to_file(self) -> None:
        assert artifact_type("payload.bin") == "file"
        assert artifact_type("noext") == "file"

    def test_classification_is_case_insensitive(self) -> None:
        assert artifact_type("SCREENSHOT.PNG") == "image"


# ---------------------------------------------------------------------------
# run_artifacts / latest_run_with_artifacts — the pure aggregation.
# ---------------------------------------------------------------------------


class TestRunArtifacts:
    def test_raises_for_unknown_stem(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        try:
            run_artifacts(runs_dir, "nope")
        except FileNotFoundError as exc:
            assert "nope" in str(exc)
        else:
            raise AssertionError("expected FileNotFoundError")

    def test_run_with_no_artifacts_key_is_empty(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(runs_dir, "20260101T000000-task-a-aaaaaa", [_mandate_finished()])

        result = run_artifacts(runs_dir, "20260101T000000-task-a-aaaaaa")

        assert result == RunArtifacts(stem="20260101T000000-task-a-aaaaaa", artifacts=[])

    def test_reads_artifacts_from_mandate_finished(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_mandate_finished([".alc/artifacts/x/health-poll.log", ".alc/artifacts/x/shot.png"])],
        )

        result = run_artifacts(runs_dir, "20260101T000000-task-a-aaaaaa")

        assert result.artifacts == [
            ".alc/artifacts/x/health-poll.log",
            ".alc/artifacts/x/shot.png",
        ]

    def test_multiple_stages_collect_and_dedup_preserving_first_seen_order(
        self, tmp_path: Path
    ) -> None:
        # A flow/task run log holds one mandate_finished per stage.
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [
                _mandate_finished(["a.log", "shared.txt"]),
                _mandate_finished(["shared.txt", "b.log"]),
            ],
        )

        result = run_artifacts(runs_dir, "20260101T000000-task-a-aaaaaa")

        assert result.artifacts == ["a.log", "shared.txt", "b.log"]

    def test_non_string_and_missing_items_are_skipped(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [{"event": "mandate_finished", "artifacts": ["ok.log", 42, None, {"nested": True}]}],
        )

        result = run_artifacts(runs_dir, "20260101T000000-task-a-aaaaaa")

        assert result.artifacts == ["ok.log"]

    def test_non_mandate_finished_events_are_ignored(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [
                {"event": "mandate_started", "artifacts": ["should-not-appear.log"]},
                _mandate_finished(["real.log"]),
            ],
        )

        result = run_artifacts(runs_dir, "20260101T000000-task-a-aaaaaa")

        assert result.artifacts == ["real.log"]

    def test_malformed_lines_are_skipped_not_fatal(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        path = runs_dir / "20260101T000000-task-a-aaaaaa.jsonl"
        path.write_text("not json at all\n" + json.dumps(_mandate_finished(["ok.log"])) + "\n\n")

        result = run_artifacts(runs_dir, "20260101T000000-task-a-aaaaaa")

        assert result.artifacts == ["ok.log"]


class TestLatestRunWithArtifacts:
    def test_absent_runs_dir_is_none(self, tmp_path: Path) -> None:
        assert latest_run_with_artifacts(tmp_path / "nope") is None

    def test_empty_runs_dir_is_none(self, tmp_path: Path) -> None:
        (tmp_path / "runs").mkdir()
        assert latest_run_with_artifacts(tmp_path / "runs") is None

    def test_no_run_has_artifacts_is_none(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(runs_dir, "20260101T000000-task-a-aaaaaa", [_mandate_finished()])
        _write_log(runs_dir, "20260101T000001-task-b-bbbbbb", [{"event": "mandate_started"}])

        assert latest_run_with_artifacts(runs_dir) is None

    def test_picks_the_most_recently_modified_run_with_artifacts(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        older = _write_log(
            runs_dir, "20260101T000000-task-a-aaaaaa", [_mandate_finished(["old.log"])]
        )
        newer = _write_log(
            runs_dir, "20260101T000001-task-b-bbbbbb", [_mandate_finished(["new.log"])]
        )
        now = 2_000_000_000.0
        os.utime(older, (now - 100, now - 100))
        os.utime(newer, (now, now))

        result = latest_run_with_artifacts(runs_dir)

        assert result == RunArtifacts(stem="20260101T000001-task-b-bbbbbb", artifacts=["new.log"])

    def test_skips_recent_runs_with_no_artifacts_to_reach_an_older_one_that_has_some(
        self, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        with_artifacts = _write_log(
            runs_dir, "20260101T000000-task-a-aaaaaa", [_mandate_finished(["old.log"])]
        )
        without_artifacts = _write_log(
            runs_dir, "20260101T000001-task-b-bbbbbb", [_mandate_finished()]
        )
        now = 2_000_000_000.0
        os.utime(with_artifacts, (now - 100, now - 100))
        os.utime(without_artifacts, (now, now))

        result = latest_run_with_artifacts(runs_dir)

        assert result == RunArtifacts(stem="20260101T000000-task-a-aaaaaa", artifacts=["old.log"])


# ---------------------------------------------------------------------------
# CLI — `alc artifacts [<stem>] [--json]`.
# ---------------------------------------------------------------------------


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"stem": None, "json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestArtifactsCli:
    def test_no_runs_at_all_prints_a_hint(self, operator_layer: Path, monkeypatch, capsys) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_artifacts(_ns()) == 0
        out = capsys.readouterr().out
        assert "No run has captured any artifacts" in out

    def test_no_runs_json(self, operator_layer: Path, monkeypatch, capsys) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_artifacts(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data == {"stem": None, "artifacts": []}

    def test_defaults_to_the_most_recent_run_with_artifacts(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        runs_dir = operator_layer.parent / ".alc" / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_mandate_finished([".alc/artifacts/a/shot.png"])],
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_artifacts(_ns()) == 0

        out = capsys.readouterr().out
        assert "20260101T000000-task-a-aaaaaa" in out
        assert ".alc/artifacts/a/shot.png" in out
        assert "(image)" in out

    def test_unknown_stem_is_an_error(self, operator_layer: Path, monkeypatch, capsys) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_artifacts(_ns(stem="nope")) == 1
        err = capsys.readouterr().err
        assert "nope" in err

    def test_known_stem_with_no_artifacts_says_so(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        runs_dir = operator_layer.parent / ".alc" / "runs"
        _write_log(runs_dir, "20260101T000000-task-a-aaaaaa", [_mandate_finished()])
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_artifacts(_ns(stem="20260101T000000-task-a-aaaaaa")) == 0

        out = capsys.readouterr().out
        assert "captured no artifacts" in out

    def test_json_output_shape(self, operator_layer: Path, monkeypatch, capsys) -> None:
        runs_dir = operator_layer.parent / ".alc" / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_mandate_finished([".alc/artifacts/a/health-poll.log"])],
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_artifacts(_ns(stem="20260101T000000-task-a-aaaaaa", json=True)) == 0

        data = json.loads(capsys.readouterr().out)
        assert data == {
            "stem": "20260101T000000-task-a-aaaaaa",
            "artifacts": [{"path": ".alc/artifacts/a/health-poll.log", "type": "log"}],
        }

    def test_never_writes_anything(self, operator_layer: Path, monkeypatch) -> None:
        runs_dir = operator_layer.parent / ".alc" / "runs"
        _write_log(
            runs_dir, "20260101T000000-task-a-aaaaaa", [_mandate_finished(["a.log"])]
        )
        monkeypatch.chdir(operator_layer.parent)
        before = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))

        assert cmd_artifacts(_ns()) == 0

        after = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert before == after
