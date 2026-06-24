# Live smoke test for the Claude Code engine adapter.
#
# This test calls the REAL model and costs a small amount of tokens, so it is
# opt-in. It runs only when BOTH are true:
#   - ALC_LIVE_TESTS=1 is set in the environment, and
#   - the `claude` CLI is installed and authenticated (health_check passes).
# Otherwise it is skipped, keeping the default suite hermetic and free.
from __future__ import annotations

import os
from pathlib import Path

import pytest

from alc.engine import EngineRequest
from alc.engines.claude_code import ClaudeCodeEngine

_LIVE = os.environ.get("ALC_LIVE_TESTS") == "1"
_engine = ClaudeCodeEngine()

pytestmark = pytest.mark.skipif(
    not (_LIVE and _engine.health_check()),
    reason="set ALC_LIVE_TESTS=1 and install the `claude` CLI to run live smoke tests",
)


def test_claude_code_performs_a_headless_edit(tmp_path: Path) -> None:
    """One headless turn must actually edit the filesystem in request.workdir.

    This is the contract's minimum bar ("accept a directive headlessly and edit
    files") exercised against the real engine.
    """
    request = EngineRequest(
        directive=(
            "Create a file named hello.txt in the current directory whose entire "
            "contents are exactly the lowercase word: hi"
        ),
        workdir=tmp_path,
        model="haiku",  # cheap/fast model keeps the smoke test inexpensive
        timeout_s=180,
    )

    result = _engine.run(request)

    assert result.ok, f"engine reported failure: {result.output_text}"

    target = tmp_path / "hello.txt"
    assert target.exists(), f"expected {target} to be created; output: {result.output_text}"
    assert "hi" in target.read_text().lower()
