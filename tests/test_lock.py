# test_lock.py — Hermetic tests for the tick concurrency lock.
from __future__ import annotations

from pathlib import Path

import pytest

from alc import lock as lock_mod
from alc.lock import tick_lock


def test_acquires_when_free(tmp_path: Path) -> None:
    with tick_lock(tmp_path / ".lock") as acquired:
        assert acquired is True


@pytest.mark.skipif(lock_mod.fcntl is None, reason="advisory locking unavailable")
def test_second_holder_is_blocked(tmp_path: Path) -> None:
    lock = tmp_path / ".lock"
    with tick_lock(lock) as first:
        assert first is True
        # A second acquisition while the first is held must be refused.
        with tick_lock(lock) as second:
            assert second is False
    # Once released, the lock can be acquired again.
    with tick_lock(lock) as third:
        assert third is True
