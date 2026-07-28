using System.Runtime.InteropServices;

namespace ClaudeStatusBar;

/// <summary>
/// Registers a single system-wide hotkey and raises <see cref="Pressed"/> when
/// it fires. Backed by a message-only <see cref="NativeWindow"/> so the tray app
/// needs no visible form to receive WM_HOTKEY.
/// </summary>
internal sealed class GlobalHotkey : NativeWindow, IDisposable
{
    private const int WM_HOTKEY = 0x0312;
    private const int HotkeyId = 0x1CA1; // arbitrary, unique within this process

    [Flags]
    private enum Mod : uint { Alt = 0x1, Control = 0x2, Shift = 0x4, Win = 0x8, NoRepeat = 0x4000 }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnregisterHotKey(IntPtr hWnd, int id);

    /// <summary>Raised (on the UI thread) each time the hotkey is pressed.</summary>
    public event Action? Pressed;

    private bool _registered;

    public GlobalHotkey() => CreateHandle(new CreateParams());

    /// <summary>
    /// (Re)registers the given combination, parsed from a spec like
    /// "Ctrl+Alt+C". Returns false if the spec is invalid or the OS refuses it
    /// (e.g. another app already owns that combination).
    /// </summary>
    public bool Register(string? spec)
    {
        Unregister();

        if (!TryParse(spec, out uint mods, out uint vk))
            return false;

        _registered = RegisterHotKey(Handle, HotkeyId, mods | (uint)Mod.NoRepeat, vk);
        return _registered;
    }

    public void Unregister()
    {
        if (_registered)
        {
            UnregisterHotKey(Handle, HotkeyId);
            _registered = false;
        }
    }

    /// <summary>Parse a spec like "Ctrl+Alt+C" into Win32 modifiers + a vkey.</summary>
    private static bool TryParse(string? spec, out uint mods, out uint vk)
    {
        mods = 0;
        vk = 0;
        if (string.IsNullOrWhiteSpace(spec)) return false;

        foreach (string raw in spec.Split('+'))
        {
            string token = raw.Trim();
            switch (token.ToLowerInvariant())
            {
                case "ctrl":
                case "control": mods |= (uint)Mod.Control; break;
                case "alt": mods |= (uint)Mod.Alt; break;
                case "shift": mods |= (uint)Mod.Shift; break;
                case "win":
                case "meta":
                case "super": mods |= (uint)Mod.Win; break;
                default:
                    if (Enum.TryParse(token, ignoreCase: true, out Keys key))
                        vk = (uint)key;
                    else
                        return false;
                    break;
            }
        }

        return vk != 0 && mods != 0; // require at least one modifier
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == WM_HOTKEY && m.WParam.ToInt32() == HotkeyId)
            Pressed?.Invoke();
        base.WndProc(ref m);
    }

    public void Dispose()
    {
        Unregister();
        DestroyHandle();
    }
}
