using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace U2DWTray
{
    // A passive, owner-drawn card: hovering never takes keyboard focus.
    internal sealed class BatteryFlyout : Form
    {
        private readonly float scale;
        private string value = "--";
        private string voltage = "等待数据";
        private string queried = "正在读取";
        private string reason = "";
        private int? percentage;
        private static readonly Color Ink = Color.FromArgb(26, 36, 46);
        private static readonly Color Muted = Color.FromArgb(100, 111, 119);
        private static readonly Color Accent = Color.FromArgb(0, 128, 112);

        public BatteryFlyout()
        {
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            AutoScaleMode = AutoScaleMode.None;
            BackColor = Color.FromArgb(249, 251, 250);
            DoubleBuffered = true;
            using (Graphics graphics = CreateGraphics()) scale = graphics.DpiX / 96f;
            ClientSize = new Size((int)(304 * scale), (int)(222 * scale));
        }

        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams parameters = base.CreateParams;
                parameters.ExStyle |= 0x08000000 | 0x00000080; // NOACTIVATE | TOOLWINDOW
                parameters.ClassStyle |= 0x00020000; // Drop shadow
                return parameters;
            }
        }

        public void UpdateReading(int? percent, string volts, string time, string explanation)
        {
            percentage = percent;
            value = percent.HasValue ? percent.Value.ToString() : "--";
            voltage = volts;
            queried = time;
            reason = explanation;
            AccessibleName = "U2-DW · " + (percent.HasValue ? "约 " + value + "%" : explanation);
            AccessibleDescription = "电压由基站保存，采样时间未提供；无法判断充电状态。";
            Invalidate();
        }

        public void ShowNear(Point anchor)
        {
            Rectangle area = Screen.FromPoint(anchor).WorkingArea;
            int gap = (int)(14 * scale);
            int x = Math.Max(area.Left, Math.Min(anchor.X - Width / 2, area.Right - Width));
            int y = anchor.Y - Height - gap;
            if (y < area.Top) y = anchor.Y + gap;
            y = Math.Max(area.Top, Math.Min(y, area.Bottom - Height));
            Location = new Point(x, y);
            // TopMost does not activate this NOACTIVATE window.
            TopMost = true;
            Show();
        }

        private static void DrawText(Graphics canvas, string text, float size, FontStyle style,
                                     Color color, RectangleF bounds)
        {
            using (Font font = new Font("Segoe UI", size, style, GraphicsUnit.Pixel))
            using (Brush brush = new SolidBrush(color))
            using (StringFormat format = new StringFormat(StringFormat.GenericTypographic))
            {
                format.FormatFlags |= StringFormatFlags.NoWrap;
                format.Trimming = StringTrimming.EllipsisCharacter;
                canvas.DrawString(text, font, brush, bounds, format);
            }
        }

        protected override void OnPaint(PaintEventArgs args)
        {
            base.OnPaint(args);
            Graphics canvas = args.Graphics;
            canvas.ScaleTransform(scale, scale);
            canvas.SmoothingMode = SmoothingMode.AntiAlias;
            canvas.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
            Color accent = percentage.HasValue && percentage.Value <= 10 ? Color.FromArgb(191, 81, 38) : Accent;
            DrawText(canvas, "U2-DW", 15, FontStyle.Bold, Ink, new RectangleF(22, 18, 100, 23));
            DrawText(canvas, "电量估算", 12, FontStyle.Regular, Muted, new RectangleF(224, 20, 66, 22));
            DrawText(canvas, percentage.HasValue ? "约" : "", 14, FontStyle.Regular, Muted, new RectangleF(23, 75, 24, 25));
            DrawText(canvas, value, 54, FontStyle.Bold, Ink, new RectangleF(49, 44, 160, 70));
            DrawText(canvas, percentage.HasValue ? "%" : "", 22, FontStyle.Regular, Muted, new RectangleF(222, 74, 40, 30));
            using (Pen track = new Pen(Color.FromArgb(223, 231, 227), 4))
            using (Pen fill = new Pen(accent, 4))
            {
                track.StartCap = track.EndCap = fill.StartCap = fill.EndCap = LineCap.Round;
                canvas.DrawLine(track, 24, 121, 280, 121);
                if (percentage.HasValue && percentage.Value > 0)
                    canvas.DrawLine(fill, 24, 121, 24 + 256 * percentage.Value / 100f, 121);
            }
            DrawText(canvas, percentage.HasValue ? voltage : reason, 13, FontStyle.Regular,
                     percentage.HasValue ? Ink : Muted, new RectangleF(22, 138, 264, 22));
            DrawText(canvas, queried, 12, FontStyle.Regular, Muted, new RectangleF(22, 160, 264, 21));
            DrawText(canvas, "电压由基站保存，采样时间未提供", 11, FontStyle.Regular, Muted,
                     new RectangleF(22, 193, 268, 20));
            using (Pen border = new Pen(Color.FromArgb(218, 226, 222)))
                canvas.DrawRectangle(border, 0, 0, 303, 221);
        }
    }

    internal sealed class MenuColors : ProfessionalColorTable
    {
        public override Color ToolStripDropDownBackground { get { return Color.FromArgb(249, 251, 250); } }
        public override Color MenuBorder { get { return Color.FromArgb(218, 226, 222); } }
        public override Color MenuItemSelected { get { return Color.FromArgb(225, 240, 232); } }
        public override Color MenuItemBorder { get { return Color.FromArgb(225, 240, 232); } }
        public override Color SeparatorDark { get { return Color.FromArgb(226, 232, 228); } }
        public override Color SeparatorLight { get { return Color.FromArgb(249, 251, 250); } }
    }

    public sealed class TrayContext : ApplicationContext
    {
        [DllImport("user32.dll")]
        private static extern bool DestroyIcon(IntPtr icon);

        private readonly NotifyIcon tray = new NotifyIcon();
        private readonly BatteryFlyout flyout = new BatteryFlyout();
        private readonly ContextMenuStrip menu = new ContextMenuStrip();
        private readonly ToolStripMenuItem title = new ToolStripMenuItem("U2-DW 电量估算");
        private readonly ToolStripMenuItem detail = new ToolStripMenuItem();
        private readonly ToolStripMenuItem timestamp = new ToolStripMenuItem();
        private readonly ToolStripMenuItem refresh = new ToolStripMenuItem("立即刷新");
        private readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        private readonly JavaScriptSerializer json = new JavaScriptSerializer();
        private readonly string python;
        private readonly string root;
        private readonly string stateFile;
        private Process reader;
        private Task<string> output;
        private Task<string> errors;
        private Stopwatch readClock;
        private DateTime nextRead = DateTime.MinValue;
        private DateTime lastTick = DateTime.UtcNow;
        private bool closing;
        private Point hoverAnchor;
        private readonly Font menuFont = new Font("Segoe UI", 10, FontStyle.Regular);

        public TrayContext(string pythonPath, string projectRoot)
            : this(pythonPath, projectRoot, Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "U2DWTray"), true)
        {
        }

        // Internal seam for isolated acceptance fixtures; production always uses
        // the public constructor, the normal state directory and a visible icon.
        internal TrayContext(string pythonPath, string projectRoot, string stateDirectory, bool showIcon)
        {
            python = pythonPath;
            root = projectRoot;
            Directory.CreateDirectory(stateDirectory);
            stateFile = Path.Combine(stateDirectory, "status.json");
            menu.Font = menuFont;
            menu.ShowImageMargin = false;
            menu.Padding = new Padding(6);
            menu.Renderer = new ToolStripProfessionalRenderer(new MenuColors()) { RoundedEdges = false };
            title.Enabled = detail.Enabled = timestamp.Enabled = false;
            menu.Items.Add(title);
            menu.Items.Add(detail);
            menu.Items.Add(timestamp);
            menu.Items.Add(new ToolStripSeparator());
            ToolStripMenuItem note = new ToolStripMenuItem("采样时间未提供 · 无法判断充电状态");
            note.Enabled = false;
            menu.Items.Add(note);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(refresh);
            ToolStripMenuItem quit = new ToolStripMenuItem("退出");
            menu.Items.Add(quit);
            foreach (ToolStripItem item in menu.Items)
                if (!(item is ToolStripSeparator)) item.Padding = new Padding(10, 6, 10, 6);
            refresh.Click += delegate { BeginRead(); };
            quit.Click += delegate { ExitThread(); };
            tray.DoubleClick += delegate { BeginRead(); };
            tray.MouseMove += OnTrayMouseMove;
            menu.Opening += delegate { HideFlyout(); };
            tray.ContextMenuStrip = menu;
            ShowUnknown("starting", "正在读取");
            tray.Visible = showIcon;
            timer.Interval = 250;
            timer.Tick += OnTick;
            timer.Start();
            BeginRead();
        }

        private void OnTrayMouseMove(object sender, MouseEventArgs args)
        {
            if (closing || menu.Visible || flyout.Visible) return;
            hoverAnchor = Cursor.Position;
            flyout.ShowNear(hoverAnchor);
        }

        private void HideFlyout()
        {
            flyout.Hide();
        }

        private void UpdateHover()
        {
            if (!flyout.Visible) return;
            Point cursor = Cursor.Position;
            bool nearIcon = Math.Abs(cursor.X - hoverAnchor.X) <= 14 && Math.Abs(cursor.Y - hoverAnchor.Y) <= 14;
            if (menu.Visible || (!nearIcon && !flyout.Bounds.Contains(cursor))) HideFlyout();
        }

        private static string Reason(string status)
        {
            switch (status)
            {
                case "receiver_missing": return "未找到基站";
                case "disconnected_or_unknown": return "鼠标未连接或状态未知";
                case "unsupported_receiver": return "接收器固件暂不支持";
                case "unsupported_mouse": return "鼠标固件暂不支持";
                case "device_busy": return "设备正由其他诊断程序使用";
                case "calibration_error": return "校准文件缺失或无效";
                case "invalid_or_saturated_voltage":
                case "unrecognized_voltage": return "电压数据无效";
                case "timeout": return "读取超时，稍后重试";
                default: return "读取失败，稍后重试";
            }
        }

        private void BeginRead()
        {
            if (closing || reader != null) return;
            refresh.Enabled = false;
            refresh.Text = "正在刷新…";
            try
            {
                ProcessStartInfo info = new ProcessStartInfo(python);
                // The script path is an ordinary Windows file path (no quote
                // characters, no trailing slash); no shell interprets arguments.
                info.Arguments = "-B \"" + Path.Combine(root, "tray", "read_battery.py") + "\"";
                info.WorkingDirectory = root;
                info.UseShellExecute = false;
                info.CreateNoWindow = true;
                info.RedirectStandardOutput = true;
                info.RedirectStandardError = true;
                info.StandardOutputEncoding = Encoding.UTF8;
                info.StandardErrorEncoding = Encoding.UTF8;
                info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                reader = new Process();
                reader.StartInfo = info;
                reader.Start();
                output = reader.StandardOutput.ReadToEndAsync();
                errors = reader.StandardError.ReadToEndAsync();
                readClock = Stopwatch.StartNew();
            }
            catch
            {
                StopReader();
                ShowUnknown("read_error", "无法启动读取程序");
                ScheduleNext();
            }
        }

        private void OnTick(object sender, EventArgs args)
        {
            if (closing) return;
            try
            {
                UpdateHover();
                DateTime now = DateTime.UtcNow;
                bool resumed = (now - lastTick).TotalSeconds > 10;
                lastTick = now;
                if (resumed)
                {
                    HideFlyout();
                    StopReader();
                    ShowUnknown("resuming", "恢复后重新读取");
                    nextRead = DateTime.MinValue;
                }
                if (reader != null)
                {
                    if (reader.HasExited && output.IsCompleted && errors.IsCompleted)
                    {
                        if (reader.ExitCode != 0) throw new InvalidDataException();
                        string response = output.GetAwaiter().GetResult();
                        StopReader();
                        ApplyReading(json.Deserialize<Dictionary<string, object>>(response));
                        ScheduleNext();
                    }
                    else if (readClock.Elapsed.TotalSeconds >= 25)
                    {
                        StopReader();
                        ShowUnknown("timeout", Reason("timeout"));
                        ScheduleNext();
                    }
                }
                if (reader == null && now >= nextRead) BeginRead();
            }
            catch
            {
                StopReader();
                ShowUnknown("read_error", Reason("read_error"));
                ScheduleNext();
            }
        }

        private void ScheduleNext()
        {
            nextRead = DateTime.UtcNow.AddSeconds(30);
            refresh.Enabled = true;
            refresh.Text = "立即刷新";
        }

        private void ApplyReading(Dictionary<string, object> data)
        {
            string status = Convert.ToString(data["status"]);
            if (status != "cached_voltage_only" || data["estimated_percentage"] == null)
            {
                ShowUnknown(status, Reason(status));
                return;
            }
            int percent = Convert.ToInt32(data["estimated_percentage"]);
            double volts = Convert.ToDouble(data["inferred_volts"]);
            if (percent < 0 || percent > 100 || Double.IsNaN(volts) || Double.IsInfinity(volts)
                || volts <= 3 || volts >= 5)
                throw new InvalidDataException();
            DateTime queried = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)
                .AddSeconds(Convert.ToDouble(data["snapshot_time"])).ToLocalTime();
            string label = "约 " + percent + "%";
            title.Text = "U2-DW · " + label;
            detail.Text = "缓存电压：" + volts.ToString("F2") + " V";
            timestamp.Text = "查询时间：" + queried.ToString("HH:mm:ss");
            // Suppress the legacy system tooltip; the passive card provides details.
            tray.Text = "";
            flyout.UpdateReading(percent, "基站电压  " + volts.ToString("F2") + " V",
                                 "查询于 " + queried.ToString("HH:mm:ss") + " · 自动刷新", "");
            SetIcon(percent.ToString(), percent <= 10 ? Color.OrangeRed : Color.FromArgb(67, 198, 167));
            SaveState(status, label, percent, volts, queried);
        }

        private void ShowUnknown(string status, string reason)
        {
            title.Text = "U2-DW · --";
            detail.Text = reason;
            timestamp.Text = "检查时间：" + DateTime.Now.ToString("HH:mm:ss");
            tray.Text = "";
            flyout.UpdateReading(null, "", "检查于 " + DateTime.Now.ToString("HH:mm:ss"), reason);
            SetIcon("--", Color.Gray);
            SaveState(status, reason, null, null, DateTime.Now);
        }

        private void SetIcon(string text, Color accent)
        {
            using (Bitmap bitmap = new Bitmap(32, 32))
            using (Graphics canvas = Graphics.FromImage(bitmap))
            using (SolidBrush background = new SolidBrush(Color.FromArgb(28, 34, 43)))
            using (SolidBrush foreground = new SolidBrush(text == "--" ? Color.Silver : Color.White))
            using (SolidBrush bar = new SolidBrush(accent))
            using (GraphicsPath tile = new GraphicsPath())
            using (GraphicsPath digits = new GraphicsPath())
            using (StringFormat format = new StringFormat(StringFormat.GenericTypographic))
            using (FontFamily family = new FontFamily("Segoe UI"))
            {
                canvas.SmoothingMode = SmoothingMode.AntiAlias;
                canvas.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                canvas.Clear(Color.Transparent);
                tile.AddArc(0, 0, 10, 10, 180, 90);
                tile.AddArc(22, 0, 10, 10, 270, 90);
                tile.AddArc(22, 22, 10, 10, 0, 90);
                tile.AddArc(0, 22, 10, 10, 90, 90);
                tile.CloseFigure();
                canvas.FillPath(background, tile);
                // Outline the whole string once, then fit its actual bounds.
                // Layout rectangles can wrap "70" and silently clip the second digit.
                format.FormatFlags |= StringFormatFlags.NoWrap;
                digits.AddString(text, family, (int)FontStyle.Bold, 32, PointF.Empty, format);
                RectangleF bounds = digits.GetBounds();
                float fit = Math.Min(28f / bounds.Width, 23f / bounds.Height);
                float x = (32 - bounds.Width * fit) / 2 - bounds.X * fit;
                float y = (28 - bounds.Height * fit) / 2 - bounds.Y * fit;
                using (Matrix transform = new Matrix(fit, 0, 0, fit, x, y)) digits.Transform(transform);
                canvas.FillPath(foreground, digits);
                canvas.FillRectangle(bar, 8, 28, 16, 2);
                IntPtr handle = bitmap.GetHicon();
                Icon replacement;
                try
                {
                    using (Icon borrowed = Icon.FromHandle(handle))
                        replacement = (Icon)borrowed.Clone();
                }
                finally { DestroyIcon(handle); }
                Icon old = tray.Icon;
                tray.Icon = replacement;
                if (old != null) old.Dispose();
            }
        }

        private void SaveState(string status, string label, int? percent, double? volts, DateTime time)
        {
            // Keep only the latest display state, never raw input or device paths.
            try
            {
                var state = new Dictionary<string, object>();
                state.Add("status", status);
                state.Add("label", label);
                state.Add("estimated_percentage", percent);
                state.Add("cached_voltage", volts);
                state.Add("query_time", time.ToString("o"));
                state.Add("cache_age_known", false);
                state.Add("pid", Process.GetCurrentProcess().Id);
                string temporary = stateFile + ".tmp";
                File.WriteAllText(temporary, json.Serialize(state), new UTF8Encoding(false));
                if (File.Exists(stateFile)) File.Replace(temporary, stateFile, null);
                else File.Move(temporary, stateFile);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }

        private void StopReader()
        {
            if (reader == null) return;
            try
            {
                if (!reader.HasExited)
                {
                    reader.Kill();
                    reader.WaitForExit(1000);
                }
            }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
            finally
            {
                reader.Dispose();
                reader = null;
                output = errors = null;
            }
        }

        protected override void ExitThreadCore()
        {
            closing = true;
            timer.Stop();
            HideFlyout();
            StopReader();
            SaveState("stopped", "已退出", null, null, DateTime.Now);
            tray.Visible = false;
            base.ExitThreadCore();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                closing = true;
                timer.Dispose();
                StopReader();
                Icon old = tray.Icon;
                tray.Dispose();
                if (old != null) old.Dispose();
                menu.Dispose();
                flyout.Dispose();
                menuFont.Dispose();
            }
            base.Dispose(disposing);
        }
    }

    public static class App
    {
        public static void Run(string pythonPath, string projectRoot)
        {
            using (Mutex instance = new Mutex(false, @"Local\ZowieU2DW.Tray.v1"))
            {
                bool owned;
                try { owned = instance.WaitOne(0); }
                catch (AbandonedMutexException) { owned = true; }
                if (!owned) return;
                try
                {
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);
                    using (TrayContext context = new TrayContext(pythonPath, projectRoot))
                        Application.Run(context);
                }
                finally { instance.ReleaseMutex(); }
            }
        }
    }
}
