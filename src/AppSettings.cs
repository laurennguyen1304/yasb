using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ClaudeStatusBar;

/// <summary>
/// User-facing preferences for the tray app, persisted to
/// ~/.claude/statusbar/settings.json. Independent of the volatile state.json.
/// </summary>
internal sealed class AppSettings
{
    [JsonPropertyName("showTimer")]
    public bool ShowTimer { get; set; } = true;

    /// <summary>Play a chime when a turn longer than 60s completes.</summary>
    [JsonPropertyName("chimeOnDone")]
    public bool ChimeOnDone { get; set; } = false;

    /// <summary>Use the system text color instead of Claude coral.</summary>
    [JsonPropertyName("useSystemColor")]
    public bool UseSystemColor { get; set; } = false;

    /// <summary>
    /// Global hotkey that toggles the calculator flyout, e.g. "Ctrl+Alt+C".
    /// At least one modifier is required. Empty disables the hotkey.
    /// </summary>
    [JsonPropertyName("calculatorHotkey")]
    public string CalculatorHotkey { get; set; } = "Ctrl+Alt+C";

    private static readonly JsonSerializerOptions Opts = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never
    };

    public static AppSettings Load()
    {
        try
        {
            if (File.Exists(AppPaths.SettingsFile))
            {
                string json = File.ReadAllText(AppPaths.SettingsFile);
                return JsonSerializer.Deserialize<AppSettings>(json) ?? new AppSettings();
            }
        }
        catch
        {
            // Corrupt or unreadable settings shouldn't stop the app from running.
        }
        return new AppSettings();
    }

    public void Save()
    {
        try
        {
            Directory.CreateDirectory(AppPaths.StatusBarDir);
            string json = JsonSerializer.Serialize(this, Opts);
            string tmp = AppPaths.SettingsFile + ".tmp";
            File.WriteAllText(tmp, json);
            File.Copy(tmp, AppPaths.SettingsFile, overwrite: true);
            File.Delete(tmp);
        }
        catch
        {
            // Best-effort persistence.
        }
    }
}
