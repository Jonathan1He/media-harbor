using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Diagnostics;
using Microsoft.Win32;
using System.Windows.Forms;
using System.Text;

class Setup {
    [STAThread] static int Main(string[] args) {
        try {
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
            bool extract = args.Length == 2 && args[0] == "--extract";
            if (args.Length != 0 && !extract) return 2;
            string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MediaHarbor");
            string target = extract ? Path.GetFullPath(args[1]) :
                Path.Combine(root, "app-" + Assembly.GetExecutingAssembly().ManifestModule.ModuleVersionId.ToString("N").Substring(0,12));
            if(!extract && MessageBox.Show("将拾流安装到当前 Windows 账户，并注册 Chrome / Edge 本机助手。继续安装？",
                "拾流 · 安装", MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK) return 0;
            string stage = Path.Combine(Path.GetDirectoryName(target),"mh-"+Guid.NewGuid().ToString("N").Substring(0,12));
            if (Directory.Exists(target) && extract) throw new IOException("解包目标目录已存在");
            if (!Directory.Exists(target)) {
                Directory.CreateDirectory(stage);
                using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("bundle"))
                using (var z = new ZipArchive(s, ZipArchiveMode.Read)) {
                    foreach (var f in z.Entries) {
                        string path = Path.GetFullPath(Path.Combine(stage,f.FullName));
                        if(!path.StartsWith(stage + Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new IOException("无效安装路径");
                        Directory.CreateDirectory(Path.GetDirectoryName(path)); f.ExtractToFile(path);
                    }
                }
                Directory.Move(stage,target);
            }
            if (extract) return 0;
            string exe = Path.Combine(target,"MediaHarbor.exe");
            string manifest = Path.Combine(target,"native-host.json");
            File.WriteAllText(manifest,"{\"name\":\"app.mediaharbor.desktop\",\"description\":\"Media Harbor\",\"path\":\""+
                exe.Replace("\\","\\\\")+"\",\"type\":\"stdio\",\"allowed_origins\":[\"chrome-extension://fgknhnjdemnejfagelfoihbdbflodjpl/\"]}",new UTF8Encoding(false));
            foreach(string vendor in new[]{"Google\\Chrome","Microsoft\\Edge"})
                using(var k=Registry.CurrentUser.CreateSubKey("Software\\"+vendor+"\\NativeMessagingHosts\\app.mediaharbor.desktop"))k.SetValue("",manifest);
            string programs=Environment.GetFolderPath(Environment.SpecialFolder.Programs);
            var shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            dynamic ws=shell;dynamic link=ws.CreateShortcut(Path.Combine(programs,"拾流.lnk"));
            link.TargetPath=exe;link.WorkingDirectory=target;link.Save();
            MessageBox.Show("安装完成。浏览器扩展管理页开启开发者模式，点击「加载已解压的扩展程序」，选择接下来打开的 extension 文件夹。","拾流");
            Process.Start("explorer.exe","\""+Path.Combine(target,"extension")+"\"");
            Process.Start(exe);
            return 0;
        } catch(Exception e) {
            if(args.Length==0)MessageBox.Show(e.Message,"安装失败");
            else Console.Error.WriteLine(e.Message);
            return 1;
        }
    }
}

