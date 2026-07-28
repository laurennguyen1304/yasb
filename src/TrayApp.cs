using System.IO;
using System.Media;
using System.Text.Json;

namespace ClaudeStatusBar;

/// <summary>
/// The tray application. Polls ~/.claude/statusbar/state.json, animates the
/// NotifyIcon to reflect Claude's activity, shows an elapsed timer, and quits
/// itself once no sessions remain (matching the macOS app's lifecycle).
/// </summary>
internal sealed class TrayApp : ApplicationContext
{
    private const int PollMs = 400;   // how often we read state.json
    private const int AnimMs = 110;   // animation frame cadence

    private readonly NotifyIcon _tray;
    private readonly IconRenderer _renderer = new();
    private readonly System.Windows.Forms.Timer _pollTimer = new();
    private readonly System.Windows.Forms.Timer _animTimer = new();
    private readonly GlobalHotkey _hotkey = new();
    private CalculatorForm? _calculator;

    private AppSettings _settings;
    private StatusState _state = new();
    private Phase _lastRenderedPhase = (Phase)(-1);
    private int _animFrame;
    private long _activeStartedAt;    // remembered while a turn is active
    private bool _sawSession;         // true once any Claude session has appeared

    // Menu items we toggle checkmarks on.
    private readonly ToolStripMenuItem _miStatus;
    private readonly ToolStripMenuItem _miTimer;
    private readonly ToolStripMenuItem _miChime;
    private readonly ToolStripMenuItem _miColor;

    public TrayApp()
    {
        _settings = AppSettings.Load();

        _miStatus = new ToolStripMenuItem("Idle") { Enabled = false };
        _miTimer = new ToolStripMenuItem("Show timer", null, (_, _) => ToggleTimer())
            { Checked = _settings.ShowTimer };
        _miChime = new ToolStripMenuItem("Chime when done (>1m)", null, (_, _) => ToggleChime())
            { Checked = _settings.ChimeOnDone };
        _miColor = new ToolStripMenuItem("Use system color", null, (_, _) => ToggleColor())
            { Checked = _settings.UseSystemColor };

        string hotkeyHint = string.IsNullOrWhiteSpace(_settings.CalculatorHotkey)
            ? ""
            : $"  ({_settings.CalculatorHotkey})";
        var miCalculator = new ToolStripMenuItem("Calculator" + hotkeyHint, null, (_, _) => ToggleCalculator());

        var menu = new ContextMenuStrip();
        menu.Items.Add(_miStatus);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(miCalculator);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(_miTimer);
        menu.Items.Add(_miChime);
        menu.Items.Add(_miColor);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(new ToolStripMenuItem("Quit", null, (_, _) => QuitApp()));

        _tray = new NotifyIcon
        {
            Visible = true,
            Text = "Claude — idle",
            ContextMenuStrip = menu,
            Icon = _renderer.Build(Phase.Idle, 0, _settings.UseSystemColor)
        };

        _pollTimer.Interval = PollMs;
        _pollTimer.Tick += (_, _) => Poll();
        _pollTimer.Start();

        _animTimer.Interval = AnimMs;
        _animTimer.Tick += (_, _) => AnimateTick();
        _animTimer.Start();

        _hotkey.Pressed += ToggleCalculator;
        _hotkey.Register(_settings.CalculatorHotkey);

        Poll();
    }

    private void ToggleCalculator()
    {
        _calculator ??= new CalculatorForm();
        _calculator.Toggle();
    }

    private void Poll()
    {
        // Self-quit once Claude sessions have come and gone. If the app was
        // launched standalone (no session ever appeared, e.g. someone just
        // wants the calculator), it stays running until quit from the menu.
        if (CountSessions() > 0)
        {
            _sawSession = true;
        }
        else if (_sawSession)
        {
            QuitApp();
            return;
        }

        StatusState? next = ReadState();
        if (next != null)
        {
            Phase prev = _state.Phase;
            _state = next;
            MaybeChime(prev, _state);
        }

        UpdateMenuAndTooltip();
    }

    private void AnimateTick()
    {
        Phase phase = _state.Phase;
        bool animated = phase is Phase.Thinking or Phase.Tool;

        if (animated)
        {
            _animFrame = (_animFrame + 1) % IconRenderer.AnimFrames;
            _tray.Icon = _renderer.Build(phase, _animFrame, _settings.UseSystemColor);
            _lastRenderedPhase = phase;
        }
        else if (phase != _lastRenderedPhase)
        {
            // Static phases only need a redraw on transition.
            _animFrame = 0;
            _tray.Icon = _renderer.Build(phase, 0, _settings.UseSystemColor);
            _lastRenderedPhase = phase;
        }
    }

    private void UpdateMenuAndTooltip()
    {
        string label = _state.Phase switch
        {
            Phase.Thinking => "Thinking",
            Phase.Tool => string.IsNullOrEmpty(_state.Label) ? "Running tool" : _state.Label!,
            Phase.Permission => "Waiting for permission",
            _ => "Idle"
        };

        string elapsed = "";
        if (_settings.ShowTimer && _state.Phase != Phase.Idle && _state.StartedAt > 0)
        {
            long secs = Now() - _state.StartedAt;
            if (secs >= 0) elapsed = "  " + FormatElapsed(secs);
        }

        _miStatus.Text = label + elapsed;

        // NotifyIcon.Text is capped at 63 chars.
        string tip = $"Claude — {label}{elapsed}";
        _tray.Text = tip.Length > 63 ? tip[..63] : tip;
    }

    private void MaybeChime(Phase prev, StatusState now)
    {
        bool nowActive = now.Phase is Phase.Thinking or Phase.Tool;
        bool wasActive = prev is Phase.Thinking or Phase.Tool or Phase.Permission;

        // Track when the current turn began (startedAt gets cleared on stop).
        if (nowActive && now.StartedAt > 0)
            _activeStartedAt = now.StartedAt;

        if (!_settings.ChimeOnDone) return;

        // Fire once when a turn finishes (active -> idle) that ran over a minute.
        if (wasActive && now.Phase == Phase.Idle && _activeStartedAt > 0)
        {
            long elapsed = Now() - _activeStartedAt;
            _activeStartedAt = 0;
            if (elapsed >= 60)
            {
                try { SystemSounds.Asterisk.Play(); } catch { /* ignore */ }
            }
        }
    }

    private static StatusState? ReadState()
    {
        for (int attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                if (!File.Exists(AppPaths.StateFile)) return null;
                using var fs = new FileStream(AppPaths.StateFile, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
                using var reader = new StreamReader(fs);
                string json = reader.ReadToEnd();
                if (string.IsNullOrWhiteSpace(json)) return null;
                return JsonSerializer.Deserialize<StatusState>(json);
            }
            catch
            {
                Thread.Sleep(20); // brief retry against a concurrent rename
            }
        }
        return null;
    }

    private static int CountSessions()
    {
        try
        {
            if (!Directory.Exists(AppPaths.SessionsDir)) return 0;
            return Directory.EnumerateFiles(AppPaths.SessionsDir).Count();
        }
        catch
        {
            return 1; // on error, assume alive rather than self-terminating
        }
    }

    private static string FormatElapsed(long secs)
    {
        long m = secs / 60, s = secs % 60;
        return m > 0 ? $"{m}m {s}s" : $"{s}s";
    }

    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeSeconds();

    private void ToggleTimer()
    {
        _settings.ShowTimer = !_settings.ShowTimer;
        _miTimer.Checked = _settings.ShowTimer;
        _settings.Save();
        UpdateMenuAndTooltip();
    }

    private void ToggleChime()
    {
        _settings.ChimeOnDone = !_settings.ChimeOnDone;
        _miChime.Checked = _settings.ChimeOnDone;
        _settings.Save();
    }

    private void ToggleColor()
    {
        _settings.UseSystemColor = !_settings.UseSystemColor;
        _miColor.Checked = _settings.UseSystemColor;
        _settings.Save();
        _lastRenderedPhase = (Phase)(-1); // force redraw
        AnimateTick();
    }

    private void QuitApp()
    {
        _pollTimer.Stop();
        _animTimer.Stop();
        _hotkey.Dispose();
        _calculator?.Dispose();
        _tray.Visible = false;
        _tray.Dispose();
        _renderer.Dispose();
        ExitThread();
    }
}
