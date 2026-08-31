# test_check_progress_output.py — the Verify phase must narrate itself.
# `→ Verify (1 check(s))…` followed by silence is indistinguishable from a hang,
# and an operator who cannot tell those apart kills the run to find out.
from __future__ import annotations

from pathlib import Path

from alc.assurance import AssuranceLoop, _elapsed
from alc.engines.mock import MockEngine
from alc.models import Check
from alc.verifier import CheckResult, Verifier


def _loop(**kwargs) -> AssuranceLoop:
    return AssuranceLoop(engine=MockEngine(), verifier=Verifier(), max_repairs=0, **kwargs)


def _request(workdir: Path):
    from alc.engine import EngineRequest

    return EngineRequest(directive="do the thing", workdir=workdir)


class TestElapsed:
    def test_sub_ten_seconds_keeps_a_decimal(self) -> None:
        assert _elapsed(0.42) == "0.4s"

    def test_seconds_lose_the_decimal_once_they_stop_mattering(self) -> None:
        assert _elapsed(12.4) == "12s"

    def test_past_a_minute_reads_as_minutes(self) -> None:
        assert _elapsed(100.0) == "1m40s"

    def test_the_seconds_part_is_zero_padded(self) -> None:
        assert _elapsed(125.0) == "2m05s"


class TestCheckProgressIsNarrated:
    def test_names_each_check_and_reports_its_elapsed_time(self, tmp_path: Path, capsys) -> None:
        checks = [Check(name="marker", command=["true"])]
        _loop().run(_request(tmp_path), checks)
        err = capsys.readouterr().err
        # The name appears BEFORE the verdict — that is the whole point: it is on
        # screen while the check is still running.
        assert "· marker…" in err
        assert err.index("· marker…") < err.index("✓")

    def test_a_failing_check_is_marked_as_such(self, tmp_path: Path, capsys) -> None:
        checks = [Check(name="marker", command=["false"])]
        _loop().run(_request(tmp_path), checks)
        err = capsys.readouterr().err
        assert "· marker…" in err
        assert "✗" in err

    def test_every_check_gets_its_own_line(self, tmp_path: Path, capsys) -> None:
        checks = [
            Check(name="alpha", command=["true"]),
            Check(name="beta", command=["true"]),
        ]
        _loop().run(_request(tmp_path), checks)
        err = capsys.readouterr().err
        assert "· alpha…" in err and "· beta…" in err

    def test_a_timed_out_check_says_so_rather_than_just_failing(self, tmp_path: Path, capsys) -> None:
        class _TimeoutVerifier(Verifier):
            def run(self, checks, workdir, on_check_start=None, on_check_done=None):
                results = []
                for check in checks:
                    if on_check_start is not None:
                        on_check_start(check.name)
                    result = CheckResult(
                        name=check.name,
                        passed=False,
                        output="",
                        timed_out=True,
                        duration_s=120.0,
                        exit_code=None,
                    )
                    if on_check_done is not None:
                        on_check_done(result)
                    results.append(result)
                return results

        loop = AssuranceLoop(engine=MockEngine(), verifier=_TimeoutVerifier(), max_repairs=0)
        loop.run(_request(tmp_path), [Check(name="slow", command=["true"])])
        err = capsys.readouterr().err
        assert "timed out after 2m00s" in err
