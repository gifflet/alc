# test_signals.py — Hermetic tests for roadmap-phase-5.md T1 (signal intake):
# (a) Manifest.signals_dir.
# (b) Signal — the typed pydantic model.
# (c) ingest — writes one typed JSON file under signals_dir, returns its path.
# (d) read_signals — best-effort read of pending signals, oldest first.
# (e) archive_signal — moves a consumed signal into signals_dir/done/.
from __future__ import annotations

import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from alc.models import Manifest, Signal
from alc.signals import PendingSignal, archive_signal, ingest, read_signals


def _signal(
    kind: str = "error",
    source: str = "sentry",
    title: str = "NullPointerException in checkout",
    body: str = "",
    ts: float = 100.0,
    weight: float | None = None,
) -> Signal:
    return Signal(kind=kind, source=source, title=title, body=body, ts=ts, weight=weight)


# ---------------------------------------------------------------------------
# (a) Manifest.signals_dir
# ---------------------------------------------------------------------------


class TestManifestSignalsDir:
    def test_default_value(self) -> None:
        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
        )
        assert manifest.signals_dir == ".alc/signals"


# ---------------------------------------------------------------------------
# (b) Signal — the typed pydantic model
# ---------------------------------------------------------------------------


class TestSignalModel:
    def test_required_fields_round_trip(self) -> None:
        signal = _signal(kind="issue", source="github", title="Crash on save", ts=1.0)
        assert signal.kind == "issue"
        assert signal.source == "github"
        assert signal.title == "Crash on save"
        assert signal.ts == 1.0

    def test_body_defaults_to_empty(self) -> None:
        signal = Signal(kind="feedback", source="operator", title="slow search", ts=1.0)
        assert signal.body == ""

    def test_weight_defaults_to_none(self) -> None:
        signal = Signal(kind="review", source="github", title="nit: naming", ts=1.0)
        assert signal.weight is None

    def test_weight_accepts_a_float(self) -> None:
        signal = _signal(weight=3.5)
        assert signal.weight == 3.5

    @pytest.mark.parametrize("kind", ["error", "feedback", "issue", "review"])
    def test_every_declared_kind_is_accepted(self, kind: str) -> None:
        assert _signal(kind=kind).kind == kind

    def test_unknown_kind_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Signal(kind="rumor", source="x", title="y", ts=1.0)

    def test_missing_ts_defaults_to_now(self) -> None:
        """A real external payload (a Sentry alert, a GitHub issue hook, ...)
        knows nothing about ALC's internal `ts` field — both `alc signal
        ingest` and `alc serve --webhook`'s `/signal` route validate straight
        through this model, so the default lives here, once, for both."""
        before = time.time()
        signal = Signal.model_validate({"kind": "error", "source": "x", "title": "y"})
        after = time.time()
        assert before <= signal.ts <= after

    def test_a_ts_the_caller_sends_is_kept_exactly(self) -> None:
        signal = Signal.model_validate(
            {"kind": "error", "source": "x", "title": "y", "ts": 12345.0}
        )
        assert signal.ts == 12345.0

    def test_json_round_trip(self) -> None:
        signal = _signal(body="stack trace here", ts=42.0)
        restored = Signal.model_validate_json(signal.model_dump_json())
        assert restored == signal


# ---------------------------------------------------------------------------
# (c) ingest — writes one typed JSON file, returns its path
# ---------------------------------------------------------------------------


class TestIngest:
    def test_writes_a_json_file_under_signals_dir(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        path = ingest(signals_dir, _signal())

        assert path.parent == signals_dir
        assert path.suffix == ".json"
        assert path.exists()

    def test_creates_signals_dir_when_absent(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "nested" / "signals"
        ingest(signals_dir, _signal())
        assert signals_dir.is_dir()

    def test_written_file_round_trips_through_read_signals(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        signal = _signal(kind="issue", source="linear", title="Onboarding is confusing")
        ingest(signals_dir, signal)

        [pending] = read_signals(signals_dir)
        assert pending.signal == signal

    def test_two_ingests_produce_two_distinct_files(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        ingest(signals_dir, _signal(title="first"))
        ingest(signals_dir, _signal(title="second"))

        assert len(list(signals_dir.glob("*.json"))) == 2

    def test_filename_carries_the_kind(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        path = ingest(signals_dir, _signal(kind="review", title="nit"))
        assert path.name.startswith("review-")


# ---------------------------------------------------------------------------
# (d) read_signals — best-effort, oldest first
# ---------------------------------------------------------------------------


class TestReadSignals:
    def test_absent_dir_yields_empty_list(self, tmp_path: Path) -> None:
        assert read_signals(tmp_path / "signals") == []

    def test_empty_dir_yields_empty_list(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        assert read_signals(signals_dir) == []

    def test_returns_pending_signal_with_path_and_model(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        signal = _signal()
        path = ingest(signals_dir, signal)

        [pending] = read_signals(signals_dir)
        assert isinstance(pending, PendingSignal)
        assert pending.path == path
        assert pending.signal == signal

    def test_sorted_oldest_first_by_ts_regardless_of_ingest_order(
        self, tmp_path: Path
    ) -> None:
        signals_dir = tmp_path / "signals"
        ingest(signals_dir, _signal(title="newer", ts=200.0))
        ingest(signals_dir, _signal(title="older", ts=100.0))

        pending = read_signals(signals_dir)
        assert [p.signal.title for p in pending] == ["older", "newer"]

    def test_malformed_json_file_is_skipped(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        ingest(signals_dir, _signal(title="good"))
        (signals_dir / "bad.json").write_text("not json")

        pending = read_signals(signals_dir)
        assert [p.signal.title for p in pending] == ["good"]

    def test_json_with_wrong_shape_is_skipped(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        ingest(signals_dir, _signal(title="good"))
        (signals_dir / "bad.json").write_text('{"not": "a signal"}')

        pending = read_signals(signals_dir)
        assert [p.signal.title for p in pending] == ["good"]

    def test_unreadable_entry_is_skipped(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        ingest(signals_dir, _signal(title="good"))
        (signals_dir / "oops.json").mkdir()  # a directory -> read_text() raises

        pending = read_signals(signals_dir)
        assert [p.signal.title for p in pending] == ["good"]

    def test_done_subdirectory_is_never_returned(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        path = ingest(signals_dir, _signal())
        archive_signal(signals_dir, path)

        assert read_signals(signals_dir) == []


# ---------------------------------------------------------------------------
# (e) archive_signal — moves a consumed signal into signals_dir/done/
# ---------------------------------------------------------------------------


class TestArchiveSignal:
    def test_moves_file_into_done_subdir(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        path = ingest(signals_dir, _signal())

        archive_signal(signals_dir, path)

        assert not path.exists()
        assert (signals_dir / "done" / path.name).exists()

    def test_archived_content_is_preserved(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        signal = _signal(title="preserved")
        path = ingest(signals_dir, signal)

        archive_signal(signals_dir, path)

        archived = signals_dir / "done" / path.name
        assert Signal.model_validate_json(archived.read_text()) == signal

    def test_second_archive_of_the_same_file_never_raises(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        path = ingest(signals_dir, _signal())

        archive_signal(signals_dir, path)
        archive_signal(signals_dir, path)  # already moved -> best-effort no-op

        assert (signals_dir / "done" / path.name).exists()

    def test_archiving_a_never_ingested_path_never_raises(self, tmp_path: Path) -> None:
        signals_dir = tmp_path / "signals"
        archive_signal(signals_dir, signals_dir / "ghost.json")  # never crashes
