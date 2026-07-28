using System.IO;

namespace ClaudeStatusBar;

/// <summary>
/// Shared filesystem layout. Must stay in sync with hooks/lifecycle.js so the
/// hooks (writers) and the tray app (reader) agree on where state lives.
/// Layout mirrors the macOS original: ~/.claude/statusbar/
/// </summary>
internal static class AppPaths
{
    public static string ClaudeDir =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".claude");

    public static string StatusBarDir => Path.Combine(ClaudeDir, "statusbar");

    public static string StateFile => Path.Combine(StatusBarDir, "state.json");

    public static string SessionsDir => Path.Combine(StatusBarDir, "sessions.d");

    public static string SettingsFile => Path.Combine(StatusBarDir, "settings.json");
}
