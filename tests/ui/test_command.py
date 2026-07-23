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
