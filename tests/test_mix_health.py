# test_mix_health.py — Hermetic tests for T6: Mix Health, `mix_health()` in
# src/alc/stagepolicy.py and its surfacing in `alc team status`. Aggregates
# archived reports (roadmap-phase-4.md T6) by `RunReport.archetype` and pairs
# the totals with the stage's target mix — never judging when no stage is set,
# never a division by zero when no report has been archived yet.
from __future__ import annotations

import argparse
import json
from pathlib import Path

from alc.cli import cmd_team
from alc.models import Manifest
from alc.packs import pack_files
from alc.scaffold import scaffold
from alc.stagepolicy import mix_health


def _hire_packs(project_root: Path, *archetypes: str) -> None:
    """Write the pack files for each archetype onto disk (hire it)."""
    for archetype in archetypes:
        for rel_path, text in pack_files(archetype, stacks=[]).items():
            target = project_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)


def _manifest(**overrides) -> Manifest:
    defaults = dict(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
    )
    defaults.update(overrides)
    return Manifest(**defaults)


def _write_report(
    done_dir: Path,
    stem: str,
    *,
    stages: list[dict],
) -> Path:
    """Write one archived `<stem>.report.json` FlowReport with the given stages.

    Mirrors test_audit.py's `_write_report`, generalised to accept one dict per
    stage so a test can vary archetype/scorecard/usage/diffstat per stage.
    """
    done_dir.mkdir(parents=True, exist_ok=True)
    full_stages = []
    for s in stages:
        full_stages.append(
            {
                "blueprint": s.get("blueprint", "chore"),
                "engine": "mock",
                "success": True,
                "attempts": [],
                "scorecard": s.get(
                    "scorecard", {"span": 1, "passes": 1, "streak": 1, "touch": 0}
                ),
                "output_text": "",
                "changed_files": [],
                "usage": s.get("usage"),
                "archetype": s.get("archetype"),
                "diffstat": s.get("diffstat"),
            }
        )
    report = {
        "flow": "ship",
        "engine": "mock",
        "success": True,
        "stages": full_stages,
        "scorecard": {"span": 1, "passes": 1, "streak": 1, "touch": 0},
    }
    path = done_dir / f"{stem}.report.json"
    path.write_text(json.dumps(report))
    return path


# ---------------------------------------------------------------------------
# mix_health() — the aggregation function
# ---------------------------------------------------------------------------


class TestMixHealthEmpty:
    def test_missing_done_dir_is_no_data_yet(self, tmp_path: Path) -> None:
        health = mix_health(tmp_path / "done", _manifest())
        assert health.total_runs == 0
        assert health.by_archetype == []

    def test_empty_done_dir_is_no_data_yet(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        done_dir.mkdir()
        health = mix_health(done_dir, _manifest())
        assert health.total_runs == 0


class TestMixHealthCountsDirectRuns:
    def test_extra_report_dir_runs_count_and_clear_never_exercised(
        self, tmp_path: Path
    ) -> None:
        """A direct `alc run` archives its report under runs/, not the queue done/.
        Passed as extra_report_dir, those reports count too — so a sweeper run there
        buckets under 'sweeper' and clears it from idle_core (no false 'never
        exercised')."""
        done_dir = tmp_path / "done"
        runs_dir = tmp_path / "runs"
        # queue done/ has one builder task; runs/ has a direct sweeper run.
        _write_report(done_dir, "task-a", stages=[{"archetype": "builder"}])
        _write_report(runs_dir, "run-b", stages=[{"archetype": "sweeper"}])

        manifest = _manifest(stage="pre-pmf")  # core includes sweeper
        health = mix_health(done_dir, manifest, extra_report_dir=runs_dir)

        by = {b.archetype: b.runs for b in health.by_archetype}
        assert by.get("sweeper") == 1  # the runs/ report counted
        assert by.get("builder") == 1  # the done/ report still counted
        assert health.total_runs == 2
        assert "sweeper" not in [ic.archetype for ic in health.idle_core]

    def test_without_extra_report_dir_runs_are_ignored(self, tmp_path: Path) -> None:
        """Byte-identical legacy behavior: omit extra_report_dir and runs/ is unseen."""
        done_dir = tmp_path / "done"
        runs_dir = tmp_path / "runs"
        _write_report(runs_dir, "run-b", stages=[{"archetype": "sweeper"}])

        health = mix_health(done_dir, _manifest(stage="pre-pmf"))
        assert health.total_runs == 0
        assert "sweeper" in [ic.archetype for ic in health.idle_core]

    def test_since_epoch_skips_reports_older_than_the_window(self, tmp_path: Path) -> None:
        """Mix Health reflects the RECENT mix: a report older than since_epoch is not
        parsed/counted — bounding the O(n) scan on a long-lived project."""
        import os
        import time

        done_dir = tmp_path / "done"
        recent = _write_report(done_dir, "recent", stages=[{"archetype": "builder"}])
        old = _write_report(done_dir, "old", stages=[{"archetype": "sweeper"}])
        # Backdate the old report well beyond the window.
        os.utime(old, (time.time() - 90 * 86400, time.time() - 90 * 86400))

        health = mix_health(
            done_dir, _manifest(), since_epoch=time.time() - 30 * 86400
        )
        by = {b.archetype: b.runs for b in health.by_archetype}
        assert by == {"builder": 1}  # only the recent one; the old is windowed out
        assert health.total_runs == 1
        assert recent.exists() and old.exists()  # skipped, not deleted


class TestMixHealthAggregation:
    def test_buckets_by_archetype_across_reports(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(
            done_dir, "a",
            stages=[{"archetype": "builder", "scorecard": {"span": 2, "passes": 1, "streak": 1, "touch": 0}}],
        )
        _write_report(
            done_dir, "b",
            stages=[{"archetype": "builder", "scorecard": {"span": 3, "passes": 1, "streak": 1, "touch": 0}}],
        )
        _write_report(
            done_dir, "c",
            stages=[{"archetype": "sweeper", "scorecard": {"span": 1, "passes": 1, "streak": 1, "touch": 0}}],
        )

        health = mix_health(done_dir, _manifest())
        assert health.total_runs == 3

        by_name = {e.archetype: e for e in health.by_archetype}
        assert by_name["builder"].runs == 2
        assert by_name["builder"].span == 5
        assert by_name["sweeper"].runs == 1
        assert by_name["sweeper"].span == 1

    def test_cost_usd_summed_from_usage(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(
            done_dir, "a",
            stages=[{"archetype": "grower", "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.5}}],
        )
        _write_report(
            done_dir, "b",
            stages=[{"archetype": "grower", "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.25}}],
        )

        health = mix_health(done_dir, _manifest())
        grower = next(e for e in health.by_archetype if e.archetype == "grower")
        assert grower.cost_usd == 0.75

    def test_net_lines_summed_from_diffstat(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(
            done_dir, "a",
            stages=[{"archetype": "sweeper", "diffstat": {"adds": 1, "dels": 10, "files_deleted": 1}}],
        )
        _write_report(
            done_dir, "b",
            stages=[{"archetype": "sweeper", "diffstat": {"adds": 5, "dels": 2, "files_deleted": 0}}],
        )
        _write_report(done_dir, "c", stages=[{"archetype": "sweeper", "diffstat": None}])

        health = mix_health(done_dir, _manifest())
        sweeper = next(e for e in health.by_archetype if e.archetype == "sweeper")
        assert sweeper.net_lines == (1 - 10) + (5 - 2)
        assert sweeper.runs == 3  # the diffstat-less report still counts as a run

    def test_no_archetype_bucket_is_kept_but_never_special_cased(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", stages=[{"archetype": None}])

        health = mix_health(done_dir, _manifest())
        assert health.total_runs == 1
        assert health.by_archetype[0].archetype is None

    def test_unreadable_report_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        done_dir.mkdir(parents=True)
        (done_dir / "broken.report.json").write_text("not json")
        _write_report(done_dir, "ok", stages=[{"archetype": "builder"}])

        health = mix_health(done_dir, _manifest())
        assert health.total_runs == 1


class TestMixHealthStageJudgement:
    def test_no_stage_declared_yields_empty_core_and_secondary(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "builder"}])

        health = mix_health(done_dir, _manifest())
        assert health.stage is None
        assert health.core == []
        assert health.secondary == []
        # Still built — the breakdown, just never judged.
        assert health.total_runs == 1

    def test_stage_declared_carries_its_target_mix(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "builder"}])

        health = mix_health(done_dir, _manifest(stage="growth"))
        assert health.stage == "growth"
        assert set(health.core) == {"builder", "sweeper", "grower"}
        assert health.secondary == ["maintainer"]

    def test_stage_mix_override_is_reflected(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        health = mix_health(
            done_dir,
            _manifest(stage="growth", stage_mix={"core": ["maintainer"], "secondary": []}),
        )
        assert health.core == ["maintainer"]
        assert health.secondary == []


class TestMixHealthIdleCore:
    """idle_core — a core archetype with ZERO archived runs, and the RIGHT hint:
    hire it (not on the team), exercise its loop (hired, brought a loop), or route
    a demand through its blueprints (hired, no loop). The roster maps a hired
    archetype -> the loop names its pack brought.
    """

    def test_hired_with_loop_hints_to_run_the_loop(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        # sweeper exercised; maintainer hired (brought deps-refresh) but idle.
        _write_report(done_dir, "a", stages=[{"archetype": "sweeper"}])
        health = mix_health(
            done_dir,
            _manifest(stage="strong-pmf"),
            roster={"sweeper": ["sweep"], "maintainer": ["deps-refresh"], "grower": []},
        )
        maintainer = next(e for e in health.idle_core if e.archetype == "maintainer")
        assert maintainer.hired is True
        assert maintainer.hint == "run its loop (alc loop deps-refresh)"

    def test_hired_without_loops_hints_to_route_a_demand(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "sweeper"}])
        health = mix_health(
            done_dir,
            _manifest(stage="strong-pmf"),
            roster={"sweeper": ["sweep"], "maintainer": ["deps-refresh"], "grower": []},
        )
        grower = next(e for e in health.idle_core if e.archetype == "grower")
        assert grower.hired is True
        assert grower.hint == (
            'route a demand through its blueprints '
            '(alc conduct "<goal>" or alc enqueue <flow> "<task>")'
        )

    def test_absent_from_roster_hints_to_hire(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "sweeper"}])
        # maintainer/grower NOT in the roster -> not hired.
        health = mix_health(
            done_dir,
            _manifest(stage="strong-pmf"),
            roster={"sweeper": ["sweep"]},
        )
        maintainer = next(e for e in health.idle_core if e.archetype == "maintainer")
        assert maintainer.hired is False
        assert maintainer.hint == "alc team hire maintainer"

    def test_a_core_with_runs_never_appears_in_idle_core(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "sweeper"}])
        health = mix_health(
            done_dir,
            _manifest(stage="strong-pmf"),
            roster={"sweeper": ["sweep"], "maintainer": ["deps-refresh"], "grower": []},
        )
        assert "sweeper" not in {e.archetype for e in health.idle_core}

    def test_no_stage_yields_empty_idle_core(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "builder"}])
        health = mix_health(done_dir, _manifest(), roster={"builder": []})
        assert health.idle_core == []

    def test_roster_none_treats_every_idle_core_as_not_hired(self, tmp_path: Path) -> None:
        # Legacy/tests: roster=None means membership is unknown -> not hired,
        # byte-identical to the pre-roster "alc team hire X" behavior.
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "sweeper"}])
        health = mix_health(done_dir, _manifest(stage="strong-pmf"))
        idle = {e.archetype: e for e in health.idle_core}
        assert set(idle) == {"grower", "maintainer"}
        assert all(not e.hired for e in idle.values())
        assert idle["maintainer"].hint == "alc team hire maintainer"
        assert idle["grower"].hint == "alc team hire grower"


# ---------------------------------------------------------------------------
# `alc team status` — the CLI surface
# ---------------------------------------------------------------------------


def _ns(**overrides) -> argparse.Namespace:
    defaults = {
        "team_action": "status",
        "archetype": "builder",
        "member": "builder",
        "force": False,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdTeamStatusMixHealth:
    def test_no_archived_reports_prints_no_data_yet(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        scaffold(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert cmd_team(_ns(team_action="status")) == 0
        out = capsys.readouterr().out
        assert "Mix Health: no data yet" in out

    def test_json_includes_roster_and_mix_health(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        scaffold(tmp_path)
        done_dir = tmp_path / ".alc" / "queue" / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "builder"}])
        monkeypatch.chdir(tmp_path)

        assert cmd_team(_ns(team_action="status", json=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert "roster" in payload
        assert payload["mix_health"]["total_runs"] == 1
        assert payload["mix_health"]["by_archetype"][0]["archetype"] == "builder"

    def test_list_json_stays_a_bare_roster_array(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        scaffold(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert cmd_team(_ns(team_action="list", json=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list)

    def test_human_output_labels_core_secondary_and_off_mix(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        scaffold(tmp_path)
        done_dir = tmp_path / ".alc" / "queue" / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "builder"}])
        _write_report(done_dir, "b", stages=[{"archetype": "maintainer"}])
        _write_report(done_dir, "c", stages=[{"archetype": "prototyper"}])
        manifest_path = tmp_path / ".alc" / "manifest.yaml"
        manifest_path.write_text(manifest_path.read_text() + "\nstage: growth\n")
        monkeypatch.chdir(tmp_path)

        assert cmd_team(_ns(team_action="status")) == 0
        out = capsys.readouterr().out
        assert "builder" in out and "[core]" in out
        assert "maintainer" in out and "[secondary]" in out
        assert "prototyper" in out and "[off-mix]" in out

    def test_human_output_hints_a_never_exercised_core_archetype(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        scaffold(tmp_path)
        done_dir = tmp_path / ".alc" / "queue" / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "builder"}])
        manifest_path = tmp_path / ".alc" / "manifest.yaml"
        manifest_path.write_text(manifest_path.read_text() + "\nstage: growth\n")
        monkeypatch.chdir(tmp_path)

        assert cmd_team(_ns(team_action="status")) == 0
        out = capsys.readouterr().out
        # growth core = builder + sweeper + grower; only builder was ever run,
        # and neither sweeper nor grower is hired -> hire hints.
        assert "alc team hire sweeper" in out
        assert "alc team hire grower" in out

    def test_human_output_hints_exercising_an_already_hired_idle_core(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        # Bug (1): a HIRED-but-idle core archetype must be told to EXERCISE it,
        # never to (re-)hire it. maintainer + grower are hired; only sweeper ran.
        scaffold(tmp_path)
        _hire_packs(tmp_path, "maintainer", "grower")
        done_dir = tmp_path / ".alc" / "queue" / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "sweeper"}])
        manifest_path = tmp_path / ".alc" / "manifest.yaml"
        manifest_path.write_text(manifest_path.read_text() + "\nstage: strong-pmf\n")
        monkeypatch.chdir(tmp_path)

        assert cmd_team(_ns(team_action="status")) == 0
        out = capsys.readouterr().out
        assert "hired but never exercised" in out
        assert "alc loop deps-refresh" in out
        # It must NOT tell you to hire what is already on the team.
        assert "alc team hire maintainer" not in out
        assert "alc team hire grower" not in out

    def test_json_carries_idle_core(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        scaffold(tmp_path)
        _hire_packs(tmp_path, "maintainer", "grower")
        done_dir = tmp_path / ".alc" / "queue" / "done"
        _write_report(done_dir, "a", stages=[{"archetype": "sweeper"}])
        manifest_path = tmp_path / ".alc" / "manifest.yaml"
        manifest_path.write_text(manifest_path.read_text() + "\nstage: strong-pmf\n")
        monkeypatch.chdir(tmp_path)

        assert cmd_team(_ns(team_action="status", json=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        idle = {e["archetype"]: e for e in payload["mix_health"]["idle_core"]}
        assert idle["maintainer"]["hired"] is True
        assert idle["maintainer"]["hint"] == "run its loop (alc loop deps-refresh)"
