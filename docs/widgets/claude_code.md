# Claude Code Widget

Shows the live status of your Claude Code sessions in the bar — the Windows/YASB
counterpart to the macOS [`claude-status-bar`](https://github.com/m1ckc3s/claude-status-bar)
menu-bar app. It surfaces four phases:

| Phase        | Meaning                                   | Default text |
| ------------ | ----------------------------------------- | ------------ |
| `idle`       | No turn in progress                       | `idle`       |
| `thinking`   | Model is producing a turn                 | `thinking`   |
| `tool`       | A tool is running (shows the tool name)   | e.g. `Edit`  |
| `permission` | Claude is waiting for you to approve       | `waiting`    |

An optional live elapsed-time counter (`1m 4s`) ticks while Claude is working.

## How it works

The widget is a thin reader over `~/.claude/statusbar/state.json`, a tiny JSON
file that Claude Code hooks rewrite on every lifecycle event. The file is picked
up **instantly** via a `QFileSystemWatcher`; the `update_interval` timer only
advances the elapsed counter. No polling of Claude Code itself, no network.

State-file contract (written by the hooks, read by this widget):

```json
{ "sessionId": "…", "state": "idle|thinking|tool|permission",
  "label": "Edit", "startedAt": 1700000000, "ts": 1700000000 }
```

See [Setup](#setup) for wiring the hooks.

## Options

| Option            | Type | Default                        | Description |
| ----------------- | ---- | ------------------------------ | ----------- |
| `label`           | str  | `<span>{icon}</span> {status}` | Bar label. Placeholders: `{icon}`, `{status}`, `{elapsed}`, `{tool}`, `{state}`. |
| `label_alt`       | str  | `<span>{icon}</span> {status} {elapsed}` | Alternate label toggled by `toggle_label`. |
| `state_file`      | str  | `""` (→ `~/.claude/statusbar/state.json`) | Override the state-file path. `~` and env vars are expanded. |
| `update_interval` | int  | `1000`                         | Elapsed-timer tick in ms (200–60000). State changes are still instant. |
| `show_elapsed`    | bool | `true`                         | Show the elapsed counter while working. |
| `hide_when_idle`  | bool | `false`                        | Collapse the widget when no session is active. |
| `idle_text`       | str  | `idle`                         | Status text when idle. |
| `thinking_text`   | str  | `thinking`                     | Status text while thinking. |
| `permission_text` | str  | `waiting`                      | Status text on a permission prompt. |
| `stale_after`     | int  | `0` (off)                      | Seconds after which a stuck "working" state is treated as idle. |
| `tooltip`         | bool | `true`                         | Show a tooltip with status + elapsed. |
| `icons`           | map  | `● ● ● ●`                       | Per-phase glyph: `idle`, `thinking`, `tool`, `permission`. |
| `mascot`          | map  | see below                      | The animated Claude mascot face drawn to the left of the bullet/text. |
| `callbacks`       | map  | `on_left: toggle_label`        | `on_left` / `on_middle` / `on_right`. |

The `{icon}` span carries a CSS class equal to the current phase
(`idle`/`thinking`/`tool`/`permission`), so you can colour it per state — see the
stylesheet example below.

### `mascot` — the animated Claude face

A small pixel-art Claude mascot (rounded coral face, two block eyes, a row of
pale "teeth" along the bottom edge), drawn at runtime with QPainter — no image
assets — and placed to the left of the bullet + status text. It's purely
additive; the bullet glyph and text are unaffected. It bobs gently while
thinking or running a tool, sits still at rest, and dims with a yellow dot
badge while waiting on a permission prompt. The bob timer only runs while
actually animating, so it's free in the background.

| Option                 | Type | Default     | Description |
|-------------------------|------|-------------|--------------|
| `enabled`               | bool | `true`      | Show the mascot. |
| `size`                  | int  | `16`        | Diameter in pixels. |
| `color`                 | str  | `#E8825A`   | Face colour (Claude coral). |
| `eye_color`             | str  | `#1E1E1E`   | Eye colour. |
| `mouth_color`           | str  | `#FBEFE3`   | "Teeth" colour along the bottom edge. |
| `permission_dot_color`  | str  | `#F2B82E`   | Dot colour shown over the dimmed face while waiting on you. |

## Example configuration

```yaml
claude_code:
  type: "yasb.claude_code.ClaudeCodeWidget"
  options:
    label: "<span>{icon}</span> {status}"
    label_alt: "<span>{icon}</span> {status} {elapsed}"
    show_elapsed: true
    hide_when_idle: false
    stale_after: 900
    icons:
      idle: "●"
      thinking: "●"
      tool: "●"
      permission: "●"
    callbacks:
      on_left: "toggle_label"
```

Then add `"claude_code"` to a bar's widget list (e.g. under `right:`).

## Example stylesheet (Catppuccin)

```css
.claude-code {
    padding: 0 8px;
}
.claude-code .label {
    color: var(--text);
}
.claude-code .icon {
    font-size: 10px;
    padding-right: 6px;
}
/* Per-state icon colour */
.claude-code .icon.idle       { color: var(--overlay0); }
.claude-code .icon.thinking   { color: var(--mauve); }
.claude-code .icon.tool       { color: var(--blue); }
.claude-code .icon.permission { color: var(--yellow); }
```

## Setup

The widget only reads the state file — the numbers come from Claude Code hooks
that write it. A ready-to-install hook script and setup guide are bundled in
this repo at [`claude-hooks/`](../../claude-hooks/README.md): add the provided
block to your `~/.claude/settings.json`, start a Claude Code session, and the
widget updates live. Any hook set that produces the contract above also works.
