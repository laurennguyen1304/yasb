# Claude Code hooks for the `claude_code` widget

The [`claude_code`](../docs/widgets/claude_code.md) bar widget only *reads*
status — the numbers come from these hooks, which Claude Code runs on each
lifecycle event and which write `~/.claude/statusbar/state.json`. Without them
the widget loads but stays **idle**.

## What it does

`lifecycle.js` is invoked by Claude Code with an event name, reads the hook
payload from stdin, and maintains a tiny state machine in two places:

- `~/.claude/statusbar/state.json` — the most-recently-active session (what
  the bar label itself shows).
- `~/.claude/statusbar/state.d/<sessionId>.json` — one file per **live**
  session, same shape, removed on `SessionEnd`. Powers the widget's
  session-list popup (right-click / `show_sessions`).

```json
{ "sessionId": "…", "state": "idle|thinking|tool|permission",
  "label": "Edit", "cwd": "C:\\path\\to\\project", "project": "project",
  "entrypoint": "cli", "termProgram": "vscode",
  "startedAt": 1700000000, "ts": 1700000000 }
```

`cwd`/`project` come from the hook payload's working directory and drive the
widget's click-to-open action and `{project}` placeholder. `entrypoint`/
`termProgram` come from Claude Code's own `CLAUDE_CODE_ENTRYPOINT`/
`TERM_PROGRAM` env vars and show up as a badge per session in the list (e.g.
distinguishing a `cli` session from `claude-desktop`).

Both writes are atomic (temp file + rename) with a retry/fallback so a reader
holding the file on Windows never leaves the bar showing a stale state.
Per-session files older than 24h are swept on the next `SessionStart` (a
crashed session's file that never got a `SessionEnd`).

## Requirements

- **Node.js** on your `PATH` (`node --version`).

## Install (manual — add to `~/.claude/settings.json`)

Add the block below to your Claude Code settings file
(`%USERPROFILE%\.claude\settings.json`), merging into any existing `"hooks"`
object. **Replace `PATH-TO` with the absolute path to this folder** and use
forward slashes, e.g. `C:/Users/you/yasb/claude-hooks/lifecycle.js`.

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "node \"PATH-TO/lifecycle.js\" start" }] }
    ],
    "SessionEnd": [
      { "hooks": [{ "type": "command", "command": "node \"PATH-TO/lifecycle.js\" end" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "node \"PATH-TO/lifecycle.js\" prompt" }] }
    ],
    "PreToolUse": [
      { "matcher": "*", "hooks": [{ "type": "command", "command": "node \"PATH-TO/lifecycle.js\" pre" }] }
    ],
    "PostToolUse": [
      { "matcher": "*", "hooks": [{ "type": "command", "command": "node \"PATH-TO/lifecycle.js\" post" }] }
    ],
    "Notification": [
      { "hooks": [{ "type": "command", "command": "node \"PATH-TO/lifecycle.js\" notify" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "node \"PATH-TO/lifecycle.js\" stop" }] }
    ]
  }
}
```

Start a new Claude Code session, run something, and the `claude_code` widget
will move through **thinking → tool name → idle** in real time.

## Event → state mapping

| Claude Code event | arg | widget state |
| ----------------- | ------ | ------------ |
| `SessionStart`    | start  | idle |
| `UserPromptSubmit`| prompt | thinking (starts the timer) |
| `PreToolUse`      | pre    | tool (shows the tool name) |
| `PostToolUse`     | post   | thinking |
| `Notification`    | notify | permission — only if the notification actually looks like a permission prompt (`notification_type: permission_prompt`, or the message mentions "permission"/"approve"/"allow"); other notifications (e.g. the idle "Claude is waiting for your input" nudge) are ignored |
| *(desktop app)*   | permreq | permission — the Claude Code desktop app's own permission signal, not redundant with `notify` (CLI-only) |
| `Stop`            | stop   | idle |
| `SessionEnd`      | end    | idle |

## Notes

- This is the Windows counterpart to the hook layer behind the macOS
  [claude-status-bar](https://github.com/m1ckc3s/claude-status-bar) app and uses
  the same state-file contract.
- Nothing here talks to the network; it only writes a local JSON file.
