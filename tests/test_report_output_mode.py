"""Machine output belongs behind a flag, not in front of a person.

Every `alc run` printed about thirty-five lines of serialised model after the
four that said what happened — and the one actionable sentence a run produces,
"Isolated changes committed on branch …", was printed below all of it. There was
no --json and no --quiet; it was the only mode. `alc audit` already showed the
better shape: five readable lines and no dump.
"""

from __future__ import annotations

from alc.cli import _print_flow_report, _print_run_report
from alc.models import AttemptRecord, FlowReport, RunReport, Scorecard


def _run_report() -> RunReport:
    return RunReport(
        blueprint="chore",
        engine="mock",
        success=True,
        attempts=[AttemptRecord(index=0, engine_ok=True, failed_checks=[], checks=[])],
        scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
        output_text="done",
        changed_files=["a.py"],
    )


def _flow_report() -> FlowReport:
    return FlowReport(
        flow="ship",
        engine="mock",
        success=True,
        stages=[_run_report()],
        scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
    )


def test_the_default_is_the_human_summary_with_no_dump(capsys) -> None:
    _print_run_report(_run_report())
    out = capsys.readouterr().out

    assert "Status:   SUCCESS" in out
    assert "Scorecard: span=1" in out
    assert "a.py" in out
    assert '"blueprint"' not in out, "the serialised model must not follow the summary"


def test_json_replaces_the_summary_rather_than_following_it(capsys) -> None:
    # Matching `alc lint --json` and `alc land --json`: the flag switches mode,
    # it does not append. Appending is what made the useful lines scroll away.
    _print_run_report(_run_report(), as_json=True)
    out = capsys.readouterr().out

    assert '"blueprint": "chore"' in out
    assert "Status:   SUCCESS" not in out


def test_the_summary_still_names_the_changed_files(capsys) -> None:
    # The reason a person reads this at all.
    _print_run_report(_run_report())
    assert "Changed files:" in capsys.readouterr().out


def test_a_flow_report_follows_the_same_contract(capsys) -> None:
    report = FlowReport(
        flow="ship",
        engine="mock",
        success=True,
        stages=[_run_report()],  # one RunReport per executed stage
        scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
    )

    _print_flow_report(report)
    plain = capsys.readouterr().out
    assert "Status:   SUCCESS" in plain
    assert '"flow"' not in plain

    _print_flow_report(report, as_json=True)
    as_json = capsys.readouterr().out
    assert '"flow": "ship"' in as_json
    assert "Status:   SUCCESS" not in as_json


class TestTheScorecardSaysWhichWayIsGood:
    """Four invented words arrive with no units and no legend.

    `touch=0` on a run that changed nothing reads as neutral; on a run that
    changed something a reader has no way to tell whether high or low is what
    they wanted. Direction is the part you cannot act without.
    """

    def test_a_run_report_carries_the_legend(self, capsys) -> None:
        _print_run_report(_run_report())
        out = capsys.readouterr().out

        assert "Scorecard: span=1 passes=1 streak=1 touch=0" in out
        assert "span ↑" in out and "passes ↓" in out
        assert "streak ↑" in out and "touch ↓" in out

    def test_a_flow_report_carries_the_same_legend(self, capsys) -> None:
        _print_flow_report(_flow_report())
        out = capsys.readouterr().out

        assert "span ↑" in out and "touch ↓" in out

    def test_the_legend_never_wraps_an_eighty_column_terminal(self, capsys) -> None:
        # It is fixing ragged output; wrapping would reintroduce it.
        _print_run_report(_run_report())
        legend = next(line for line in capsys.readouterr().out.splitlines() if "span ↑" in line)

        assert len(legend) <= 80

    def test_it_sits_directly_under_the_numbers(self, capsys) -> None:
        _print_run_report(_run_report())
        lines = capsys.readouterr().out.splitlines()
        numbers_at = next(i for i, line in enumerate(lines) if line.startswith("Scorecard:"))

        assert "span ↑" in lines[numbers_at + 1]

    def test_json_mode_stays_free_of_it(self, capsys) -> None:
        import json

        _print_run_report(_run_report(), as_json=True)
        payload = capsys.readouterr().out

        assert "span ↑" not in payload
        assert json.loads(payload)["scorecard"]["span"] == 1
