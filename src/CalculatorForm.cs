using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.Runtime.InteropServices;

namespace ClaudeStatusBar;

/// <summary>
/// A slim calculator bar that pops up beside the tray and stretches to the left
/// along the taskbar, so it reads as expanding out of the status bar. There are
/// no buttons: the user types an expression (e.g. "12 + 30 * 2") and the result
/// updates live, grouped with thousands separators. Enter copies the result to
/// the clipboard. It auto-hides when it loses focus and is reused for the app's
/// lifetime rather than recreated.
/// </summary>
internal sealed class CalculatorForm : Form
{
    // Claude coral, matching IconRenderer.
    private static readonly Color Coral = Color.FromArgb(0xCC, 0x78, 0x5C);
    private static readonly Color PanelBg = Color.FromArgb(0x1E, 0x1E, 0x1E);
    private static readonly Color TextFg = Color.FromArgb(0xF2, 0xF2, 0xF2);
    private static readonly Color Muted = Color.FromArgb(0x8A, 0x8A, 0x8A);

    private const int CornerRadius = 16;
    private const int ResultCol = 220;    // px reserved for the result
    private const float BaseResultSize = 17f;

    // DWM: prefer natively-rounded corners on Windows 11 (smoother than the region).
    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);
    private const int DWMWA_WINDOW_CORNER_PREFERENCE = 33;
    private const int DWMWCP_ROUND = 2;

    private readonly TextBox _input = new();
    private readonly Label _sep = new();
    private readonly Label _result = new();
    private readonly System.Windows.Forms.Timer _flash = new();

    public CalculatorForm()
    {
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false;
        TopMost = true;
        KeyPreview = true;
        BackColor = PanelBg;
        Padding = new Padding(1); // room for the accent border drawn in OnPaint
        ClientSize = new Size(500, 54);

        BuildUi();

        // Briefly turn the "=" into a check when a result is copied.
        _flash.Interval = 900;
        _flash.Tick += (_, _) => { _flash.Stop(); _sep.Text = "="; _sep.ForeColor = Muted; };
    }

    private void BuildUi()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 3,
            RowCount = 1,
            BackColor = PanelBg,
            Padding = new Padding(18, 0, 18, 0),
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));       // input (fills)
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 26));       // "="
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, ResultCol)); // result

        _input.BorderStyle = BorderStyle.None;
        _input.BackColor = PanelBg;
        _input.ForeColor = TextFg;
        _input.Font = new Font("Segoe UI", 16f);
        _input.PlaceholderText = "Type a calculation…";
        _input.Anchor = AnchorStyles.Left | AnchorStyles.Right; // vertically centered in the row
        _input.TextChanged += (_, _) => Recompute();

        _sep.Text = "=";
        _sep.ForeColor = Muted;
        _sep.Font = new Font("Segoe UI", 15f);
        _sep.TextAlign = ContentAlignment.MiddleCenter;
        _sep.Dock = DockStyle.Fill;

        _result.ForeColor = Coral;
        _result.Font = new Font("Segoe UI", BaseResultSize, FontStyle.Bold);
        _result.TextAlign = ContentAlignment.MiddleRight;
        _result.Dock = DockStyle.Fill;
        _result.AutoEllipsis = false; // we shrink the font instead of clipping to "…"

        root.Controls.Add(_input, 0, 0);
        root.Controls.Add(_sep, 1, 0);
        root.Controls.Add(_result, 2, 0);
        Controls.Add(root);
    }

    private void Recompute()
    {
        SetResult(ExpressionEvaluator.TryEvaluate(_input.Text, out double v) ? Format(v) : "");
    }

    /// <summary>
    /// Sets the result text and shrinks its font as needed so long numbers stay
    /// fully visible within the reserved column rather than being truncated.
    /// </summary>
    private void SetResult(string text)
    {
        int avail = ResultCol - 8;
        float size = BaseResultSize;
        Font font = new("Segoe UI", size, FontStyle.Bold);
        while (size > 9f &&
               TextRenderer.MeasureText(text, font).Width > avail)
        {
            font.Dispose();
            size -= 1f;
            font = new Font("Segoe UI", size, FontStyle.Bold);
        }

        Font old = _result.Font;
        _result.Text = text;
        _result.Font = font;
        old.Dispose();
    }

    private static string Format(double v)
    {
        // Group with thousands separators; trim trailing zeros; cap precision.
        string s = v.ToString("#,##0.##########", CultureInfo.InvariantCulture);
        return s == "-0" ? "0" : s;
    }

    // ---- Flyout behaviour ----

    /// <summary>Show the bar if hidden, hide it if already showing.</summary>
    public void Toggle()
    {
        if (Visible) Hide();
        else ShowFlyout();
    }

    private void ShowFlyout()
    {
        PositionNearTray();
        Show();
        Activate();
        BringToFront();
        _input.Focus();
        _input.SelectAll(); // typing replaces the previous expression
    }

    private void PositionNearTray()
    {
        Rectangle wa = (Screen.PrimaryScreen ?? Screen.AllScreens[0]).WorkingArea;
        const int margin = 12;
        // Right edge sits by the tray; the bar stretches to the LEFT along the taskbar.
        Location = new Point(wa.Right - Width - margin, wa.Bottom - Height - margin);
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        int pref = DWMWCP_ROUND;
        try { DwmSetWindowAttribute(Handle, DWMWA_WINDOW_CORNER_PREFERENCE, ref pref, sizeof(int)); }
        catch { /* pre-Win11: fall back to the region set in OnSizeChanged */ }
        ApplyRoundedRegion();
    }

    protected override void OnSizeChanged(EventArgs e)
    {
        base.OnSizeChanged(e);
        ApplyRoundedRegion();
    }

    private void ApplyRoundedRegion()
    {
        var path = RoundedRect(new Rectangle(0, 0, Width, Height), CornerRadius);
        Region?.Dispose();
        Region = new Region(path);
        path.Dispose();
    }

    private static GraphicsPath RoundedRect(Rectangle r, int radius)
    {
        int d = radius * 2;
        var p = new GraphicsPath();
        p.AddArc(r.X, r.Y, d, d, 180, 90);
        p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
        p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
        p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
        p.CloseFigure();
        return p;
    }

    protected override void OnDeactivate(EventArgs e)
    {
        base.OnDeactivate(e);
        Hide(); // behave like a flyout: dismiss when focus moves elsewhere
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        // Keep the single instance alive; just hide on Alt+F4 / close requests.
        if (e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true;
            Hide();
            return;
        }
        base.OnFormClosing(e);
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Escape)
        {
            Hide();
            e.Handled = e.SuppressKeyPress = true;
        }
        else if (e.KeyCode == Keys.Enter)
        {
            CopyResult();
            e.Handled = e.SuppressKeyPress = true; // no error ding on a single-line box
        }
        else
        {
            base.OnKeyDown(e);
        }
    }

    private void CopyResult()
    {
        if (string.IsNullOrEmpty(_result.Text)) return;
        try { Clipboard.SetText(_result.Text); } catch { /* clipboard busy — ignore */ }

        _sep.Text = "✓";
        _sep.ForeColor = Coral;
        _flash.Stop();
        _flash.Start();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        // Subtle coral hairline border, rounded to match the window corners.
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var path = RoundedRect(new Rectangle(0, 0, Width - 1, Height - 1), CornerRadius - 1);
        using var pen = new Pen(Color.FromArgb(110, Coral), 1f);
        e.Graphics.DrawPath(pen, path);
    }
}
