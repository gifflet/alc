# ALC installer - Windows.
#
#   irm https://alc-runtime.vercel.app/install.ps1 | iex
#
# Installing and updating are the same command: `uv tool install --upgrade` is
# idempotent, so re-running moves you to the latest release.
#
# What it does, in order:
#   1. Installs uv if it is missing (ALC ships on PyPI; uv is what puts a Python
#      CLI on PATH without a virtualenv to manage).
#   2. Installs or upgrades alc-runtime[ui].
#   3. Puts uv's tool bin directory on your user PATH, which is the step people
#      hit and the reason this script exists.

$ErrorActionPreference = 'Stop'

function Write-Step { param($Text) Write-Host "==> " -ForegroundColor Cyan -NoNewline; Write-Host $Text }
function Write-Note { param($Text) Write-Host "    $Text" -ForegroundColor DarkGray }
function Write-Warn { param($Text) Write-Host "warning: " -ForegroundColor Yellow -NoNewline; Write-Host $Text }
function Write-Fail { param($Text) Write-Host "error: " -ForegroundColor Red -NoNewline; Write-Host $Text; exit 1 }

# The `ui` extra pulls fastapi/uvicorn/watchfiles. Opt out with $env:ALC_NO_UI=1.
$package = if ($env:ALC_NO_UI -eq '1') { 'alc-runtime' } else { 'alc-runtime[ui]' }

# ---------------------------------------------------------------------------
# 1. uv
# ---------------------------------------------------------------------------
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Step "uv is already installed ($(uv --version))"
} else {
    Write-Step 'Installing uv'
    try {
        # iex on a downloaded string is exactly what Astral documents, and this
        # script was itself delivered the same way. Writing it to a temp file
        # first would look safer and change nothing.
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Fail "the uv installer failed: $_"
    }
    # uv's installer edits the user PATH, which the CURRENT process does not see.
    # Pull it in so the rest of this script can call uv.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Fail 'uv installed but is not on PATH. Open a new terminal and re-run this command.'
    }
}

# ---------------------------------------------------------------------------
# 2. alc
# ---------------------------------------------------------------------------
Write-Step "Installing $package"
uv tool install --upgrade $package
if ($LASTEXITCODE -ne 0) { Write-Fail 'uv tool install failed.' }

# Ask uv where it put the executable rather than guessing: it is not necessarily
# beside uv itself.
$toolBin = (uv tool dir --bin 2>$null | Select-Object -First 1)
if (-not $toolBin) { $toolBin = Join-Path $env:USERPROFILE '.local\bin' }
$toolBin = $toolBin.Trim()

# ---------------------------------------------------------------------------
# 3. PATH - the step this installer exists for
# ---------------------------------------------------------------------------
# The USER PATH, not the process one: only that survives into the next terminal.
# Read it raw so an existing %VAR% is not expanded and then written back flat.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($null -eq $userPath) { $userPath = '' }

$already = $userPath -split ';' | Where-Object { $_.TrimEnd('\') -ieq $toolBin.TrimEnd('\') }
$pathNote = $null

if ($already) {
    Write-Note "$toolBin is already on your user PATH"
} else {
    try {
        $updated = if ($userPath.Length -gt 0) { "$userPath;$toolBin" } else { $toolBin }
        [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
        Write-Host "    added " -ForegroundColor Green -NoNewline
        Write-Host "$toolBin to your user PATH"
        $pathNote = 'open a new terminal for it to take effect'
    } catch {
        Write-Warn "could not write your user PATH. Add this directory yourself: $toolBin"
    }
}

# Current session, so the verification below works and so does the next command
# the user types in THIS window.
if (($env:Path -split ';') -notcontains $toolBin) {
    $env:Path = "$toolBin;$env:Path"
}

# ---------------------------------------------------------------------------
# Prove it
# ---------------------------------------------------------------------------
$alc = Join-Path $toolBin 'alc.exe'
if (-not (Test-Path $alc)) { $alc = Join-Path $toolBin 'alc' }
$version = & $alc --version 2>$null
if (-not $version) { Write-Fail "alc was installed to $toolBin but would not run." }

Write-Host ''
Write-Host $version -ForegroundColor Green -NoNewline
Write-Host ' is installed.'
if ($pathNote) { Write-Host "To use it, $pathNote." }
Write-Host ''
Write-Host 'Next: ' -NoNewline; Write-Host 'alc init' -ForegroundColor White -NoNewline
Write-Host '   (sets up .alc\ in a project)' -ForegroundColor DarkGray
Write-Host 'Docs: ' -NoNewline; Write-Host 'https://alc-runtime.vercel.app/docs' -ForegroundColor DarkGray
