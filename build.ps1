<#
.SYNOPSIS
  Publishes the tray app to a single-file exe under .\dist.
#>
[CmdletBinding()]
param(
  [string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$proj = Join-Path $root 'src\ClaudeStatusBar.csproj'
$dist = Join-Path $root 'dist'

# Make sure a freshly-installed SDK is on PATH for this process.
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
            [System.Environment]::GetEnvironmentVariable('Path','User')

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
  throw "dotnet SDK not found. Install with: winget install --id Microsoft.DotNet.SDK.8 -e"
}

Write-Host "Publishing single-file exe..." -ForegroundColor Cyan
& dotnet publish $proj -c $Configuration -r win-x64 --self-contained false `
  /p:PublishSingleFile=true /p:DebugType=none -o $dist
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed ($LASTEXITCODE)" }

$exe = Join-Path $dist 'ClaudeStatusBar.exe'
if (Test-Path $exe) {
  Write-Host "Built: $exe" -ForegroundColor Green
} else {
  throw "Expected exe not found at $exe"
}
