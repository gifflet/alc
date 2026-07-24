# test_command.py — Direct unit tests for the exec argv whitelist (command.py).
from __future__ import annotations

import sys

import pytest

from alc.ui.command import build_argv
from alc.ui.errors import ApiError


class TestSpike:
    def test_builds_argv_from_task(self) -> None:
        argv = build_argv("spike", {"task": "try a prototype"})
        assert argv == [sys.executable, "-m", "alc", "spike", "try a prototype"]

    def test_accepts_engine_flag(self) -> None:
        argv = build_argv("spike", {"task": "x", "engine": "mock"})
        assert argv == [sys.executable, "-m", "alc", "spike", "x", "--engine", "mock"]

    def test_missing_task_is_rejected(self) -> None:
        with pytest.raises(ApiError) as exc:
            build_argv("spike", {})
        assert exc.value.status == 422

    def test_unknown_flag_is_rejected(self) -> None:
        # 'blueprint' belongs to `run`, not `spike` (a spike has no blueprint to pick).
        with pytest.raises(ApiError) as exc:
            build_argv("spike", {"task": "x", "blueprint": "chore"})
        assert exc.value.status == 422


class TestExplore:
    def test_builds_argv_from_blueprint_and_task(self) -> None:
        argv = build_argv("explore", {"blueprint": "chore", "task": "try a variant"})
        assert argv == [
            sys.executable, "-m", "alc", "explore", "chore", "try a variant",
        ]

    def test_accepts_variants_and_single_item_engine_and_tier_lists(self) -> None:
        argv = build_argv(
            "explore",
            {
                "blueprint": "chore",
                "task": "try a variant",
                "variants": 3,
                "engine": ["mock"],
                "tier": ["standard"],
            },
        )
        assert argv == [
            sys.executable, "-m", "alc", "explore", "chore", "try a variant",
            "--variants", "3", "--engine", "mock", "--tier", "standard",
        ]

    def test_missing_task_is_rejected(self) -> None:
        with pytest.raises(ApiError) as exc:
            build_argv("explore", {"blueprint": "chore"})
        assert exc.value.status == 422

    def test_unknown_flag_is_rejected(self) -> None:
        # `explore` has no `isolate` flag (that belongs to `run`/`flow`).
        with pytest.raises(ApiError) as exc:
            build_argv("explore", {"blueprint": "chore", "task": "x", "isolate": True})
        assert exc.value.status == 422


class TestExploreListFlags:
    """T5/T6.1 — engine/tier are `list_flags`: repeatable, cartesian on the CLI side."""

    def test_multiple_engines_and_tiers_emit_one_flag_per_item_in_order(self) -> None:
        argv = build_argv(
            "explore",
            {
                "blueprint": "chore",
                "task": "try a variant",
                "engine": ["A", "B"],
                "tier": ["X"],
            },
        )
        assert argv == [
            sys.executable, "-m", "alc", "explore", "chore", "try a variant",
            "--engine", "A", "--engine", "B", "--tier", "X",
        ]

    def test_single_item_list_emits_one_flag(self) -> None:
        argv = build_argv(
            "explore",
            {"blueprint": "chore", "task": "x", "engine": ["mock"]},
        )
        assert argv == [
            sys.executable, "-m", "alc", "explore", "chore", "x", "--engine", "mock",
        ]

    def test_absent_list_omits_the_flag(self) -> None:
        argv = build_argv("explore", {"blueprint": "chore", "task": "x"})
        assert "--engine" not in argv
        assert "--tier" not in argv

    def test_empty_list_omits_the_flag(self) -> None:
        argv = build_argv(
            "explore",
            {"blueprint": "chore", "task": "x", "engine": [], "tier": []},
        )
        assert "--engine" not in argv
        assert "--tier" not in argv

    def test_non_list_value_is_rejected(self) -> None:
        with pytest.raises(ApiError) as exc:
            build_argv("explore", {"blueprint": "chore", "task": "x", "engine": "mock"})
        assert exc.value.status == 422

    def test_non_list_value_error_message_names_the_flag(self) -> None:
        with pytest.raises(ApiError) as exc:
            build_argv("explore", {"blueprint": "chore", "task": "x", "tier": "standard"})
        assert "tier" in str(exc.value)
        assert "list" in str(exc.value)


class TestValueFlagsGuard:
    """Guard: the list_flags refactor must not change how single-value flags work
    for every other command (build_argv validates ALL exec dispatch)."""

    def test_run_emits_each_value_flag_exactly_once(self) -> None:
        argv = build_argv(
            "run",
            {"blueprint": "chore", "task": "tidy", "engine": "mock", "tier": "standard", "primer": "p1"},
        )
        assert argv == [
            sys.executable, "-m", "alc", "run", "chore", "tidy",
            "--engine", "mock", "--tier", "standard", "--primer", "p1",
        ]

    def test_flow_emits_each_value_flag_exactly_once(self) -> None:
        argv = build_argv(
            "flow",
            {"flow": "ship", "task": "tidy", "engine": "mock", "tier": "standard"},
        )
        assert argv == [
            sys.executable, "-m", "alc", "flow", "ship", "tidy",
            "--engine", "mock", "--tier", "standard",
        ]

    def test_conduct_emits_each_value_flag_exactly_once(self) -> None:
        argv = build_argv(
            "conduct",
            {"goal": "ship it", "engine": "mock", "tier": "standard", "concurrency": 2},
        )
        assert argv == [
            sys.executable, "-m", "alc", "conduct", "ship it",
            "--engine", "mock", "--tier", "standard", "--concurrency", "2",
        ]

    def test_spike_still_accepts_a_scalar_engine(self) -> None:
        argv = build_argv("spike", {"task": "x", "engine": "mock"})
        assert argv == [sys.executable, "-m", "alc", "spike", "x", "--engine", "mock"]


class TestConductStrictStage:
    def test_accepts_strict_stage_flag(self) -> None:
        argv = build_argv("conduct", {"goal": "ship it", "strict-stage": True})
        assert argv == [sys.executable, "-m", "alc", "conduct", "ship it", "--strict-stage"]

    def test_omits_strict_stage_when_unset(self) -> None:
        argv = build_argv("conduct", {"goal": "ship it"})
        assert "--strict-stage" not in argv

    def test_unknown_flag_is_still_rejected(self) -> None:
        with pytest.raises(ApiError) as exc:
            build_argv("conduct", {"goal": "ship it", "evil": "1"})
        assert exc.value.status == 422
