"""clone.py — Validate a clone request and build the git argv for it.

The alc codebase talks to git by running the binary — worktree.py, commit.py,
branches.py and five other modules do it in about fifty places. Cloning follows
that, which also means it inherits the SSH agent and credential helpers the
operator already has configured. A library would have to reimplement or work
around those.

The whole security surface of this feature is here. A clone URL arrives from the
network and becomes an argument to a subprocess, and git has options that run
commands:

    git clone --upload-pack='touch /tmp/pwned' …
    git clone --config=core.sshCommand='…' …
    git clone ext::sh -c '…' …

So the URL is not sanitised — it is *matched against what a repository URL looks
like*, and anything else is refused. A deny-list of dangerous flags would be a
race against git's option surface; an allow-list of schemes is not.
"""

from __future__ import annotations

import re
from pathlib import Path

from alc.ui.errors import ApiError

# Schemes that are a fetch, and nothing else. `ext::` and `file::` are absent on
# purpose: ext:: runs an arbitrary command by design, and file:: adds nothing a
# plain path does not already do.
_HTTP = re.compile(r"^https?://[A-Za-z0-9._~%-]+(:[0-9]+)?/[A-Za-z0-9._~%/+-]+$")
_SSH_URL = re.compile(r"^ssh://[A-Za-z0-9._~%-]+@[A-Za-z0-9._~%-]+(:[0-9]+)?/[A-Za-z0-9._~%/+-]+$")
_SCP_LIKE = re.compile(r"^[A-Za-z0-9._~%-]+@[A-Za-z0-9._~%-]+:[A-Za-z0-9._~%/+-]+$")


def validate_url(raw: str) -> str:
    """Return the URL if it is one we are willing to hand to git.

    Raises ApiError with a reason the UI can show, rather than a generic refusal
    the operator cannot act on.
    """
    url = raw.strip()
    if not url:
        raise ApiError("clone URL is empty", status=400)
    # A leading dash makes git read the URL as an option, which is how
    # --upload-pack gets in. Checked before the patterns so the message is exact.
    if url.startswith("-"):
        raise ApiError("clone URL may not start with '-'", status=400)
    if any(c.isspace() for c in url):
        raise ApiError("clone URL may not contain whitespace", status=400)
    if not (_HTTP.match(url) or _SSH_URL.match(url) or _SCP_LIKE.match(url)):
        raise ApiError(
            "clone URL must be https://…, ssh://…, or user@host:path — "
            "other forms (including ext:: and file::) are refused",
            status=400,
        )
    return url


def repo_name(url: str) -> str:
    """The directory name git would create for this URL."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    if ":" in tail and "/" not in tail:  # scp-like user@host:name.git
        tail = tail.rsplit(":", 1)[-1]
    return tail[:-4] if tail.endswith(".git") else tail


def resolve_destination(parent_raw: str, url: str, name: str | None) -> Path:
    """Where the clone will land, refusing anything already occupied."""
    parent = Path(parent_raw).expanduser()
    try:
        parent = parent.resolve()
    except OSError as exc:
        raise ApiError(f"cannot resolve '{parent_raw}': {exc}", status=400) from exc
    if not parent.is_dir():
        raise ApiError(f"'{parent}' is not a directory", status=400)

    folder = (name or repo_name(url)).strip()
    if not folder or folder in (".", "..") or "/" in folder or "\\" in folder:
        raise ApiError(f"'{folder}' is not a usable directory name", status=400)

    destination = parent / folder
    # git would refuse a non-empty target anyway; saying so here means the
    # operator learns it before watching a clone start and fail.
    if destination.exists() and any(destination.iterdir()):
        raise ApiError(f"'{destination}' already exists and is not empty", status=400)
    return destination


def build_argv(url: str, destination: Path) -> list[str]:
    """The git command line for this clone.

    `--` separates options from operands, so even a URL that slipped past
    validation cannot be read as a flag.
    """
    return ["git", "clone", "--progress", "--", url, str(destination)]


def resolve_new_project(parent_raw: str, name: str) -> Path:
    """Where a brand-new project will be created.

    Unlike a clone, the directory may not exist yet — that is the normal case.
    What must not happen is landing on top of something already there.
    """
    parent = Path(parent_raw).expanduser()
    try:
        parent = parent.resolve()
    except OSError as exc:
        raise ApiError(f"cannot resolve '{parent_raw}': {exc}", status=400) from exc
    if not parent.is_dir():
        raise ApiError(f"'{parent}' is not a directory", status=400)

    folder = name.strip()
    if not folder or folder in (".", "..") or "/" in folder or "\\" in folder:
        raise ApiError(f"'{folder}' is not a usable directory name", status=400)

    destination = parent / folder
    if destination.exists() and any(destination.iterdir()):
        raise ApiError(f"'{destination}' already exists and is not empty", status=400)
    return destination
