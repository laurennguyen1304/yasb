using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;

namespace ClaudeStatusBar;

/// <summary>
/// Draws the tray icon at runtime with GDI+ so the app ships as a single exe
/// with no image assets. Produces a Claude-style four-point "spark" that can be
/// animated (rotated/pulsed) or shown at rest, plus a yellow permission dot.
/// </summary>
internal sealed class IconRenderer : IDisposable
{
    // Claude coral/orange.
    private static readonly Color Coral = Color.FromArgb(0xCC, 0x78, 0x5C);
    private static readonly Color Permission = Color.FromArgb(0xF2, 0xB8, 0x2E);

    private const int Size = 32; // render size; Windows scales to the tray slot

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool DestroyIcon(IntPtr handle);

    private Icon? _current;

    /// <summary>
    /// Build an icon for the given phase. <paramref name="frame"/> advances the
    /// animation (ignored when idle). <paramref name="useSystemColor"/> renders
    /// the spark in the tray's text color instead of coral.
    /// </summary>
    public Icon Build(Phase phase, int frame, bool useSystemColor)
    {
        var bmp = new Bitmap(Size, Size);
        try
        {
            using var g = Graphics.FromImage(bmp);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.Clear(Color.Transparent);

            Color color = useSystemColor ? SystemColors.WindowText : Coral;

            switch (phase)
            {
                case Phase.Permission:
                    DrawPermissionDot(g);
                    break;
                case Phase.Thinking:
                case Phase.Tool:
                    // Animated: rotate slowly and pulse the size.
                    double t = (frame % AnimFrames) / (double)AnimFrames;
                    float angle = (float)(t * 90.0); // 4-fold symmetry -> 90deg loop
                    float pulse = 0.85f + 0.15f * (float)Math.Sin(t * Math.PI * 2);
                    DrawSpark(g, color, angle, pulse, fill: true);
                    break;
                default: // Idle
                    DrawSpark(g, color, 0f, 1f, fill: true);
                    break;
            }

            ReplaceCurrent(bmp);
            return _current!;
        }
        finally
        {
            bmp.Dispose();
        }
    }

    /// <summary>Number of distinct frames in one animation loop.</summary>
    public const int AnimFrames = 12;

    private void ReplaceCurrent(Bitmap bmp)
    {
        IntPtr hicon = bmp.GetHicon();
        // Clone so the Icon owns a copy and we can free the HICON immediately.
        using var temp = Icon.FromHandle(hicon);
        var clone = (Icon)temp.Clone();
        DestroyIcon(hicon);

        _current?.Dispose();
        _current = clone;
    }

    private static void DrawSpark(Graphics g, Color color, float angleDeg, float scale, bool fill)
    {
        float cx = Size / 2f, cy = Size / 2f;
        float outer = (Size / 2f - 2f) * scale;
        float inner = outer * 0.32f;

        var state = g.Save();
        g.TranslateTransform(cx, cy);
        g.RotateTransform(angleDeg);

        // Four-point sparkle with concave sides: alternate outer/inner radius
        // at 45-degree steps, then smooth via a closed path.
        using var path = new GraphicsPath();
        var pts = new PointF[8];
        for (int i = 0; i < 8; i++)
        {
            double a = Math.PI / 2 * (i / 2) + (i % 2 == 1 ? Math.PI / 4 : 0);
            float r = (i % 2 == 0) ? outer : inner;
            pts[i] = new PointF((float)(Math.Cos(a) * r), (float)(Math.Sin(a) * r));
        }
        path.AddClosedCurve(pts, 0.15f);

        using var brush = new SolidBrush(color);
        if (fill)
            g.FillPath(brush, path);
        else
        {
            using var pen = new Pen(color, 2f);
            g.DrawPath(pen, path);
        }

        g.Restore(state);
    }

    private static void DrawPermissionDot(Graphics g)
    {
        // A muted coral spark in the background so the icon still reads as
        // "Claude", with a bright yellow dot signalling "waiting on you".
        DrawSpark(g, Color.FromArgb(120, Coral), 0f, 0.9f, fill: true);

        float d = Size * 0.5f;
        var rect = new RectangleF((Size - d) / 2f, (Size - d) / 2f, d, d);
        using var brush = new SolidBrush(Permission);
        g.FillEllipse(brush, rect);
    }

    public void Dispose() => _current?.Dispose();
}
