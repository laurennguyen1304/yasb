using System.Text.Json.Serialization;

namespace ClaudeStatusBar;

/// <summary>
/// The set of activity phases the tray icon can show. Mirrors the "state"
/// field written by hooks/lifecycle.js.
/// </summary>
internal enum Phase
{
    Idle,        // at rest, Claude logo
    Thinking,    // model is producing a turn -> animated spark
    Tool,        // a tool is running -> animated spark (with tool label)
    Permission   // waiting on the user to approve something -> yellow dot
}

/// <summary>
/// Deserialized shape of ~/.claude/statusbar/state.json.
/// </summary>
internal sealed class StatusState
{
    [JsonPropertyName("sessionId")]
    public string? SessionId { get; set; }

    /// <summary>Raw string: idle | thinking | tool | permission.</summary>
    [JsonPropertyName("state")]
    public string? State { get; set; }

    /// <summary>Optional short label, e.g. the active tool name.</summary>
    [JsonPropertyName("label")]
    public string? Label { get; set; }

    /// <summary>Unix seconds when the current turn started (0 = none).</summary>
    [JsonPropertyName("startedAt")]
    public long StartedAt { get; set; }

    /// <summary>Unix seconds when this state was written.</summary>
    [JsonPropertyName("ts")]
    public long Ts { get; set; }

    [JsonIgnore]
    public Phase Phase => State switch
    {
        "thinking" => Phase.Thinking,
        "tool" => Phase.Tool,
        "permission" => Phase.Permission,
        _ => Phase.Idle
    };
}
