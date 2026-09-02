# test_signal_ingest.py — Hermetic tests for
# `alc signal ingest --kind K --source S --title T [--body B] [--from-file PATH] [--json]`
# and `alc signal list [--json]`. Uses the conftest `operator_layer` fixture.
from __future__ import annotations

import argparse
import json
from pathlib import Path

from alc.cli import cmd_signal
from alc.intake import load_manifest
from alc.models import Signal
from alc.signals import archive_signal, read_signals


def _ns(**overrides) -> argparse.Namespace:
    defaults = {
        "signal_action": "ingest",
        "kind": "error",
        "source": "sentry",
        "title": "NullPointerException in checkout",
        "body": None,
        "from_file": None,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _pending(operator_layer: Path):
    manifest = load_manifest(operator_layer)
    signals_dir = operator_layer.parent / manifest.signals_dir
    return read_signals(signals_dir)


# ---------------------------------------------------------------------------
# `alc signal ingest`
# ---------------------------------------------------------------------------


class TestSignalIngestFromFlags:
    def test_writes_one_signal_file(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns()) == 0

        [pending] = _pending(operator_layer)
        assert pending.signal.kind == "error"
        assert pending.signal.source == "sentry"
        assert pending.signal.title == "NullPointerException in checkout"

    def test_body_defaults_to_empty_string(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns(body=None)) == 0

        [pending] = _pending(operator_layer)
        assert pending.signal.body == ""

    def test_body_is_carried_when_given(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns(body="Traceback (most recent call last): ...")) == 0

        [pending] = _pending(operator_layer)
        assert pending.signal.body == "Traceback (most recent call last): ..."

    def test_ts_is_populated(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns()) == 0

        [pending] = _pending(operator_layer)
        assert pending.signal.ts > 0

    def test_prints_the_written_filename(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns()) == 0

        out = capsys.readouterr().out
        assert "Signal ingested:" in out

    def test_json_output_prints_the_path(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns(json=True)) == 0

        data = json.loads(capsys.readouterr().out)
        [pending] = _pending(operator_layer)
        assert data == {"path": str(pending.path)}

    def test_missing_kind_without_from_file_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns(kind=None)) == 1
        assert "[ERROR]" in capsys.readouterr().err
        assert _pending(operator_layer) == []

    def test_missing_source_without_from_file_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns(source=None)) == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_missing_title_without_from_file_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns(title=None)) == 1
        assert "[ERROR]" in capsys.readouterr().err


class TestSignalIngestFromFile:
    def test_reads_a_full_json_object(
        self, operator_layer: Path, monkeypatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        payload = tmp_path / "payload.json"
        payload.write_text(
            json.dumps(
                {
                    "kind": "issue",
                    "source": "linear",
                    "title": "Onboarding is confusing",
                    "body": "Three users reported this today.",
                    "ts": 12345.0,
                }
            )
        )

        assert cmd_signal(_ns(kind=None, source=None, title=None, from_file=str(payload))) == 0

        [pending] = _pending(operator_layer)
        assert pending.signal == Signal(
            kind="issue",
            source="linear",
            title="Onboarding is confusing",
            body="Three users reported this today.",
            ts=12345.0,
        )

    def test_missing_ts_in_payload_defaults_to_now(
        self, operator_layer: Path, monkeypatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        payload = tmp_path / "payload.json"
        payload.write_text(
            json.dumps({"kind": "review", "source": "github", "title": "nit: naming"})
        )

        assert cmd_signal(_ns(kind=None, source=None, title=None, from_file=str(payload))) == 0

        [pending] = _pending(operator_layer)
        assert pending.signal.ts > 0

    def test_missing_file_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(
            _ns(kind=None, source=None, title=None, from_file="does-not-exist.json")
        ) == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_malformed_json_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, tmp_path: Path, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        payload = tmp_path / "payload.json"
        payload.write_text("{not json")

        assert cmd_signal(
            _ns(kind=None, source=None, title=None, from_file=str(payload))
        ) == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_json_array_instead_of_object_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, tmp_path: Path, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        payload = tmp_path / "payload.json"
        payload.write_text("[1, 2, 3]")

        assert cmd_signal(
            _ns(kind=None, source=None, title=None, from_file=str(payload))
        ) == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_invalid_kind_in_payload_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, tmp_path: Path, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        payload = tmp_path / "payload.json"
        payload.write_text(
            json.dumps({"kind": "rumor", "source": "x", "title": "y"})
        )

        assert cmd_signal(
            _ns(kind=None, source=None, title=None, from_file=str(payload))
        ) == 1
        assert "[ERROR]" in capsys.readouterr().err
        assert _pending(operator_layer) == []


# ---------------------------------------------------------------------------
# `alc signal list`
# ---------------------------------------------------------------------------


class TestSignalList:
    def test_no_pending_signals_prints_a_clear_message(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_signal(_ns(signal_action="list")) == 0
        assert "No pending signals" in capsys.readouterr().out

    def test_never_writes_anything(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)
        before = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))

        assert cmd_signal(_ns(signal_action="list")) == 0

        after = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert before == after

    def test_human_output_shows_kind_source_and_title(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        cmd_signal(_ns())  # ingest one signal first

        assert cmd_signal(_ns(signal_action="list")) == 0
        out = capsys.readouterr().out

        assert "[error]" in out
        assert "sentry" in out
        assert "NullPointerException in checkout" in out

    def test_json_output_matches_read_signals(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        cmd_signal(_ns())
        capsys.readouterr()  # drain the ingest's own stdout

        assert cmd_signal(_ns(signal_action="list", json=True)) == 0
        data = json.loads(capsys.readouterr().out)

        [pending] = _pending(operator_layer)
        assert data == [{"path": str(pending.path), **pending.signal.model_dump()}]

    def test_archived_signals_are_not_listed(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        cmd_signal(_ns())
        manifest = load_manifest(operator_layer)
        signals_dir = operator_layer.parent / manifest.signals_dir
        [pending] = _pending(operator_layer)
        archive_signal(signals_dir, pending.path)

        assert cmd_signal(_ns(signal_action="list")) == 0
        assert "No pending signals" in capsys.readouterr().out
