using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace U2DWTray
{
    public static class Acceptance
    {
        [DllImport("user32.dll")]
        private static extern int GetGuiResources(IntPtr process, int flags);
        private static readonly BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        private static readonly List<object> Results = new List<object>();
        private static string root;
        private static string report;
        private static TrayContext context;
        private static Dictionary<string, object> measurements;

        private static object Field(string name) { return typeof(TrayContext).GetField(name, Private).GetValue(context); }
        private static void SetField(string name, object value) { typeof(TrayContext).GetField(name, Private).SetValue(context, value); }
        private static object Call(string name, params object[] args) { return typeof(TrayContext).GetMethod(name, Private).Invoke(context, args); }
        private static void Require(bool condition, string detail) { if (!condition) throw new Exception(detail); }
        private static void PumpUntil(Func<bool> done, int seconds)
        {
            Stopwatch clock = Stopwatch.StartNew();
            while (!done())
            {
                Application.DoEvents();
                if (clock.Elapsed.TotalSeconds > seconds) throw new Exception("Wait exceeded " + seconds + " seconds");
                Thread.Sleep(10);
            }
        }
        private static void Fixture(string value) { File.WriteAllText(Path.Combine(root, "fixture.json"), value); }
        private static Dictionary<string, object> State()
        {
            return Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(root, "state", "status.json")));
        }
        private static void Read(string fixture)
        {
            Fixture(fixture);
            ((ToolStripMenuItem)Field("refresh")).PerformClick();
            PumpUntil(delegate { return Field("reader") == null; }, 8);
        }
        private static void Check(string name, Action test)
        {
            measurements = new Dictionary<string, object>();
            try { test(); Results.Add(new { name = name, passed = true, measurements = measurements }); }
            catch (Exception error)
            {
                Results.Add(new { name = name, passed = false, error = error.GetBaseException().ToString() });
                Call("StopReader");
                Call("ScheduleNext");
            }
            File.WriteAllText(report, Json.Serialize(Results));
        }

        public static void Run(string python, string project, string destination)
        {
            root = Path.Combine(destination, "isolated-tray");
            report = Path.Combine(destination, "tray-components.json");
            Directory.CreateDirectory(Path.Combine(root,"tray"));
            File.Copy(Path.Combine(project,"tests","fake_reader.py"), Path.Combine(root,"tray","read_battery.py"), true);
            Fixture("{}");
            Application.EnableVisualStyles();
            using (context = new TrayContext(python, root, Path.Combine(root,"state"), false))
            {
                Check("startup_success_and_estimate_semantics", delegate {
                    PumpUntil(delegate { return Field("reader") == null; }, 8);
                    Require(Convert.ToInt32(State()["estimated_percentage"]) == 85, "Expected 85");
                    NotifyIcon icon = (NotifyIcon)Field("tray");
                    Require(icon.Text.Contains("约 85%") && icon.Text.Contains("缓存年龄未知"), "Tooltip semantics");
                    Require(icon.Icon != null, "Icon missing");
                });
                Check("manual_refresh_updates_time", delegate {
                    string before = Convert.ToString(State()["query_time"]);
                    Read("{}");
                    Require(Convert.ToString(State()["query_time"]) != before, "No timestamp update");
                });
                Check("periodic_refresh_uses_30_second_interval", delegate {
                    double seconds = (((DateTime)Field("nextRead"))-DateTime.UtcNow).TotalSeconds;
                    Require(seconds > 28 && seconds <= 30, "Incorrect interval");
                    SetField("nextRead", DateTime.UtcNow.AddSeconds(-1));
                    Call("OnTick", null, EventArgs.Empty);
                    Require(Field("reader") != null, "Timer did not start reader");
                    PumpUntil(delegate { return Field("reader") == null; }, 8);
                });
                Check("refreshes_do_not_overlap", delegate {
                    Fixture("{\"delay\":1}");
                    Call("BeginRead");
                    int pid = ((Process)Field("reader")).Id;
                    for (int i=0; i<30; i++) Call("BeginRead");
                    Require(((Process)Field("reader")).Id == pid, "Overlapping process");
                    Require(!((ToolStripMenuItem)Field("refresh")).Enabled, "Refresh not disabled");
                    PumpUntil(delegate { return Field("reader") == null; }, 8);
                });
                Check("all_unknown_states_hide_previous_value", delegate {
                    foreach (string status in new [] {"receiver_missing","disconnected_or_unknown","unsupported_receiver","unsupported_mouse","device_busy","calibration_error","invalid_or_saturated_voltage","unrecognized_voltage"})
                    {
                        Read("{\"response\":{\"status\":\""+status+"\",\"estimated_percentage\":null}}");
                        Require(State()["estimated_percentage"] == null && State()["cached_voltage"] == null, "Stale values for " + status);
                        Require(((ToolStripMenuItem)Field("title")).Text.Contains("--"), "Missing unknown label");
                    }
                });
                Check("malformed_output_clears_state_and_recovers", delegate {
                    Read("{\"malformed\":true}");
                    Require(Convert.ToString(State()["status"]) == "read_error", "Malformed accepted");
                    Read("{}");
                    Require(Convert.ToString(State()["status"]) == "cached_voltage_only", "No recovery");
                });
                Check("nonzero_child_exit_is_failure", delegate {
                    Read("{\"exit_code\":1}");
                    Require(Convert.ToString(State()["status"]) == "read_error", "Exit code ignored");
                });
                Check("stderr_is_drained_without_deadlock", delegate {
                    Read("{\"stderr_bytes\":200000}");
                    Require(Convert.ToString(State()["status"]) == "cached_voltage_only", "Pipe blocked");
                });
                Check("resume_gap_invalidates_display_and_requeries", delegate {
                    Fixture("{\"delay\":1}");
                    SetField("lastTick",DateTime.UtcNow.AddSeconds(-11));
                    Call("OnTick",null,EventArgs.Empty);
                    Require(Convert.ToString(State()["status"]) == "resuming", "Stale display on resume");
                    PumpUntil(delegate { return Field("reader") == null; }, 8);
                    Require(Convert.ToString(State()["status"]) == "cached_voltage_only", "Resume failed");
                });
                Check("icon_replacement_does_not_leak_GDI_handles", delegate {
                    int before = GetGuiResources(Process.GetCurrentProcess().Handle, 0);
                    for (int i=0; i<2000; i++) Call("SetIcon",(i%101).ToString(),System.Drawing.Color.Turquoise);
                    int after = GetGuiResources(Process.GetCurrentProcess().Handle, 0);
                    measurements.Add("replacements", 2000);
                    measurements.Add("gdi_before", before);
                    measurements.Add("gdi_after", after);
                    Require(after-before <= 3, "GDI grew by " + (after-before));
                });
                Check("invalid_infinite_voltage_rejected", delegate {
                    var input = new Dictionary<string,object>();
                    input.Add("status","cached_voltage_only"); input.Add("estimated_percentage",85);
                    input.Add("inferred_volts",Double.PositiveInfinity); input.Add("snapshot_time",0);
                    bool rejected = false;
                    try { Call("ApplyReading", input); } catch (TargetInvocationException) { rejected = true; }
                    Require(rejected,"Infinite voltage accepted");
                });
                Check("25_second_timeout_terminates_child_and_recovers", delegate {
                    Fixture("{\"delay\":60}");
                    Call("BeginRead");
                    int pid = ((Process)Field("reader")).Id;
                    Stopwatch timeoutClock = Stopwatch.StartNew();
                    PumpUntil(delegate { return Field("reader") == null; }, 30);
                    measurements.Add("elapsed_seconds", timeoutClock.Elapsed.TotalSeconds);
                    Require(Convert.ToString(State()["status"]) == "timeout", "Missing timeout status");
                    bool gone = false;
                    try { gone = Process.GetProcessById(pid).HasExited; } catch (ArgumentException) { gone = true; }
                    Require(gone, "Reader survived timeout");
                    Read("{}");
                    Require(Convert.ToString(State()["status"]) == "cached_voltage_only", "Failed to recover");
                });
                Check("quit_click_stops_loop_child_and_icon", delegate {
                    Fixture("{\"delay\":60}");
                    Call("BeginRead");
                    int pid = ((Process)Field("reader")).Id;
                    var menu = (ContextMenuStrip)Field("menu");
                    var trigger = new System.Windows.Forms.Timer();
                    trigger.Interval = 100;
                    trigger.Tick += delegate { trigger.Stop(); ((ToolStripMenuItem)menu.Items[menu.Items.Count-1]).PerformClick(); };
                    trigger.Start();
                    Stopwatch elapsed = Stopwatch.StartNew();
                    Application.Run(context);
                    trigger.Dispose();
                    measurements.Add("exit_seconds", elapsed.Elapsed.TotalSeconds);
                    Require(elapsed.Elapsed.TotalSeconds < 5,"Message loop failed to exit");
                    Require(Convert.ToString(State()["status"]) == "stopped", "Missing stopped state");
                    Require(!((NotifyIcon)Field("tray")).Visible, "Icon remains visible");
                    Require(!((System.Windows.Forms.Timer)Field("timer")).Enabled,"Timer still enabled");
                    bool gone = false;
                    try { gone = Process.GetProcessById(pid).HasExited; } catch (ArgumentException) { gone = true; }
                    Require(gone, "Reader survived quit");
                });
            }
        }
    }
}
