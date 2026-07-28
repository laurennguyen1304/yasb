# Claude Status Bar (Windows)

A lightweight system-tray status indicator for [Claude Code](https://claude.com/claude-code) on Windows, with a built-in quick-calculator. It mirrors the macOS status-bar app: an animated Claude "spark" in the notification area that reflects what Claude is doing, an elapsed timer, and an open/close lifecycle driven by Claude Code hooks.

## Features

- **Live activity icon** — the tray icon animates while Claude is thinking or running a tool, shows a yellow dot when waiting for permission, and sits at rest when idle.
- **Elapsed timer** — see how long the current turn has been running (toggle in the tray menu).
- **Done chime** — optional sound when a turn longer than a minute completes.
- **Calculator bar** — a global hotkey pops up a slim calculator that expands out of the status bar (see below).
- **Self-managing lifecycle** — launches on `SessionStart` and quits itself once no Claude sessions remain.
- **Single file, no assets** — the tray icon is drawn at runtime with GDI+, so the whole app ships as one `.exe`.

## Calculator bar

Press **`Ctrl + Alt + C`** anywhere to toggle a slim calculator bar that slides out beside the tray and stretches left along the taskbar. There are no buttons — you just type:

- **Type a formula** and the result appears live as you type, e.g. `12 + 30 * 2` → `72`.
- **Thousands separators** — results are grouped for readability, e.g. `1000 * 1000` → `1,000,000`.
- **Long numbers stay readable** — the result auto-shrinks to fit rather than being truncated.
- **`Enter`** copies the result to the clipboard (the `=` briefly flips to `✓`).
- **`Esc`** or clicking elsewhere hides the bar.
- Also available from the tray menu: **right-click the tray icon → Calculator**.

Supported operators: `+  −  *  /  %  ^`, parentheses, unary minus, and decimals, with the usual precedence.

### Changing the hotkey

The shortcut is stored in `~/.claude/statusbar/settings.json` under `calculatorHotkey` (default `"Ctrl+Alt+C"`). Edit it to any combination with at least one modifier, for example:

```json
{ "calculatorHotkey": "Ctrl+Shift+K" }
```

Modifiers: `Ctrl`, `Alt`, `Shift`, `Win`. If the OS or another app already owns the combination, registration is silently skipped — the tray-menu **Calculator** item still works.

## Requirements

- Windows 10/11 (x64)
- [.NET 8 SDK](https://dotnet.microsoft.com/download) — to build (`winget install --id Microsoft.DotNet.SDK.8 -e`)
- Node.js — used by the lifecycle hooks
- Claude Code

## Install

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

This will:

1. Build the single-file exe (if `dist\ClaudeStatusBar.exe` isn't already present).
2. Copy the exe and hooks into `~/.claude/claude-status-bar`.
3. Merge the lifecycle hooks into `~/.claude/settings.json` (with a timestamped backup).

Start a new Claude Code session and the tray icon appears.

### Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall
```

Removes the installed files and strips the hooks from `settings.json`.

## Build only

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Publishes a single-file exe to `.\dist\ClaudeStatusBar.exe`.

## How it works

The hooks in `hooks/lifecycle.js` fire on Claude Code lifecycle events (`SessionStart`, `PreToolUse`, `Stop`, etc.) and write the current activity to `~/.claude/statusbar/state.json`. The tray app polls that file and animates the icon accordingly. Session presence is tracked via marker files in `~/.claude/statusbar/sessions.d/`; when the last one disappears, the app exits.

| Path | Purpose |
|------|---------|
| `~/.claude/statusbar/state.json` | Current activity (written by hooks, read by the app) |
| `~/.claude/statusbar/settings.json` | User preferences (timer, chime, color, calculator hotkey) |
| `~/.claude/statusbar/sessions.d/` | One marker file per active session |

### Source layout

| File | Responsibility |
|------|----------------|
| `src/Program.cs` | Entry point + single-instance mutex |
| `src/TrayApp.cs` | Tray icon, polling, menu, hotkey wiring |
| `src/IconRenderer.cs` | Draws the animated spark icon with GDI+ |
| `src/CalculatorForm.cs` | The calculator flyout bar |
| `src/ExpressionEvaluator.cs` | Recursive-descent arithmetic parser |
| `src/GlobalHotkey.cs` | System-wide hotkey registration |
| `src/AppSettings.cs` / `StatusState.cs` / `AppPaths.cs` | Settings, state model, shared paths |

## License

MIT
