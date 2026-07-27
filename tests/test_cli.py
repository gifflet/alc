# test_cli.py — CLI entrypoint helpers.
from __future__ import annotations

from io import StringIO

from alc.cli import _build_parser, _ResilientStderr


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


class TestBuildParserDefaults:
    """`_build_parser()` is extracted from `main()` so the argparse defaults can be
    asserted WITHOUT executing any command (GAP 1 — CLI ergonomics). These pin the
    bare-read-command ergonomics: a bare read command must default, never error.
    """

    def test_bare_audit_defaults_since_to_7d(self) -> None:
        # `alc audit` with no --since aggregates a sensible trailing window.
        args = _build_parser().parse_args(["audit"])
        assert args.since == "7d"

    def test_audit_since_flag_overrides_the_default(self) -> None:
        args = _build_parser().parse_args(["audit", "--since", "24h"])
        assert args.since == "24h"

    def test_bare_checks_leaves_action_none(self) -> None:
        # No required sub-action: `alc checks` parses with checks_action == None,
        # which cmd_checks routes to the audit read view.
        args = _build_parser().parse_args(["checks"])
        assert args.checks_action is None

    def test_bare_team_leaves_action_none(self) -> None:
        # No required sub-action: `alc team` parses with team_action == None,
        # which cmd_team normalizes to `status`.
        args = _build_parser().parse_args(["team"])
        assert args.team_action is None

    def test_tick_engine_flag_is_captured(self) -> None:
        args = _build_parser().parse_args(["tick", "--engine", "mock"])
        assert args.engine == "mock"

    def test_bare_tick_defaults_engine_to_none(self) -> None:
        # No override by default — each task's own engine: still wins.
        args = _build_parser().parse_args(["tick"])
        assert args.engine is None
