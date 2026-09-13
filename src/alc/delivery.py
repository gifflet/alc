# delivery.py — The remote last mile after `alc land`'s local merge.
#
# `alc land` (merge.py) already integrates alc/* branches into the current branch
# entirely LOCALLY — that IS the work landing successfully. `DeliverySpec` (models.py)
# adds ONE optional step on top: hand the already-landed branch to the remote, either
# as a bare push or as a pull request opened via the `gh` CLI, for a human to review —
# the review gate the product deliberately preserves. Every function here mirrors
# commit.py's contract: a push failure or a missing `gh` binary NEVER raises, because
# the local landing already succeeded and the remote step is the last mile, not the work.
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from alc.merge import MergeReport


def has_gh() -> bool:
    """Return True when the `gh` CLI is on PATH."""
    return shutil.which("gh") is not None


def load_delivery_env(repo_root: Path, env_file: str | None) -> dict[str, str] | None:
    """The environment for the delivery commands: os.environ merged with the
    dotenv at *env_file* (relative to *repo_root*), so a `GH_TOKEN` /
    `AZURE_DEVOPS_EXT_PAT` written there reaches `git`/`gh`/`az`. None when no
    env_file is set (the commands then inherit os.environ untouched, unchanged
    from before). A missing/unreadable dotenv contributes nothing — never
    raises, mirroring the never-raise contract of the whole module."""
    if not env_file:
        return None
    from alc.runtime import parse_dotenv

    merged = dict(os.environ)
    try:
        merged.update(parse_dotenv((repo_root / env_file).read_text(encoding="utf-8")))
    except OSError:
        pass
    return merged


def has_az() -> bool:
    """Return True when the `az` CLI is on PATH (Azure DevOps needs its
    `azure-devops` extension too, but its absence surfaces as a normal CLI
    failure — never-raise, like a missing `gh`)."""
    return shutil.which("az") is not None


def detect_provider(repo_root: Path, remote: str) -> str:
    """Classify the forge from *remote*'s URL: 'azure' for dev.azure.com /
    visualstudio.com, else 'github'. Never raises — an unreadable remote falls
    back to 'github', the historical default."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", remote],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return "github"
    url = result.stdout.strip().lower() if result.returncode == 0 else ""
    if "dev.azure.com" in url or "visualstudio.com" in url:
        return "azure"
    return "github"


def current_branch(repo_root: Path) -> str | None:
    """Return the currently checked out branch name, or None on any failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return name or None


def push_branch(
    repo_root: Path, remote: str, branch: str, env: dict[str, str] | None = None
) -> tuple[bool, str]:
    """Push *branch* to *remote*.

    Never raises: a missing ``git`` binary, an unconfigured remote, or an auth
    failure is reported back as ``(False, <reason>)``, exactly like
    ``commit.py``'s helpers — a delivery failure must never take down a local
    land that already succeeded.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "push", remote, branch],
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        return False, "git not found; skipping push."
    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip()
        return False, f"git push {remote} {branch} failed: {reason}"
    return True, f"pushed {branch} to {remote}"


def changed_files(repo_root: Path, base: str, head: str) -> list[str]:
    """Return paths that differ between *base* and *head*.

    ``[]`` on any git failure (missing git, unknown ref) — a diff that cannot
    be computed must only shorten a PR body, never abort it.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--name-only", f"{base}...{head}"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def landed_commits(repo_root: Path, base: str, head: str) -> list[tuple[str, str]]:
    """The (subject, body) of every commit in ``base..head`` — the work that
    just landed, newest first. ``[]`` on any git failure, so a PR title/body
    degrades gracefully rather than aborting. Used to describe WHAT was done,
    instead of a bare branch name."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "log", "--format=%s%x1f%b%x1e", f"{base}..{head}"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    commits: list[tuple[str, str]] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        subject, _, body = record.partition("\x1f")
        commits.append((subject.strip(), body.strip()))
    return commits


def _title_from_subject(subject: str) -> str:
    """A descriptive, capitalized PR title from a commit subject. Strips a
    Conventional Commits ``type(scope):`` prefix so the title reads as a
    sentence, and uppercases the first letter."""
    import re

    m = re.match(r"^[a-z]+(\([^)]*\))?!?:\s*(?P<desc>.+)$", subject)
    text = m.group("desc") if m else subject
    text = text.strip()
    return text[:1].upper() + text[1:] if text else "Landed changes"


def pr_title(repo_root: Path, base: str, head: str, report: MergeReport) -> str:
    """A descriptive, capitalized title for the land's PR. One landed commit ->
    its subject as a sentence; several -> the first plus a count; none readable
    -> a clear fallback naming how many branches merged."""
    commits = landed_commits(repo_root, base, head)
    if len(commits) == 1:
        return _title_from_subject(commits[0][0])
    if len(commits) > 1:
        return f"{_title_from_subject(commits[0][0])} (+{len(commits) - 1} more)"
    n = len(report.merged)
    return f"Land {n} branch{'es' if n != 1 else ''}"


def build_pr_body(report: MergeReport, files: list[str], commits: list[tuple[str, str]] | None = None) -> str:
    """Compose a PR body from *report* (the land's own MergeReport) and *files*.

    "The report" a PR body is built from is `alc land`'s
    OWN MergeReport — the only report the command actually holds. No archived
    per-branch RunReport/FlowReport is attributable back to a specific `alc/*`
    branch anywhere in the control plane today (a `TickResult.branch` is never
    persisted alongside the report it produced), so inventing that correlation
    here would be a guess dressed as data. The three sections below still answer
    exactly what the roadmap asks for: which branches landed clean ("checks"),
    a merged/left tally ("scorecard"), and the files the landed change touches.
    """
    # What was done, first — the landed commits' own words. The mechanical
    # detail (checks / scorecard / changed files) follows, so a reviewer reads
    # the intent before the accounting.
    lines: list[str] = []
    if commits:
        lines += ["## What changed", ""]
        for subject, body in commits:
            lines.append(f"- {subject}")
            if body:
                lines += [f"  {line}" for line in body.splitlines() if line.strip()]
        lines.append("")

    lines += ["## Checks", ""]
    if report.merged:
        lines.append(f"{len(report.merged)} branch(es) merged cleanly:")
        lines += [f"- {b}" for b in report.merged]
    else:
        lines.append("No branches merged cleanly.")
    if report.conflicted:
        lines += ["", f"{len(report.conflicted)} branch(es) left for manual resolution:"]
        lines += [f"- {b}" for b in report.conflicted]

    lines += [
        "",
        "## Scorecard",
        "",
        f"- Merged: {len(report.merged)}",
        f"- Left: {len(report.conflicted)}",
        "",
        "## Changed files",
        "",
    ]
    lines += [f"- {f}" for f in files] if files else ["(none detected)"]
    return "\n".join(lines)


def _open_pr_github(
    repo_root: Path, base: str, head: str, title: str, body: str, env: dict[str, str] | None = None
) -> tuple[bool, str]:
    """Open a PR for *head* against *base* via ``gh pr create``.

    Never raises: a missing ``gh`` binary or any CLI failure is reported back
    as ``(False, <reason>)``, same never-raise contract as `push_branch`.
    """
    if not has_gh():
        return False, "gh not installed; skipping PR."
    try:
        result = subprocess.run(
            [
                "gh", "pr", "create",
                "--base", base,
                "--head", head,
                "--title", title,
                "--body", body,
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=env,
        )
    except FileNotFoundError:
        return False, "gh not installed; skipping PR."
    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip()
        return False, f"gh pr create failed: {reason}"
    return True, result.stdout.strip() or "PR opened."


def _open_pr_azure(
    repo_root: Path, base: str, head: str, title: str, body: str, env: dict[str, str] | None = None
) -> tuple[bool, str]:
    """Open a PR for *head* against *base* via ``az repos pr create``.

    The `az` CLI infers organization/project/repository from the git remote when
    run inside the repo (with the ``azure-devops`` extension). Never raises: a
    missing `az`/extension or any CLI failure is reported as ``(False, reason)``,
    the same contract as the GitHub path.
    """
    if not has_az():
        return False, "az not installed; skipping PR."
    try:
        result = subprocess.run(
            [
                "az", "repos", "pr", "create",
                "--source-branch", head,
                "--target-branch", base,
                "--title", title,
                "--description", body,
                "--output", "tsv",
                "--query", "repository.webUrl",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=env,
        )
    except FileNotFoundError:
        return False, "az not installed; skipping PR."
    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip()
        return False, f"az repos pr create failed: {reason}"
    return True, result.stdout.strip() or "PR opened."


def open_pr(
    repo_root: Path,
    base: str,
    head: str,
    title: str,
    body: str,
    *,
    provider: str = "auto",
    remote: str = "origin",
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Open a PR against the right forge. *provider* is "github", "azure", or
    "auto" (detect from *remote*'s URL). *env* (when given) is the environment
    the forge CLI runs with — carrying its token. Never raises — dispatches to
    the provider-specific opener, each of which reports failure as ``(False, …)``."""
    resolved = detect_provider(repo_root, remote) if provider == "auto" else provider
    if resolved == "azure":
        return _open_pr_azure(repo_root, base, head, title, body, env)
    return _open_pr_github(repo_root, base, head, title, body, env)
