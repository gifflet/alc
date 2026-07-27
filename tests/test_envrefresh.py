# test_envrefresh.py — The env-refresh leaf: reinstall the ecosystem BEFORE the
# checks when a run changes a dependency manifest, so type-check/build/test see
# the NEW versions instead of the stale symlinked ones (the deps-bump false green).
# Hermetic: real subprocesses via `sh -c`, tmp_path only, no model called.
from __future__ import annotations

import json
from pathlib import Path

from alc.envrefresh import has_refresh, make_env_refresh
from alc.events import bind_run_log
from alc.models import ProvisionSpec


# ---------------------------------------------------------------------------
# has_refresh
# ---------------------------------------------------------------------------


class TestHasRefresh:
    def test_true_when_any_spec_declares_a_refresh(self) -> None:
        provisions = [
            ProvisionSpec(link=".env"),
            ProvisionSpec(
                link="node_modules",
                refresh=["npm", "install"],
                when_changed=["package.json"],
            ),
        ]
        assert has_refresh(provisions) is True

    def test_false_when_no_spec_declares_a_refresh(self) -> None:
        assert has_refresh([ProvisionSpec(link="node_modules")]) is False

    def test_false_for_empty(self) -> None:
        assert has_refresh([]) is False


# ---------------------------------------------------------------------------
# make_env_refresh — the memoized closure
# ---------------------------------------------------------------------------


def _spec(refresh: list[str], when_changed: list[str], path: str = "node_modules") -> ProvisionSpec:
    return ProvisionSpec(link=path, refresh=refresh, when_changed=when_changed)


class TestMakeEnvRefresh:
    def test_no_matched_change_is_a_noop(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"v":"1"}\n')
        refresh = make_env_refresh(
            provisions=[_spec(["sh", "-c", "touch ran.txt"], ["package.json"])],
            workdir=tmp_path,
            changed_files=lambda: ["src/foo.py"],  # no match
            timeout_s=30,
            max_output_chars=4096,
        )
        assert refresh() is None
        # The install command never ran — no side effect.
        assert not (tmp_path / "ran.txt").exists()

    def test_matched_change_runs_the_command_in_workdir(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"v":"1"}\n')
        refresh = make_env_refresh(
            provisions=[_spec(["sh", "-c", "echo installed > installed.txt"], ["package.json"])],
            workdir=tmp_path,
            changed_files=lambda: ["package.json"],
            timeout_s=30,
            max_output_chars=4096,
        )
        assert refresh() is None
        # cwd was the workdir — the relative-path write landed there.
        assert (tmp_path / "installed.txt").read_text().strip() == "installed"

    def test_failing_command_returns_failed_result_and_does_not_memo(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "package.json").write_text('{"v":"1"}\n')
        refresh = make_env_refresh(
            provisions=[
                _spec(
                    ["sh", "-c", "echo x >> count.txt; echo boom-stderr >&2; exit 3"],
                    ["package.json"],
                )
            ],
            workdir=tmp_path,
            changed_files=lambda: ["package.json"],
            timeout_s=30,
            max_output_chars=4096,
        )
        first = refresh()
        assert first is not None
        assert first.name == "env-refresh"
        assert first.passed is False
        assert first.exit_code == 3
        assert "boom-stderr" in first.output

        # A failure stores no memo, so the NEXT attempt retries the install.
        second = refresh()
        assert second is not None and second.passed is False
        assert (tmp_path / "count.txt").read_text().count("x") == 2

    def test_unchanged_content_skips_second_call(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"v":"1"}\n')
        refresh = make_env_refresh(
            provisions=[_spec(["sh", "-c", "echo x >> count.txt"], ["package.json"])],
            workdir=tmp_path,
            changed_files=lambda: ["package.json"],
            timeout_s=30,
            max_output_chars=4096,
        )
        assert refresh() is None
        assert refresh() is None
        # The content did not change between calls -> installed exactly once.
        assert (tmp_path / "count.txt").read_text().count("x") == 1

    def test_install_that_writes_a_matched_file_does_not_loop(self, tmp_path: Path) -> None:
        # The install writes package-lock.json — itself a `when_changed` file. Hashing
        # the POST-install state prevents an install -> lockfile-changed -> reinstall loop.
        (tmp_path / "package.json").write_text('{"v":"2"}\n')
        refresh = make_env_refresh(
            provisions=[
                _spec(
                    ["sh", "-c", "echo x >> count.txt; echo locked >> package-lock.json"],
                    ["package.json", "package-lock.json"],
                )
            ],
            workdir=tmp_path,
            # Simulates git status: package-lock.json only appears AFTER the install.
            changed_files=lambda: [
                p for p in ("package.json", "package-lock.json") if (tmp_path / p).exists()
            ],
            timeout_s=30,
            max_output_chars=4096,
        )
        assert refresh() is None
        assert refresh() is None
        assert refresh() is None
        # Exactly one install despite the lockfile now being a changed, matched file.
        assert (tmp_path / "count.txt").read_text().count("x") == 1

    def test_content_that_genuinely_changes_reinstalls(self, tmp_path: Path) -> None:
        pkg = tmp_path / "package.json"
        pkg.write_text('{"v":"1"}\n')
        refresh = make_env_refresh(
            provisions=[_spec(["sh", "-c", "echo x >> count.txt"], ["package.json"])],
            workdir=tmp_path,
            changed_files=lambda: ["package.json"],
            timeout_s=30,
            max_output_chars=4096,
        )
        assert refresh() is None
        pkg.write_text('{"v":"2"}\n')  # a genuine second bump
        assert refresh() is None
        assert (tmp_path / "count.txt").read_text().count("x") == 2

    def test_symlinked_dst_is_materialized_before_install(self, tmp_path: Path) -> None:
        # Operator's shared node_modules.
        source = tmp_path / "operator_nm"
        source.mkdir()
        (source / "lib.txt").write_text("oldAPI\n")

        workdir = tmp_path / "wt"
        workdir.mkdir()
        (workdir / "package.json").write_text('{"v":"2"}\n')
        (workdir / "node_modules").symlink_to(source)

        refresh = make_env_refresh(
            provisions=[_spec(["sh", "-c", "echo newAPI > node_modules/lib.txt"], ["package.json"])],
            workdir=workdir,
            changed_files=lambda: ["package.json"],
            timeout_s=30,
            max_output_chars=4096,
        )
        assert refresh() is None

        # The worktree dep now has the NEW content...
        assert (workdir / "node_modules").is_dir()
        assert not (workdir / "node_modules").is_symlink()
        assert (workdir / "node_modules" / "lib.txt").read_text() == "newAPI\n"
        # ...and the operator's shared source is UNTOUCHED (the isolation guarantee).
        assert (source / "lib.txt").read_text() == "oldAPI\n"

    def test_copy_dst_is_not_re_materialized(self, tmp_path: Path) -> None:
        workdir = tmp_path / "wt"
        workdir.mkdir()
        (workdir / "package.json").write_text('{"v":"2"}\n')
        # An already-isolated (copy:) dst — a real directory, not a symlink.
        nm = workdir / "node_modules"
        nm.mkdir()
        (nm / "sentinel").write_text("kept\n")

        refresh = make_env_refresh(
            provisions=[_spec(["sh", "-c", "echo newAPI > node_modules/lib.txt"], ["package.json"])],
            workdir=workdir,
            changed_files=lambda: ["package.json"],
            timeout_s=30,
            max_output_chars=4096,
        )
        assert refresh() is None
        # Left a real dir (never replaced) and the install still ran into it.
        assert nm.is_dir() and not nm.is_symlink()
        assert (nm / "sentinel").read_text() == "kept\n"
        assert (nm / "lib.txt").read_text() == "newAPI\n"

    def test_absent_dst_and_source_still_runs_the_install(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"v":"2"}\n')
        # No node_modules at all -> materialization is skipped, the install runs and
        # creates it fresh.
        refresh = make_env_refresh(
            provisions=[_spec(["sh", "-c", "mkdir -p node_modules; echo ok > node_modules/x"], ["package.json"])],
            workdir=tmp_path,
            changed_files=lambda: ["package.json"],
            timeout_s=30,
            max_output_chars=4096,
        )
        assert refresh() is None
        assert (tmp_path / "node_modules" / "x").read_text().strip() == "ok"

    def test_timeout_kills_the_process_group_and_fails(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"v":"2"}\n')
        refresh = make_env_refresh(
            provisions=[_spec(["sh", "-c", "sleep 30"], ["package.json"])],
            workdir=tmp_path,
            changed_files=lambda: ["package.json"],
            timeout_s=1,
            max_output_chars=4096,
        )
        result = refresh()
        assert result is not None
        assert result.name == "env-refresh"
        assert result.passed is False
        assert result.timed_out is True

    def test_emits_started_and_finished_events(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"v":"1"}\n')
        log = tmp_path / "run.jsonl"
        refresh = make_env_refresh(
            provisions=[_spec(["sh", "-c", "true"], ["package.json"])],
            workdir=tmp_path,
            changed_files=lambda: ["package.json"],
            timeout_s=30,
            max_output_chars=4096,
        )
        with bind_run_log(log):
            assert refresh() is None

        events = [json.loads(line)["event"] for line in log.read_text().splitlines()]
        assert "env_refresh_started" in events
        assert "env_refresh_finished" in events
