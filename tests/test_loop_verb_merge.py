# test_loop_verb_merge.py — one verb for one unit.
#
# E2E finding 11, the worst naming collision in the project: `alc cycle` runs one
# iteration of a `loop` while `alc loop` repeats `cycle` — two verbs splitting one
# noun in a direction nobody guesses, landing squarely on the unattended tier.
# `alc loop <name> --once` says it in a way a reader can predict from the command
# they already know. `alc cycle` stays: it is in people's crontabs, and breaking a
# scheduled job to improve a noun is not a trade worth making.
from __future__ import annotations

import argparse

import pytest

from alc import cli as cli_mod


def _loop_ns(**over) -> argparse.Namespace:
    base = dict(
        command="loop", name="nightly", once=False, status=False, json=False,
        engine=None, concurrency=0, interval=300, reset=False, allow_dirty=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


class TestOnceDelegatesToTheOneImplementation:
    def test_once_runs_a_single_cycle(self, monkeypatch) -> None:
        seen: list[str] = []
        monkeypatch.setattr(cli_mod, "cmd_cycle", lambda a: seen.append("cycle") or 0)

        assert cli_mod.cmd_loop(_loop_ns(once=True)) == 0
        assert seen == ["cycle"], "--once must not start the repeating wrapper"

    def test_status_reports_without_running(self, monkeypatch) -> None:
        seen: list[str] = []
        monkeypatch.setattr(cli_mod, "cmd_cycle", lambda a: seen.append("cycle") or 0)

        assert cli_mod.cmd_loop(_loop_ns(status=True)) == 0
        assert seen == ["cycle"]

    def test_its_exit_code_is_the_cycles(self, monkeypatch) -> None:
        monkeypatch.setattr(cli_mod, "cmd_cycle", lambda a: 3)

        assert cli_mod.cmd_loop(_loop_ns(once=True)) == 3

    def test_without_once_it_does_not_delegate(self, monkeypatch) -> None:
        # The repeating path must stay the repeating path.
        seen: list[str] = []
        monkeypatch.setattr(cli_mod, "cmd_cycle", lambda a: seen.append("cycle") or 0)
        monkeypatch.setattr(cli_mod, "_resolve_loop", lambda a: (None, None, None, None, None, 7))

        assert cli_mod.cmd_loop(_loop_ns()) == 7
        assert seen == []


class TestTheParserCarriesTheMergedFlags:
    @staticmethod
    def _parse(argv: list[str]) -> argparse.Namespace:
        return cli_mod._build_parser().parse_args(argv)

    def test_loop_accepts_once(self) -> None:
        args = self._parse(["loop", "nightly", "--once"])

        assert args.command == "loop" and args.once is True

    def test_loop_accepts_the_cycle_only_flags(self) -> None:
        args = self._parse(["loop", "nightly", "--once", "--concurrency", "4", "--json"])

        assert args.concurrency == 4 and args.json is True

    def test_loop_still_repeats_by_default(self) -> None:
        args = self._parse(["loop", "nightly"])

        assert args.once is False and args.interval == 300

    def test_cycle_still_parses_for_existing_crontabs(self) -> None:
        args = self._parse(["cycle", "nightly", "--concurrency", "2"])

        assert args.command == "cycle" and args.concurrency == 2


class TestTheAliasWarnsWithoutChangingBehaviour:
    def test_it_warns_on_stderr_and_keeps_the_exit_code(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("sys.argv", ["alc", "cycle", "nightly"])
        monkeypatch.setattr(cli_mod, "cmd_cycle", lambda a: 0)

        with pytest.raises(SystemExit) as exit_info:
            cli_mod.main()

        assert exit_info.value.code == 0
        captured = capsys.readouterr()
        assert "deprecated" in captured.err
        assert "alc loop nightly --once" in captured.err
        assert captured.out == "", "stdout stays byte-identical for a cron consumer"

    def test_the_merged_flag_does_not_warn(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("sys.argv", ["alc", "loop", "nightly", "--once"])
        monkeypatch.setattr(cli_mod, "cmd_cycle", lambda a: 0)

        with pytest.raises(SystemExit):
            cli_mod.main()

        assert "deprecated" not in capsys.readouterr().err
