<#
.SYNOPSIS
  Installs Claude Status Bar (Windows): builds the exe if needed, copies it and
  the hooks into ~/.claude/claude-status-bar, and merges the lifecycle hooks
  into ~/.claude/settings.json (with a timestamped backup).

.PARAMETER Uninstall
  Removes the installed files and strips the hooks from settings.json.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$root        = Split-Path -Parent $MyInvocation.MyCommand.Path
$claudeDir   = Join-Path $env:USERPROFILE '.claude'
$installDir  = Join-Path $claudeDir 'claude-status-bar'
$settingsFile = Join-Path $claudeDir 'settings.json'
$lifecycle   = Join-Path $installDir 'hooks\lifecycle.js'

# Event name -> (lifecycle arg, matcher). Matcher $null means no matcher.
$eventMap = [ordered]@{
  'SessionStart'     = @('start',  $null)
  'SessionEnd'       = @('end',    $null)
  'UserPromptSubmit' = @('prompt', $null)
  'PreToolUse'       = @('pre',    '*')
  'PostToolUse'      = @('post',   '*')
  'Notification'     = @('notify', $null)
  'Stop'             = @('stop',   $null)
}

function Read-Settings {
  if (Test-Path $settingsFile) {
    try { return (Get-Content $settingsFile -Raw | ConvertFrom-Json) }
    catch { throw "settings.json exists but is not valid JSON: $settingsFile" }
  }
  return [PSCustomObject]@{}
}

function Save-Settings($obj) {
  if (Test-Path $settingsFile) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Copy-Item $settingsFile "$settingsFile.bak-$stamp"
    Write-Host "Backed up settings -> settings.json.bak-$stamp" -ForegroundColor DarkGray
  }
  $json = $obj | ConvertTo-Json -Depth 30
  Set-Content -Path $settingsFile -Value $json -Encoding UTF8
}

# Returns groups for an event with our lifecycle.js entries (and any stray
# nulls) removed. Always returns an array via ArrayList to avoid PowerShell's
# empty-array/$null collapsing.
function Remove-OurGroups($groups) {
  $kept = New-Object System.Collections.ArrayList
  foreach ($g in @($groups)) {
    if ($null -eq $g) { continue }
    $isOurs = $false
    foreach ($h in @($g.hooks)) {
      if ($h.command -and $h.command -match 'lifecycle\.js') { $isOurs = $true }
    }
    if (-not $isOurs) { [void]$kept.Add($g) }
  }
  return ,$kept.ToArray()
}

function Install {
  # 1. Build if the exe isn't already published.
  $distExe = Join-Path $root 'dist\ClaudeStatusBar.exe'
  if (-not (Test-Path $distExe)) {
    Write-Host "No published exe found; building..." -ForegroundColor Cyan
    & (Join-Path $root 'build.ps1')
  }

  # 2. Copy exe + hooks into the install dir.
  New-Item -ItemType Directory -Force -Path (Join-Path $installDir 'hooks') | Out-Null
  Copy-Item $distExe (Join-Path $installDir 'ClaudeStatusBar.exe') -Force
  Copy-Item (Join-Path $root 'hooks\lifecycle.js') (Join-Path $installDir 'hooks\lifecycle.js') -Force
  Write-Host "Installed app -> $installDir" -ForegroundColor Green

  # 3. Merge hooks into settings.json.
  $settings = Read-Settings
  if (-not $settings.PSObject.Properties['hooks']) {
    $settings | Add-Member -NotePropertyName 'hooks' -NotePropertyValue ([PSCustomObject]@{})
  }
  $hooks = $settings.hooks

  foreach ($evt in $eventMap.Keys) {
    $arg, $matcher = $eventMap[$evt]
    $cmd = 'node "{0}" {1}' -f $lifecycle, $arg
    $entry = [PSCustomObject]@{ type = 'command'; command = $cmd }
    if ($null -ne $matcher) {
      $group = [PSCustomObject]@{ matcher = $matcher; hooks = @($entry) }
    } else {
      $group = [PSCustomObject]@{ hooks = @($entry) }
    }

    $existing = if ($hooks.PSObject.Properties[$evt]) { $hooks.$evt } else { @() }
    $kept = New-Object System.Collections.ArrayList
    foreach ($g in @(Remove-OurGroups $existing)) {
      if ($null -ne $g) { [void]$kept.Add($g) }
    }
    [void]$kept.Add($group)
    $merged = @($kept.ToArray())

    if ($hooks.PSObject.Properties[$evt]) { $hooks.$evt = $merged }
    else { $hooks | Add-Member -NotePropertyName $evt -NotePropertyValue $merged }
  }

  Save-Settings $settings
  Write-Host "Hooks merged into settings.json." -ForegroundColor Green
  Write-Host ""
  Write-Host "Done. Start a new Claude Code session to see the tray icon." -ForegroundColor Cyan
}

function Uninstall {
  # Strip our hooks from settings.json.
  if (Test-Path $settingsFile) {
    $settings = Read-Settings
    if ($settings.PSObject.Properties['hooks']) {
      $hooks = $settings.hooks
      foreach ($evt in @($hooks.PSObject.Properties.Name)) {
        $cleaned = Remove-OurGroups $hooks.$evt
        if (@($cleaned).Count -eq 0) { $hooks.PSObject.Properties.Remove($evt) }
        else { $hooks.$evt = $cleaned }
      }
      Save-Settings $settings
      Write-Host "Removed hooks from settings.json." -ForegroundColor Green
    }
  }
  # Remove installed files.
  if (Test-Path $installDir) {
    Remove-Item $installDir -Recurse -Force
    Write-Host "Removed $installDir" -ForegroundColor Green
  }
  Write-Host "Uninstalled." -ForegroundColor Cyan
}

if ($Uninstall) { Uninstall } else { Install }
