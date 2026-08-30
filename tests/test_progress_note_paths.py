# test_progress_note_paths.py — a progress line must keep the part that VARIES.
# Every path an engine reports during a run lives under the same worktree, so a
# right-hand cut keeps the shared directory and drops the filename: four lines
# that read identically while four different files were touched.
from __future__ import annotations

import json
from pathlib import Path

from alc.engine import ProgressPrinter, elide, path_roots, shorten_path
from alc.engines.claude_code import ClaudeCodeEngine

_WORKTREE = "/private/var/folders/p6/rt1tk2pn37189vrg5y_7kwtc0000gp/T/alc-run-abc"


def _tool_use(name: str, **inp: str) -> dict:
    return {"message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


class TestShortenPath:
    def test_strips_the_worktree_prefix(self) -> None:
        roots = (f"{_WORKTREE}/",)
        assert shorten_path(f"{_WORKTREE}/scripts/install.sh", roots) == "scripts/install.sh"

    def test_leaves_a_path_outside_the_worktree_alone(self) -> None:
        roots = (f"{_WORKTREE}/",)
        assert shorten_path("/etc/hosts", roots) == "/etc/hosts"

    def test_the_worktree_root_itself_stays_readable(self) -> None:
        # Stripping would leave the empty string — worse than the full path.
        roots = (f"{_WORKTREE}/",)
        assert shorten_path(f"{_WORKTREE}/", roots) == f"{_WORKTREE}/"

    def test_no_roots_is_a_noop(self) -> None:
        assert shorten_path("/a/b/c", ()) == "/a/b/c"

    def test_matches_the_resolved_form_of_a_symlinked_temp_dir(self, tmp_path: Path) -> None:
        # macOS hands out /var/folders/... which resolves to /private/var/folders/...;
        # the engine may report either, and one root would miss half the notes.
        roots = path_roots(tmp_path)
        resolved = str(Path(tmp_path).resolve())
        assert shorten_path(f"{resolved}/main.py", roots) == "main.py"
        assert shorten_path(f"{tmp_path}/main.py", roots) == "main.py"

    def test_longest_root_wins(self, tmp_path: Path) -> None:
        # /private/... contains /var/... as a suffix, never a prefix, but ordering
        # by length keeps the match deterministic if the two ever nest.
        roots = path_roots(tmp_path)
        assert list(roots) == sorted(roots, key=len, reverse=True)

    def test_no_workdir_yields_no_roots(self) -> None:
        assert path_roots(None) == ()


class TestElide:
    def test_keeps_both_ends(self) -> None:
        assert elide("abcdefghij", 5) == "ab…ij"

    def test_result_never_exceeds_the_width(self) -> None:
        for width in range(2, 12):
            assert len(elide("abcdefghijklmnop", width)) == width

    def test_short_enough_is_untouched(self) -> None:
        assert elide("abc", 10) == "abc"

    def test_keeps_the_filename_a_right_cut_would_drop(self) -> None:
        line = f"Edit: {_WORKTREE}/scripts/install.sh"
        assert elide(line, 60).endswith("install.sh")


class TestProgressNotesShortenBeforeTruncating:
    def test_file_path_is_reported_relative_to_the_worktree(self) -> None:
        roots = (f"{_WORKTREE}/",)
        notes = ClaudeCodeEngine._progress_notes(
            _tool_use("Edit", file_path=f"{_WORKTREE}/scripts/install.sh"), roots
        )
        assert notes == ["Edit: scripts/install.sh"]

    def test_without_shortening_the_filename_is_lost(self) -> None:
        # Calibration: the note is cut at 60 columns, so an unshortened worktree
        # path spends every one of them on the prefix.
        notes = ClaudeCodeEngine._progress_notes(
            _tool_use("Edit", file_path=f"{_WORKTREE}/scripts/install.sh")
        )
        assert "install.sh" not in notes[0]

    def test_two_files_in_one_directory_stay_distinguishable(self) -> None:
        roots = (f"{_WORKTREE}/",)
        first = ClaudeCodeEngine._progress_notes(
            _tool_use("Read", file_path=f"{_WORKTREE}/src/alc/cli.py"), roots
        )
        second = ClaudeCodeEngine._progress_notes(
            _tool_use("Read", file_path=f"{_WORKTREE}/src/alc/ui/service.py"), roots
        )
        assert first != second

    def test_a_command_hint_is_untouched(self) -> None:
        roots = (f"{_WORKTREE}/",)
        notes = ClaudeCodeEngine._progress_notes(_tool_use("Bash", command="uv run pytest -q"), roots)
        assert notes == ["Bash: uv run pytest -q"]

    def test_a_tool_without_a_hint_is_just_its_name(self) -> None:
        assert ClaudeCodeEngine._progress_notes(_tool_use("TodoWrite"), ()) == ["TodoWrite"]


class TestPrinterDedupesOnTheFullLine:
    def test_two_long_distinct_lines_both_print(self, capsys) -> None:
        # They shorten to the same text; deduping on THAT would show one line
        # where two different things happened.
        printer = ProgressPrinter(max_width=30)
        printer.emit(f"Read: {_WORKTREE}/one.py")
        printer.emit(f"Read: {_WORKTREE}/two.py")
        assert capsys.readouterr().err.strip().count("\n") == 1

    def test_lines_differing_only_in_the_elided_middle_both_print(self, capsys) -> None:
        # Both shorten to the same head…tail. Deduping on the DISPLAYED text would
        # drop the second, so the comparison has to be on the full line.
        printer = ProgressPrinter(max_width=30)
        printer.emit(f"Read: {'a' * 40}one{'b' * 40}")
        printer.emit(f"Read: {'a' * 40}two{'b' * 40}")
        assert capsys.readouterr().err.strip().count("\n") == 1

    def test_a_true_repeat_still_collapses(self, capsys) -> None:
        printer = ProgressPrinter()
        printer.emit("same")
        printer.emit("same")
        assert capsys.readouterr().err.count("same") == 1

    def test_the_run_log_keeps_both_distinct_lines(self, tmp_path: Path) -> None:
        from alc.events import bind_run_log

        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            printer = ProgressPrinter(event="engine_activity", max_width=30)
            printer.emit(f"Read: {_WORKTREE}/one.py")
            printer.emit(f"Read: {_WORKTREE}/two.py")
        notes = [json.loads(line)["note"] for line in log.read_text().splitlines()]
        assert notes == [f"Read: {_WORKTREE}/one.py", f"Read: {_WORKTREE}/two.py"]


class TestReadsThatLeaveTheWorkdirAreVisible:
    """Isolation is sold as "your files stay as they are".

    A read reaching past the worktree does not break that promise — but it means
    the turn was informed by state the run does not control, and nothing in the
    Scorecard could ever show it. E2E finding 7: a repair turn read the HOST
    project's manifest from inside its isolated copy.
    """

    def test_a_path_outside_the_workdir_is_marked(self) -> None:
        roots = (f"{_WORKTREE}/",)
        notes = ClaudeCodeEngine._progress_notes(
            _tool_use("Read", file_path="/Users/me/git/alc/.alc/manifest.yaml"), roots
        )
        assert notes == ["Read: /Users/me/git/alc/.alc/manifest.yaml  ⇱ outside the workdir"]

    def test_a_path_inside_it_is_not(self) -> None:
        roots = (f"{_WORKTREE}/",)
        notes = ClaudeCodeEngine._progress_notes(
            _tool_use("Read", file_path=f"{_WORKTREE}/src/main.py"), roots
        )
        assert notes == ["Read: src/main.py"]

    def test_a_relative_hint_is_never_marked(self) -> None:
        # A relative path resolves against the workdir by definition.
        roots = (f"{_WORKTREE}/",)
        notes = ClaudeCodeEngine._progress_notes(_tool_use("Read", file_path="src/main.py"), roots)
        assert "outside" not in notes[0]

    def test_a_command_is_never_marked(self) -> None:
        roots = (f"{_WORKTREE}/",)
        notes = ClaudeCodeEngine._progress_notes(_tool_use("Bash", command="uv run pytest"), roots)
        assert "outside" not in notes[0]

    def test_nothing_is_claimed_when_the_workdir_is_unknown(self) -> None:
        # No roots means no basis for the claim — say nothing rather than guess.
        notes = ClaudeCodeEngine._progress_notes(_tool_use("Read", file_path="/etc/hosts"), ())
        assert notes == ["Read: /etc/hosts"]

    def test_the_marker_survives_the_sixty_column_cut(self) -> None:
        # The cut applies to the path; the marker is appended after it, so a long
        # outside path cannot silently lose the one word that matters.
        roots = (f"{_WORKTREE}/",)
        long_path = "/Users/me/git/alc/" + "deep/" * 20 + "manifest.yaml"
        notes = ClaudeCodeEngine._progress_notes(_tool_use("Read", file_path=long_path), roots)
        assert notes[0].endswith("⇱ outside the workdir")
