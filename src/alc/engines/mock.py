# mock.py — MockEngine: a deterministic no-op engine for tests and demos.
# Exercises the full control plane (Policy Gate, Assurance Loop, Scorecard) without
# any real model call, making it free and hermetic.
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from alc.engine import Capabilities, EngineRequest, EngineResult


class MockEngine:
    """Execution-plane adapter that never calls a real model.

    When constructed with no behaviors (the registry / manifest path) it is a
    deterministic no-op that always reports ok=True.

    When constructed with a behaviors list (the test path) each call to run()
    invokes behaviors[min(call_index, len-1)](workdir) before returning, allowing
    tests to script per-attempt side-effects (e.g. create a file on the second call).
    """

    name: str = "mock"

    def __init__(
        self,
        behaviors: list[Callable[[Path], None]] | None = None,
    ) -> None:
        self._behaviors = behaviors
        self._call_index = 0

    def capabilities(self) -> Capabilities:
        """Mock declares no native capabilities — all gaps are emulated by the control plane."""
        return Capabilities()

    def health_check(self) -> bool:
        """Mock is always healthy."""
        return True

    def run(self, request: EngineRequest) -> EngineResult:
        """Apply the current behavior (if any) then return ok=True."""
        if self._behaviors is not None:
            idx = min(self._call_index, len(self._behaviors) - 1)
            self._behaviors[idx](request.workdir)
        self._call_index += 1
        return EngineResult(ok=True, output_text="[mock] applied directive")
