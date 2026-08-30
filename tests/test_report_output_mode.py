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
