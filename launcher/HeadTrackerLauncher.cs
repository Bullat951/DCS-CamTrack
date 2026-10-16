// Head Tracker.exe - starts the tracker window (pythonw, no console) from this folder's venv.
// Errors of the Python side go to logs\ui.log; a missing venv is reported in a message box.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class HeadTrackerLauncher
{
    [STAThread]
    static int Main()
    {
        string dir = Path.GetDirectoryName(Application.ExecutablePath);
        string py = Path.Combine(dir, @".venv\Scripts\pythonw.exe");
        string ui = Path.Combine(dir, @"app\ui.py");
        if (!File.Exists(py) || !File.Exists(ui))
        {
            MessageBox.Show("Head Tracker files are missing next to this program:\n" + py + "\n" + ui,
                            "Head Tracker", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        Directory.CreateDirectory(Path.Combine(dir, "logs"));
        var psi = new ProcessStartInfo(py, "\"" + ui + "\"")
        {
            WorkingDirectory = dir,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.EnvironmentVariables["HEADTRACKER_LOG"] = Path.Combine(dir, @"logs\ui.log");
        Process.Start(psi);
        return 0;
    }
}
