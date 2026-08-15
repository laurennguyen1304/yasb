# Claude Code Widget

Shows the live status of your Claude Code sessions in the bar — the Windows/YASB
counterpart to the macOS [`claude-status-bar`](https://github.com/m1ckc3s/claude-status-bar)
menu-bar app. It surfaces four phases:

| Phase        | Meaning                                   | Default text          |
| ------------ | ----------------------------------------- | ---------------------- |
| `idle`       | No turn in progress                       | `Idle`                 |
| `thinking`   | Model is producing a turn                 | rotating word, e.g. `Cooking…` |
| `tool`       | A tool is running (shows a friendly name) | e.g. `Editing`         |
| `permission` | Claude is waiting for you to approve      | `Awaiting permission`  |

While working, the icon animates and the `thinking` phase rotates through a
playful verb per turn ("Cooking…", "Manifesting…", …) unless you turn
`thinking_words` off. By default (`icon_style: "dot"`) the icon is a plain
coloured dot per state (`icons`) — except while thinking/running a tool, when
it's swapped for an animated GIF (`resources/claude_code/working.gif`, bring
your own by replacing that file). Set `icon_style` to `image` for the real
Claude spark mark instead (tinted with `icon_tint`, animated through its
actual claude.ai "thinking" sprite), or `spinner` for a text-glyph animation.
An optional live elapsed-time counter (`1m 4s`) ticks while Claude is
working. Clicking the widget (configurable) opens the session's project
folder in Explorer, VS Code, or a terminal.

## How it works

The widget is a thin reader over `~/.claude/statusbar/state.json`, a tiny JSON
file that Claude Code hooks rewrite on every lifecycle event. The file is picked
up **instantly** via a `QFileSystemWatcher`. A frame timer only runs while a
session is active, to animate the spinner and (optionally) advance the elapsed
counter — it's idle otherwise. No polling of Claude Code itself, no network.

State-file contract (written by the hooks, read by this widget):

```json
{ "sessionId": "…", "state": "idle|thinking|tool|permission",
  "label": "Edit", "cwd": "C:\\path\\to\\project", "project": "project",
  "entrypoint": "cli", "termProgram": "vscode",
  "startedAt": 1700000000, "ts": 1700000000 }
```

`cwd`/`project` are optional — omit them and the click-to-open action and
`{project}` placeholder just have nothing to show. `entrypoint`/`termProgram`
(from Claude Code's own `CLAUDE_CODE_ENTRYPOINT`/`TERM_PROGRAM` env vars) are
shown as a badge next to the project name in the session list, distinguishing
e.g. a `cli` session from a `claude-desktop` one — optional too.

The hooks also maintain `state.d/<sessionId>.json`, one file per live session
in the same shape, for the session-list popup (see [Session list](#session-list));
removed on `SessionEnd`.

See [Setup](#setup) for wiring the hooks.

## Options

| Option            | Type | Default                        | Description |
| ----------------- | ---- | ------------------------------ | ----------- |
| `label`           | str  | `<span>{icon}</span> {status}` | Bar label. Placeholders: `{icon}`, `{status}`, `{elapsed}`, `{tool}`, `{state}`, `{project}`, `{cwd}`. |
| `label_alt`       | str  | `<span>{icon}</span> {status} {elapsed}` | Alternate label toggled by `toggle_label`. |
| `state_file`      | str  | `""` (→ `~/.claude/statusbar/state.json`) | Override the state-file path. `~` and env vars are expanded. |
| `icon_style`      | str  | `dot`                           | `dot` shows a static coloured dot per state (see `icons`), swapped for `resources/claude_code/working.gif` while thinking/running a tool; `image` renders the real Claude spark mark instead (animated while working); `spinner` animates text glyphs instead. |
| `icon_tint`       | str  | `#D97756`                      | Tint colour applied to the `image` icon (hex). Not used by `dot`/`spinner`. |
| `icon_size`       | int  | `16`                           | Rendered size in px for the `image` icon and the `dot` style's working.gif (8–64). |
| `frame_interval`  | int  | `150`                          | Text-glyph animation speed, ms per frame (60–1000) — applies to `spinner` and the `image` style. The `dot` style's GIF plays at its own native frame rate. |
| `thinking_words`  | bool | `true`                         | Rotate a playful verb ("Cooking…", "Manifesting…", …) per turn instead of the static `thinking_text`. |
| `show_elapsed`    | bool | `true`                         | Show the elapsed counter while working. |
| `hide_when_idle`  | bool | `false`                        | Collapse the widget when no session is active. |
| `idle_text`       | str  | `Idle`                         | Status text when idle. |
| `thinking_text`   | str  | `Thinking…`                    | Status text while thinking, when `thinking_words` is off. |
| `permission_text` | str  | `Awaiting permission`          | Status text on a permission prompt. |
| `click_action`    | str  | `explorer`                     | What clicking does with the session's project folder (`cwd`): `explorer`, `vscode`, `terminal`, or `none`. |
| `tool_labels`     | map  | `{}`                           | Override/extend the built-in tool-name → friendly-label map (e.g. `{"Bash": "Running"}`). |
| `stale_after`     | int  | `0` (off)                      | Seconds after which a stuck "working" state is treated as idle. |
| `tooltip`         | bool | `true`                         | Show a tooltip with project, status, elapsed, and (if `click_action` isn't `none`) the click target. |
| `icons`           | map  | `● ● ● ●`                       | Per-phase glyph. Used for all four phases in `spinner` style; for `dot` style, used for `idle`/`permission` only (`thinking`/`tool` show the working.gif). Ignored by `image` style. |
| `callbacks`       | map  | `on_left: open_project`, `on_middle: toggle_label`, `on_right: show_sessions` | `on_left` / `on_middle` / `on_right`. |
| `menu`            | map  | see below                      | Popup styling/position for `show_sessions` — same shape as `claude_usage`'s `menu` (`blur`, `round_corners`, `round_corners_type`, `border_color`, `alignment`, `direction`, `offset_top`, `offset_left`). |

The `{icon}` span carries a CSS class equal to the current phase
(`idle`/`thinking`/`tool`/`permission`), so you can colour it per state — see the
stylesheet example below. This applies whenever the icon is text: `spinner`
always, and `dot` for its `idle`/`permission` glyphs. `icon_style: "image"`,
and `dot`'s `thinking`/`tool` working.gif, are images/animations — coloured
once via `icon_tint` (image) or baked into the GIF itself (dot), not CSS.

## Session list

Right-click the widget (`show_sessions`, the default `on_right`) to pop open a
list of every live session — one row per session with its icon, project,
status, and elapsed time, sourced from `state.d/<sessionId>.json` files next
to the main state file. The list is read-only (no click-through to a
session); it's driven by the same `menu` options as `claude_usage`'s popup
(`blur`, `round_corners`, `alignment`, `direction`, `offset_top`,
`offset_left`).

## Example configuration

```yaml
claude_code:
  type: "yasb.claude_code.ClaudeCodeWidget"
  options:
    label: "<span>{icon}</span> {status}"
    label_alt: "<span>{icon}</span> {status} {elapsed}"
    icon_style: "dot"
    icon_tint: "#D97756"
    icon_size: 16
    thinking_words: true
    show_elapsed: true
    hide_when_idle: false
    click_action: "explorer"
    stale_after: 900
    icons:
      idle: "●"
      thinking: "●"
      tool: "●"
      permission: "●"
    callbacks:
      on_left: "open_project"
      on_middle: "toggle_label"
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
/* Per-state icon colour (spinner/dot styles only) */
.claude-code .icon.idle       { color: var(--overlay0); }
.claude-code .icon.thinking   { color: var(--mauve); }
.claude-code .icon.tool       { color: var(--blue); }
.claude-code .icon.permission { color: var(--yellow); }

/* Session-list popup */
.claude-code-menu {
    background-color: var(--crust);
    border: 1px solid var(--surface0);
    border-radius: 8px;
    min-width: 260px;
}
.claude-code-menu .header { font-size: 13px; font-weight: 700; color: var(--text); padding: 12px 14px 8px 14px; }
.claude-code-menu .empty  { font-size: 12px; color: var(--subtext0); padding: 4px 14px 14px 14px; }
.claude-code-menu .session-row { padding: 6px 14px; }
.claude-code-menu .row-title  { font-size: 12px; font-weight: 600; color: var(--text); }
.claude-code-menu .row-status { font-size: 11px; }
.claude-code-menu .row-icon.idle,       .claude-code-menu .row-status.idle       { color: var(--overlay0); }
.claude-code-menu .row-icon.thinking,   .claude-code-menu .row-status.thinking   { color: var(--mauve); }
.claude-code-menu .row-icon.tool,       .claude-code-menu .row-status.tool       { color: var(--blue); }
.claude-code-menu .row-icon.permission, .claude-code-menu .row-status.permission { color: var(--yellow); }
```

## Setup

The widget only reads the state file — the numbers come from Claude Code hooks
that write it. A ready-to-install hook script and setup guide are bundled in
this repo at [`claude-hooks/`](../../claude-hooks/README.md): add the provided
block to your `~/.claude/settings.json`, start a Claude Code session, and the
widget updates live. Any hook set that produces the contract above also works.
