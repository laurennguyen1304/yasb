<#
.SYNOPSIS
  One-shot setup for this YASB fork on Python 3.12.

  Creates a virtualenv, installs YASB (working around the upstream 3.14-only
  dependency gate), patches the qt-css-engine dependency for 3.12, and deploys
  the bundled config + styles (Claude widgets, calculator/search bar, hotkey).

.USAGE
  From the repository root:
      powershell -ExecutionPolicy Bypass -File .\setup.ps1

  Options:
      -NoConfig     Skip copying config/ to ~/.config/yasb (keep your own).
      -Run          Launch the bar when setup finishes.
#>
param(
    [switch]$NoConfig,
    [switch]$Run
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Find-Python312 {
    # Prefer the py launcher, then a bare python that reports 3.12.
    try { & py -3.12 --version *> $null; if ($LASTEXITCODE -eq 0) { return @('py', '-3.12') } } catch {}
    try {
        $v = & python --version 2>&1
        if ($v -match '3\.12') { return @('python') }
    } catch {}
    throw "Python 3.12 not found. Install it (https://www.python.org/downloads/) and re-run."
}

Write-Host "==> Locating Python 3.12..." -ForegroundColor Cyan
$py = Find-Python312

Write-Host "==> Creating virtualenv (.venv)..." -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $root '.venv'))) {
    & $py[0] $py[1..($py.Count-1)] -m venv .venv
}
$venvPy = Join-Path $root '.venv\Scripts\python.exe'

Write-Host "==> Upgrading pip..." -ForegroundColor Cyan
& $venvPy -m pip install --upgrade pip

Write-Host "==> Installing YASB (with --ignore-requires-python for the 3.14-gated dep)..." -ForegroundColor Cyan
& $venvPy -m pip install -e . --ignore-requires-python

Write-Host "==> Patching qt-css-engine for Python 3.12..." -ForegroundColor Cyan
& $venvPy scripts\patch_py312_deps.py

if (-not $NoConfig) {
    $cfgDir = Join-Path $env:USERPROFILE '.config\yasb'
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
    foreach ($f in @('config.yaml', 'styles.css')) {
        $dest = Join-Path $cfgDir $f
        if (Test-Path $dest) {
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            Copy-Item $dest "$dest.bak-$stamp"
            Write-Host "    backed up existing $f -> $f.bak-$stamp" -ForegroundColor DarkGray
        }
        Copy-Item (Join-Path $root "config\$f") $dest -Force
        Write-Host "    deployed $f -> $cfgDir" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Run the bar with:  .\.venv\Scripts\pythonw.exe src\main.py" -ForegroundColor Green

if ($Run) {
    Write-Host "==> Launching..." -ForegroundColor Cyan
    Start-Process (Join-Path $root '.venv\Scripts\pythonw.exe') -ArgumentList 'src\main.py' -WorkingDirectory $root
}
