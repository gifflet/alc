# test_schedule.py — roadmap-phase-3.md T13: `alc schedule install|list|remove`.
#
# Coverage:
#   (1) Pure helpers in alc.schedule: parse_every, marker, build_line,
#       resolve_binary, upsert/remove/list_entries — no crontab touched.
#   (2) The CLI (`cmd_schedule`) end-to-end against a FAKE `crontab` binary
#       (a tiny script backed by a tmp-path state file, put first on PATH) —
#       the real user crontab is never read or written.
#   (3) The "no crontab on this platform" fallback: PATH scrubbed of any
#       `crontab`, install/list/remove degrade to printing instead of failing.
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from alc.cli import cmd_schedule
from alc.schedule import (
    build_line,
    has_crontab,
    list_entries,
    marker,
    parse_every,
    remove,
    resolve_binary,
    upsert,
)

# ---------------------------------------------------------------------------
# (1) Pure helpers
# ---------------------------------------------------------------------------


class TestParseEvery:
    def test_minutes(self) -> None:
        assert parse_every("15m") == "*/15 * * * *"

    def test_hours(self) -> None:
        assert parse_every("2h") == "0 */2 * * *"

    def test_rejects_bad_unit(self) -> None:
        with pytest.raises(ValueError, match="unsupported --every"):
            parse_every("15s")

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            parse_every("0m")

    def test_rejects_minutes_at_or_above_60(self) -> None:
        with pytest.raises(ValueError, match="under 60"):
            parse_every("60m")

    def test_rejects_hours_at_or_above_24(self) -> None:
        with pytest.raises(ValueError, match="under 24"):
            parse_every("24h")

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            parse_every("often")


class TestMarker:
    def test_tick_has_no_name(self) -> None:
        assert marker("tick", None) == "# alc-schedule:tick"

    def test_cycle_carries_its_name(self) -> None:
        assert marker("cycle", "deliver") == "# alc-schedule:cycle:deliver"

    def test_different_loops_get_different_markers(self) -> None:
        assert marker("cycle", "a") != marker("cycle", "b")


class TestBuildLine:
    def test_line_shape(self) -> None:
        line = build_line("tick", None, Path("/proj"), "*/15 * * * *", ["/usr/bin/alc"])
        assert line == (
            "*/15 * * * * cd /proj && /usr/bin/alc tick # alc-schedule:tick"
        )

    def test_cycle_writes_the_current_spelling_and_keeps_its_marker(self) -> None:
        # The target keyword stays `cycle` — the marker keys on it, so an entry
        # installed before the verbs merged still resolves for list/remove. What
        # goes INTO cron is `alc loop <name> --once`, so a scheduled fire does
        # not mail the operator a deprecation notice every time it runs.
        line = build_line(
            "cycle", "deliver", Path("/proj"), "0 */2 * * *", ["/usr/bin/alc"]
        )
        assert line == (
            "0 */2 * * * cd /proj && /usr/bin/alc loop deliver --once "
            "# alc-schedule:cycle:deliver"
        )

    def test_a_scheduled_line_never_uses_the_deprecated_verb(self) -> None:
        line = build_line("cycle", "deliver", Path("/proj"), "*/5 * * * *", ["/usr/bin/alc"])

        assert " cycle deliver" not in line

    def test_paths_with_spaces_are_quoted(self) -> None:
        line = build_line(
            "tick", None, Path("/my proj"), "*/15 * * * *", ["/usr/bin/alc"]
        )
        assert "cd '/my proj'" in line


class TestResolveBinary:
    def test_prefers_the_console_script_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_alc = tmp_path / "alc"
        fake_alc.write_text("#!/bin/sh\n")
        fake_alc.chmod(fake_alc.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", str(tmp_path))

        assert resolve_binary() == [str(fake_alc.resolve())]

    def test_falls_back_to_the_interpreter_module_when_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", str(tmp_path))  # empty dir -> no `alc`

        assert resolve_binary() == [sys.executable, "-m", "alc"]


class TestUpsertRemoveListEntries:
    def test_upsert_appends_a_fresh_entry(self) -> None:
        result = upsert([], "tick", None, "L1 # alc-schedule:tick")
        assert result == ["L1 # alc-schedule:tick"]

    def test_upsert_is_idempotent(self) -> None:
        first = upsert([], "tick", None, "L1 # alc-schedule:tick")
        second = upsert(first, "tick", None, "L1 # alc-schedule:tick")
        assert second == ["L1 # alc-schedule:tick"]

    def test_upsert_replaces_a_changed_cadence_without_duplicating(self) -> None:
        first = upsert([], "tick", None, "*/15 * * * * ... # alc-schedule:tick")
        second = upsert(first, "tick", None, "*/5 * * * * ... # alc-schedule:tick")
        assert second == ["*/5 * * * * ... # alc-schedule:tick"]

    def test_upsert_never_touches_an_operator_line(self) -> None:
        operator_line = "0 3 * * * /home/me/backup.sh"
        result = upsert([operator_line], "tick", None, "L1 # alc-schedule:tick")
        assert operator_line in result
        assert result == [operator_line, "L1 # alc-schedule:tick"]

    def test_upsert_keeps_a_different_cycle_loop_untouched(self) -> None:
        other = "* * * * * alc cycle other # alc-schedule:cycle:other"
        result = upsert([other], "cycle", "deliver", "L1 # alc-schedule:cycle:deliver")
        assert other in result
        assert "L1 # alc-schedule:cycle:deliver" in result

    def test_remove_drops_only_the_matching_entry(self) -> None:
        operator_line = "0 3 * * * /home/me/backup.sh"
        entry = "L1 # alc-schedule:tick"
        assert remove([operator_line, entry], "tick", None) == [operator_line]

    def test_remove_is_a_noop_when_nothing_matches(self) -> None:
        operator_line = "0 3 * * * /home/me/backup.sh"
        assert remove([operator_line], "tick", None) == [operator_line]

    def test_list_entries_filters_to_alc_lines_only(self) -> None:
        operator_line = "0 3 * * * /home/me/backup.sh"
        entry = "L1 # alc-schedule:tick"
        assert list_entries([operator_line, entry]) == [entry]


# ---------------------------------------------------------------------------
# (2) CLI against a fake `crontab` on PATH
# ---------------------------------------------------------------------------


def _install_fake_crontab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a fake `crontab` binary first on PATH; return its backing state file.

    The fake emulates just enough of real crontab(1) for these tests: `-l`
    prints the state file (exit 1, mimicking "no crontab for user", when it
    does not exist yet) and `-` overwrites it from stdin. No real crontab is
    ever read or written.
    """
    state = tmp_path / "crontab.state"
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    script = bin_dir / "crontab"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys, pathlib\n"
        f"STATE = pathlib.Path({str(state)!r})\n"
        "arg = sys.argv[1] if len(sys.argv) > 1 else None\n"
        "if arg == '-l':\n"
        "    if not STATE.exists():\n"
        "        sys.exit(1)  # mimic 'no crontab for user'\n"
        "    sys.stdout.write(STATE.read_text())\n"
        "elif arg == '-':\n"
        "    STATE.write_text(sys.stdin.read())\n"
        "else:\n"
        "    sys.exit(2)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return state


@pytest.fixture
def fake_crontab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return _install_fake_crontab(tmp_path, monkeypatch)


def _install_ns(**overrides) -> argparse.Namespace:
    defaults = {
        "schedule_action": "install", "target": "tick", "name": None, "every": "15m",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _remove_ns(**overrides) -> argparse.Namespace:
    defaults = {"schedule_action": "remove", "target": "tick", "name": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _list_ns(**overrides) -> argparse.Namespace:
    defaults = {"schedule_action": "list", "json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestScheduleInstallCli:
    def test_installs_one_entry(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_install_ns()) == 0

        lines = fake_crontab.read_text().splitlines()
        assert len(lines) == 1
        assert "# alc-schedule:tick" in lines[0]
        assert "Installed:" in capsys.readouterr().out

    def test_running_install_twice_does_not_duplicate(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_install_ns()) == 0
        assert cmd_schedule(_install_ns()) == 0

        lines = fake_crontab.read_text().splitlines()
        assert len(lines) == 1

    def test_reinstalling_with_a_new_cadence_replaces_the_entry(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        cmd_schedule(_install_ns(every="15m"))
        cmd_schedule(_install_ns(every="5m"))

        lines = fake_crontab.read_text().splitlines()
        assert len(lines) == 1
        assert lines[0].startswith("*/5 * * * *")

    def test_cycle_target_requires_a_name(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_install_ns(target="cycle")) == 1
        assert "requires a loop NAME" in capsys.readouterr().err
        assert not fake_crontab.exists()  # validation failed before any crontab I/O

    def test_tick_target_rejects_a_name(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_install_ns(target="tick", name="deliver")) == 1
        assert "takes no NAME" in capsys.readouterr().err

    def test_bad_every_is_a_clear_error_not_a_crash(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_install_ns(every="often")) == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_two_loops_coexist_as_two_entries(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        cmd_schedule(_install_ns(target="cycle", name="deliver"))
        cmd_schedule(_install_ns(target="cycle", name="sweep"))

        lines = fake_crontab.read_text().splitlines()
        assert len(lines) == 2
        assert any("alc-schedule:cycle:deliver" in line for line in lines)
        assert any("alc-schedule:cycle:sweep" in line for line in lines)

    def test_installed_command_uses_the_project_cwd(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        cmd_schedule(_install_ns())

        line = fake_crontab.read_text().strip()
        assert f"cd {operator_layer.parent}" in line


class TestScheduleRemoveCli:
    def test_removes_only_its_own_entry(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        fake_crontab.write_text("0 3 * * * /home/me/backup.sh\n")  # operator's own line
        cmd_schedule(_install_ns())

        assert cmd_schedule(_remove_ns()) == 0

        lines = fake_crontab.read_text().splitlines()
        assert lines == ["0 3 * * * /home/me/backup.sh"]
        assert "Removed" in capsys.readouterr().out

    def test_removing_an_absent_entry_says_so_and_exits_zero(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_remove_ns()) == 0
        assert "No scheduled entry" in capsys.readouterr().out

    def test_removing_one_cycle_leaves_another_untouched(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        cmd_schedule(_install_ns(target="cycle", name="deliver"))
        cmd_schedule(_install_ns(target="cycle", name="sweep"))

        cmd_schedule(_remove_ns(target="cycle", name="deliver"))

        lines = fake_crontab.read_text().splitlines()
        assert len(lines) == 1
        assert "alc-schedule:cycle:sweep" in lines[0]


class TestScheduleListCli:
    def test_lists_installed_entries(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        fake_crontab.write_text("0 3 * * * /home/me/backup.sh\n")
        cmd_schedule(_install_ns())

        assert cmd_schedule(_list_ns()) == 0

        out = capsys.readouterr().out
        assert "alc-schedule:tick" in out
        assert "backup.sh" not in out  # never surfaces an operator-written line

    def test_json_output(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        cmd_schedule(_install_ns())
        capsys.readouterr()  # discard the install's own "Installed: ..." line

        assert cmd_schedule(_list_ns(json=True)) == 0

        entries = json.loads(capsys.readouterr().out)
        assert len(entries) == 1
        assert "alc-schedule:tick" in entries[0]

    def test_empty_says_so(
        self, operator_layer: Path, fake_crontab: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_list_ns()) == 0
        assert "No ALC-scheduled entries" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# (3) No crontab on this platform — print, never fail.
# ---------------------------------------------------------------------------


@pytest.fixture
def no_crontab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scrub PATH down to an empty directory: no `crontab` binary reachable."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()
    assert has_crontab() is False


class TestScheduleWithoutCrontab:
    def test_install_prints_the_line_and_exits_cleanly(
        self, operator_layer: Path, no_crontab: None, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_install_ns()) == 0

        out = capsys.readouterr().out
        assert "add this line to your scheduler" in out
        assert "alc-schedule:tick" in out

    def test_list_reports_no_crontab(
        self, operator_layer: Path, no_crontab: None, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_list_ns()) == 0
        assert "No `crontab`" in capsys.readouterr().out

    def test_remove_reports_no_crontab(
        self, operator_layer: Path, no_crontab: None, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_schedule(_remove_ns()) == 0
        assert "No `crontab`" in capsys.readouterr().out
