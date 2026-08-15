These PNGs are the official Claude "spark" mark (claude.ai favicon / in-chat
thinking animation), sourced as pre-rasterized 60×60 alpha masks from
[m1ckc3s/claude-status-bar](https://github.com/m1ckc3s/claude-status-bar)
(`Sources/SparkFrames.swift`, `Sources/LogoFrame.swift`), MIT-licensed. Tinted
at runtime by the `claude_code` widget the same way that project uses them.

| File            | Source                                     |
| --------------- | ------------------------------------------- |
| `spark_00..07.png` | 8-frame "thinking spark" animation cycle |
| `logo.png`      | Resting Claude spark mark                   |
| `working.gif`   | User-provided animated icon shown by `icon_style: "dot"` while thinking/running a tool. Swap this file to change it — used as-is via `QMovie`, no tinting. |
