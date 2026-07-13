# test_part_d.py — Residual-gap knobs and review nits (Part D).
#
# Each config-field knob (K, L, O) proves "unset == identical to before"; the
# review nits (slug transliteration, recursive-include lint scan, finalize_plan
# usage accounting) are covered here too. Fully hermetic: no real model, and git
# tests use a local repo in tmp_path.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.bundle import summarize_bundle, write_bundle
from alc.conduct import _slugify, finalize_plan
from alc.engine import Capabilities, EngineResult, Usage
from alc.intake import load_manifest
from alc.models import Check, Manifest, RunReport, Scorecard
from alc.policy import validate_prompts
from alc.verifier import Verifier
from alc.worktree import IsolatedWorktree

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


# ---------------------------------------------------------------------------
# Knob K — check-output cap fed into repair context
# ---------------------------------------------------------------------------


class TestCheckOutputChars:
    def test_cap_truncates_captured_output(self, tmp_path: Path) -> None:
        # A check that prints > 10 chars is truncated to exactly max_output_chars.
        check = Check(name="loud", shell="printf '0123456789ABCDEF'")
        results = Verifier(max_output_chars=10).run([check], tmp_path)
        assert results[0].passed is True
        assert results[0].output == "0123456789"

    def test_default_cap_keeps_full_short_output(self, tmp_path: Path) -> None:
        # Unset -> former 4096 cap, so a short output is untouched.
        check = Check(name="quiet", shell="printf 'hello'")
        results = Verifier().run([check], tmp_path)
        assert results[0].output == "hello"

    def test_default_manifest_value_is_4096(self) -> None:
        assert _MINIMAL_MANIFEST.check_output_chars == 4096


# ---------------------------------------------------------------------------
# Knob L — bundle replay output cap
# ---------------------------------------------------------------------------


def _write_run_bundle(bundles_dir: Path, output_text: str) -> Path:
    """Write a one-attempt RunReport bundle carrying output_text and return its path."""
    report = RunReport(
        blueprint="chore",
        engine="mock",
        success=True,
        attempts=[],
        scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
        output_text=output_text,
    )
    return write_bundle(bundles_dir, label="chore", task="t", report=report)


class TestBundleOutputChars:
    def test_cap_truncates_replay_output(self, tmp_path: Path) -> None:
        path = _write_run_bundle(tmp_path, "0123456789ABCDEF")
        summary = summarize_bundle(path, max_output_chars=5)
        assert "01234… [truncated]" in summary
        assert "56789" not in summary

    def test_default_cap_keeps_short_output(self, tmp_path: Path) -> None:
        # Unset -> former 1500 cap, so a short output is untouched.
        path = _write_run_bundle(tmp_path, "short output")
        summary = summarize_bundle(path)
        assert "short output" in summary
        assert "truncated" not in summary

    def test_default_manifest_value_is_1500(self) -> None:
        assert _MINIMAL_MANIFEST.bundle_output_chars == 1500


# ---------------------------------------------------------------------------
# Knob O — isolated-worktree exit-commit message
# ---------------------------------------------------------------------------


def _make_git_repo(base: Path) -> Path:
    """Initialize a git repo with one commit inside *base* and return its path."""
    repo = base / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@alc.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "ALC Test"],
        check=True,
        capture_output=True,
    )
    (repo / "seed.txt").write_text("initial content\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)
    return repo


def _last_commit_subject(repo: Path, branch: str) -> str:
    """Return the subject line of the tip commit on *branch*."""
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%s", branch],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _cleanup_branch(repo: Path, branch: str) -> None:
    subprocess.run(["git", "-C", str(repo), "branch", "-D", branch], capture_output=True)


class TestWorktreeCommitMessage:
    def test_custom_template_used_for_exit_commit(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        wt = IsolatedWorktree(repo, "test", commit_message="wip: {branch}")
        with wt as path:
            (path / "agent.txt").write_text("edit\n")
        assert wt.committed is True
        assert _last_commit_subject(repo, wt.branch) == f"wip: {wt.branch}"
        _cleanup_branch(repo, wt.branch)

    def test_unknown_placeholder_used_verbatim(self, tmp_path: Path) -> None:
        # With the str.replace fix, an unknown placeholder like {nope} is not a
        # format error — it is passed verbatim to git commit.  This is intentional:
        # the fix removes the try/except so task text containing literal braces
        # (e.g. JSON) never crashes the exit-commit and never falls back silently.
        repo = _make_git_repo(tmp_path)
        wt = IsolatedWorktree(repo, "test", commit_message="{nope}")
        with wt as path:
            (path / "agent.txt").write_text("edit\n")
        assert wt.committed is True
        assert _last_commit_subject(repo, wt.branch) == "{nope}"
        _cleanup_branch(repo, wt.branch)

    def test_default_message_unchanged(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        wt = IsolatedWorktree(repo, "test")  # commit_message defaulted
        with wt as path:
            (path / "agent.txt").write_text("edit\n")
        assert _last_commit_subject(repo, wt.branch) == f"alc: {wt.branch}"
        _cleanup_branch(repo, wt.branch)

    def test_default_manifest_template(self) -> None:
        assert _MINIMAL_MANIFEST.worktree_commit_message == "alc: {branch}"


# ---------------------------------------------------------------------------
# Review nit — slug transliteration
# ---------------------------------------------------------------------------


class TestSlugifyTransliteration:
    def test_portuguese_accents_are_transliterated(self) -> None:
        assert _slugify("semânticas de candidatura") == "semanticas-de-candidatura"

    def test_single_accented_word(self) -> None:
        assert _slugify("interações") == "interacoes"

    def test_plain_ascii_unchanged(self) -> None:
        assert _slugify("Ship the Feature") == "ship-the-feature"


# ---------------------------------------------------------------------------
# Review nit — lint scans prompt files for {{prompt:X}} refs
# ---------------------------------------------------------------------------


class TestLintScansPromptIncludes:
    def test_dangling_include_in_prompt_file_flagged(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        prompts_dir = operator_layer / "prompts"
        prompts_dir.mkdir(exist_ok=True)
        (prompts_dir / "my-free.md").write_text("body {{prompt:missing}} tail")
        violations = validate_prompts(manifest, operator_layer, blueprints=[])
        assert any(
            v.rule == "prompt-include-resolves" and "missing" in v.message
            for v in violations
        )

    def test_resolvable_include_in_prompt_file_ok(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        prompts_dir = operator_layer / "prompts"
        prompts_dir.mkdir(exist_ok=True)
        (prompts_dir / "target.md").write_text("TARGET")
        (prompts_dir / "src.md").write_text("uses {{prompt:target}}")
        violations = validate_prompts(manifest, operator_layer, blueprints=[])
        assert not any(v.rule == "prompt-include-resolves" for v in violations)


# ---------------------------------------------------------------------------
# Accounting — finalize_plan usage_sink
# ---------------------------------------------------------------------------


class _CorrectiveOnceEngine:
    """First corrective turn still fails to parse; the second heals — so two turns
    run and the usage sink accumulates across BOTH (proves per-turn counting)."""

    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request) -> EngineResult:
        self.calls += 1
        output = (
            '[{"kind":"flow","name":"ship","task":"x"}]'
            if self.calls >= 2
            else "still bad"
        )
        return EngineResult(
            ok=True,
            output_text=output,
            usage=Usage(input_tokens=10, output_tokens=20, cost_usd=0.5),
        )


class TestFinalizePlanUsageSink:
    def test_corrective_turns_are_counted(self) -> None:
        # Invalid first output -> 1st corrective still bad, 2nd heals -> TWO turns
        # counted (proves the sink accumulates per corrective turn, not just once).
        engine = _CorrectiveOnceEngine()
        sink: dict = {}
        plan = finalize_plan(
            engine=engine,  # type: ignore[arg-type]
            model=None,
            first_output="not json",
            available_flows={"ship"},
            available_specialists=set(),
            usage_sink=sink,
        )
        assert plan.items[0].name == "ship"
        assert engine.calls == 2
        assert sink["engine_calls"] == 2
        assert sink["usd"] == 1.0    # 0.5 per turn * 2
        assert sink["tokens"] == 60  # 30 per turn * 2

    def test_valid_first_output_counts_zero(self) -> None:
        sink: dict = {}
        finalize_plan(
            engine=None,  # type: ignore[arg-type]  # never called on valid output
            model=None,
            first_output='[{"kind":"flow","name":"ship","task":"x"}]',
            available_flows={"ship"},
            available_specialists=set(),
            usage_sink=sink,
        )
        assert sink.get("engine_calls", 0) == 0
