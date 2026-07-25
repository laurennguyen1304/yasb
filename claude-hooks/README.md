# Claude Code hooks for the `claude_code` widget

The [`claude_code`](../docs/widgets/claude_code.md) bar widget only *reads*
status — the numbers come from these hooks, which Claude Code runs on each
lifecycle event and which write `~/.claude/statusbar/state.json`. Without them
the widget loads but stays **idle**.

## What it does

`lifecycle.js` is invoked by Claude Code with an event name, reads the hook
payload from stdin, and maintains a tiny state machine in
`~/.claude/statusbar/state.json`:

```json
{ "sessionId": "…", "state": "idle|thinking|tool|permission",
  "label": "Edit", "startedAt": 1700000000, "ts": 1700000000 }
```

The write is atomic (temp file + rename) with a retry/fallback so a reader
holding the file on Windows never leaves the bar showing a stale state.

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
| `Notification`    | notify | permission (waiting on you) |
| `Stop`            | stop   | idle |
| `SessionEnd`      | end    | idle |

## Notes

- This is the Windows counterpart to the hook layer behind the macOS
  [claude-status-bar](https://github.com/m1ckc3s/claude-status-bar) app and uses
  the same state-file contract.
- Nothing here talks to the network; it only writes a local JSON file.
