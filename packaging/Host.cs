using System;
using System.IO;
using System.Diagnostics;
using System.Text;

class MediaHarbor {
    const string Origin = "chrome-extension://fgknhnjdemnejfagelfoihbdbflodjpl/";
    static int Main(string[] args) {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        bool native = args.Length > 0 && args[0] == Origin;
        if (args.Length > 0 && !native) return 2;
        var info = new ProcessStartInfo(Path.Combine(dir, native ? @"runtime\python.exe" : @"runtime\pythonw.exe"),
            "-B \"" + Path.Combine(dir, native ? "bridge.py" : "desktop.py") + "\"");
        info.WorkingDirectory = dir;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardInput = info.RedirectStandardOutput = native;
        if (!native) { Process.Start(info); return 0; }
        using (var child = Process.Start(info)) {
            try {
                using (var input = new BinaryReader(Console.OpenStandardInput())) {
                    int length = input.ReadInt32();
                    if (length < 1 || length > 900000) return 2;
                    byte[] data = input.ReadBytes(length);
                    if (data.Length != length) return 2;
                    using (var writer = new BinaryWriter(child.StandardInput.BaseStream)) {
                        writer.Write(length); writer.Write(data);
                    }
                }
                child.StandardOutput.BaseStream.CopyTo(Console.OpenStandardOutput());
                child.WaitForExit();
                return child.ExitCode;
            } finally {
                if (!child.HasExited) child.Kill();
            }
        }
    }
}

