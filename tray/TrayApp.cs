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
    public sealed class TrayContext : ApplicationContext
    {
        [DllImport("user32.dll")]
        private static extern bool DestroyIcon(IntPtr icon);

        private readonly NotifyIcon tray = new NotifyIcon();
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
            title.Enabled = detail.Enabled = timestamp.Enabled = false;
            menu.Items.Add(title);
            menu.Items.Add(detail);
            menu.Items.Add(timestamp);
            menu.Items.Add(new ToolStripSeparator());
            ToolStripMenuItem note = new ToolStripMenuItem("电压估算 · 缓存年龄及充电状态未知");
            note.Enabled = false;
            menu.Items.Add(note);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(refresh);
            ToolStripMenuItem quit = new ToolStripMenuItem("退出");
            menu.Items.Add(quit);
            refresh.Click += delegate { BeginRead(); };
            quit.Click += delegate { ExitThread(); };
            tray.DoubleClick += delegate { BeginRead(); };
            tray.ContextMenuStrip = menu;
            ShowUnknown("starting", "正在读取");
            tray.Visible = showIcon;
            timer.Interval = 250;
            timer.Tick += OnTick;
            timer.Start();
            BeginRead();
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
                DateTime now = DateTime.UtcNow;
                bool resumed = (now - lastTick).TotalSeconds > 10;
                lastTick = now;
                if (resumed)
                {
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
            tray.Text = "U2-DW " + label + " | " + volts.ToString("F2") + " V\n查询 "
                + queried.ToString("HH:mm:ss") + " · 缓存年龄未知";
            SetIcon(percent.ToString(), percent <= 10 ? Color.OrangeRed : Color.Turquoise);
            SaveState(status, label, percent, volts, queried);
        }

        private void ShowUnknown(string status, string reason)
        {
            title.Text = "U2-DW · --";
            detail.Text = reason;
            timestamp.Text = "检查时间：" + DateTime.Now.ToString("HH:mm:ss");
            tray.Text = "U2-DW · " + reason;
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
            using (Font font = new Font("Segoe UI", text.Length == 3 ? 18 : 23,
                                       FontStyle.Bold, GraphicsUnit.Pixel))
            using (StringFormat format = new StringFormat())
            {
                canvas.SmoothingMode = SmoothingMode.AntiAlias;
                canvas.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                canvas.Clear(Color.Transparent);
                canvas.FillRectangle(background, 0, 1, 32, 29);
                format.Alignment = StringAlignment.Center;
                format.LineAlignment = StringAlignment.Center;
                canvas.DrawString(text, font, foreground, new RectangleF(-1, -1, 34, 29), format);
                canvas.FillRectangle(bar, 3, 28, 26, 3);
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
