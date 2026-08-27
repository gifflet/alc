#!/bin/sh
# ALC installer — macOS and Linux.
#
#   curl -fsSL https://alc-runtime.vercel.app/install.sh | sh
#
# Installing and updating are the same command: uv tool install --upgrade is
# idempotent, so re-running moves you to the latest release.
#
# What it does, in order:
#   1. Installs uv if it is missing (ALC is distributed on PyPI and uv is what
#      puts a Python CLI on your PATH without a virtualenv to manage).
#   2. Installs or upgrades alc-runtime[ui].
#   3. Puts uv's bin directory on your PATH, which is the step people hit.
#
# POSIX sh on purpose: this runs before we know anything about the machine, and
# /bin/sh is the one interpreter that is always there.
set -eu

RESET=''; BOLD=''; DIM=''; RED=''; GREEN=''; YELLOW=''
if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
    RESET='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'
    RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'
fi

say()  { printf '%b\n' "$1"; }
step() { printf '%b\n' "${BOLD}==>${RESET} $1"; }
warn() { printf '%b\n' "${YELLOW}warning:${RESET} $1" >&2; }
die()  { printf '%b\n' "${RED}error:${RESET} $1" >&2; exit 1; }

# The `ui` extra pulls fastapi/uvicorn/watchfiles. Opt out with ALC_NO_UI=1.
PACKAGE='alc-runtime[ui]'
[ "${ALC_NO_UI:-}" = "1" ] && PACKAGE='alc-runtime'

case "$(uname -s)" in
    Darwin|Linux) ;;
    *) die "this installer is for macOS and Linux.
  On Windows, run this in PowerShell instead:
    irm https://alc-runtime.vercel.app/install.ps1 | iex" ;;
esac

# ---------------------------------------------------------------------------
# 1. uv
# ---------------------------------------------------------------------------
UV_BIN="${XDG_BIN_HOME:-$HOME/.local/bin}"

if command -v uv >/dev/null 2>&1; then
    step "uv is already installed ${DIM}($(uv --version 2>/dev/null || echo 'version unknown'))${RESET}"
    # Respect where uv actually lives rather than assuming ~/.local/bin: a uv
    # from Homebrew or a distro package is somewhere else entirely.
    UV_BIN="$(dirname "$(command -v uv)")"
else
    step 'Installing uv'
    command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 \
        || die 'neither curl nor wget is available — install one and re-run.'
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || die 'the uv installer failed.'
    else
        wget -qO- https://astral.sh/uv/install.sh | sh || die 'the uv installer failed.'
    fi
    # uv is on PATH for the rest of THIS script; the shell rc edit below is what
    # makes it survive into the next one.
    PATH="$UV_BIN:$PATH"
    export PATH
    command -v uv >/dev/null 2>&1 || die "uv installed but is not on PATH at $UV_BIN."
fi

# ---------------------------------------------------------------------------
# 2. alc
# ---------------------------------------------------------------------------
step "Installing ${BOLD}$PACKAGE${RESET}"
uv tool install --upgrade "$PACKAGE" || die 'uv tool install failed.'

# uv tool puts binaries in its own bin dir, which is not necessarily the dir uv
# itself lives in — ask uv rather than guess.
TOOL_BIN="$(uv tool dir --bin 2>/dev/null || echo "${XDG_BIN_HOME:-$HOME/.local/bin}")"

# ---------------------------------------------------------------------------
# 3. PATH — the step this installer exists for
# ---------------------------------------------------------------------------
on_path() {
    case ":$PATH:" in *":$1:"*) return 0 ;; *) return 1 ;; esac
}

rc_file() {
    # The rc file for the user's LOGIN shell, not for the sh running this script.
    shell_name="$(basename "${SHELL:-/bin/sh}")"
    case "$shell_name" in
        zsh)  printf '%s\n' "${ZDOTDIR:-$HOME}/.zshrc" ;;
        bash) if [ "$(uname -s)" = 'Darwin' ] && [ -f "$HOME/.bash_profile" ]
              then printf '%s\n' "$HOME/.bash_profile"
              else printf '%s\n' "$HOME/.bashrc"
              fi ;;
        fish) printf '%s\n' "$HOME/.config/fish/config.fish" ;;
        *)    printf '%s\n' "$HOME/.profile" ;;
    esac
}

add_to_path() {
    target="$1"
    rc="$(rc_file)"
    line="export PATH=\"$target:\$PATH\""
    [ "$(basename "${SHELL:-/bin/sh}")" = 'fish' ] && line="fish_add_path $target"

    # Already written by a previous run (or by uv's own installer): adding it a
    # second time would grow PATH on every shell start.
    if [ -f "$rc" ] && grep -Fq "$target" "$rc" 2>/dev/null; then
        say "  ${DIM}$rc already references $target${RESET}"
        return 0
    fi
    mkdir -p "$(dirname "$rc")" 2>/dev/null || true
    {
        printf '\n# Added by the ALC installer\n'
        printf '%s\n' "$line"
    } >> "$rc" 2>/dev/null || {
        warn "could not write to $rc. Add this line yourself:
    $line"
        return 1
    }
    say "  ${GREEN}added${RESET} $target to PATH in $rc"
}

PATH_NOTE=''
if on_path "$TOOL_BIN"; then
    say "  ${DIM}$TOOL_BIN is already on PATH${RESET}"
else
    add_to_path "$TOOL_BIN" && PATH_NOTE="restart your shell, or run: ${BOLD}export PATH=\"$TOOL_BIN:\$PATH\"${RESET}"
fi
PATH="$TOOL_BIN:$PATH"
export PATH

# ---------------------------------------------------------------------------
# Prove it
# ---------------------------------------------------------------------------
VERSION="$("$TOOL_BIN/alc" --version 2>/dev/null || true)"
[ -n "$VERSION" ] || die "alc was installed to $TOOL_BIN but would not run."

say ''
say "${GREEN}${BOLD}$VERSION${RESET} is installed."
[ -n "$PATH_NOTE" ] && say "To use it in this terminal, $PATH_NOTE"
say ''
say "Next: ${BOLD}alc init${RESET}   ${DIM}(sets up .alc/ in a project)${RESET}"
say "Docs: ${DIM}https://alc-runtime.vercel.app/docs${RESET}"
