# test_cli.py — CLI entrypoint helpers.
from __future__ import annotations

from io import StringIO

from alc.cli import _ResilientStderr


class _BrokenStream:
    """A stream whose write/flush always raise BrokenPipeError (closed reader)."""

    def write(self, s: str) -> int:
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self) -> None:
        raise BrokenPipeError(32, "Broken pipe")


class TestResilientStderr:
    def test_swallows_broken_pipe_on_write_and_flush(self) -> None:
        # A broken progress pipe must never raise — the work must not crash on it.
        stream = _ResilientStderr(_BrokenStream())
        assert stream.write("→ claude-code done") == len("→ claude-code done")
        stream.flush()  # does not raise

    def test_swallows_oserror(self) -> None:
        class _OSErrStream:
            def write(self, s: str) -> int:
                raise OSError("errno 9")

            def flush(self) -> None:
                raise OSError("errno 9")

        stream = _ResilientStderr(_OSErrStream())
        assert stream.write("x") == 1
        stream.flush()

    def test_delegates_normal_writes_and_attributes(self) -> None:
        buf = StringIO()
        stream = _ResilientStderr(buf)
        stream.write("hello")
        stream.flush()
        assert buf.getvalue() == "hello"
        # __getattr__ forwards other stream attributes (e.g. writable()).
        assert stream.writable() is True
