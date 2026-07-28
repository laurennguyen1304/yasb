using System.Threading;

namespace ClaudeStatusBar;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        // Single-instance gate: hooks launch the exe on every SessionStart, so
        // a second copy must bow out quietly rather than stacking tray icons.
        using var mutex = new Mutex(initiallyOwned: true, "ClaudeStatusBarWindows.SingleInstance", out bool isNew);
        if (!isNew)
            return;

        ApplicationConfiguration.Initialize();
        Application.Run(new TrayApp());

        GC.KeepAlive(mutex);
    }
}
