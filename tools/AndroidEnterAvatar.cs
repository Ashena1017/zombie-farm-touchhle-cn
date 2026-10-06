using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading;

internal static class AndroidEnterAvatar
{
    private const string AdbPath = @"C:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe";
    private const string Device = "127.0.0.1:5557";
    private const string Package = "org.touchhle.zombiefarm";

    private static int Main()
    {
        try
        {
            if (!File.Exists(AdbPath))
                throw new FileNotFoundException("找不到 MuMu 自带的 adb.exe。", AdbPath);

            RunAdb("start-server", 15000);
            RunAdb("connect " + Device, 15000);
            RunAdb("-s " + Device + " get-state", 10000);

            Console.WriteLine("正在重启 Zombie Farm...");
            RunAdb("-s " + Device + " shell am force-stop " + Package, 10000);
            RunAdb("-s " + Device + " shell am start -n " + Package + "/org.touchhle.android.MainActivity", 15000);

            Console.WriteLine("等待开始界面...");
            Thread.Sleep(8000);
            TapRelative(0.5, 0.5833);

            Console.WriteLine("等待游戏加载与欢迎页...");
            Thread.Sleep(18000);
            TapRelative(0.5, 0.7778);

            Console.WriteLine("等待选择形象页...");
            Thread.Sleep(4000);
            string state = RunAdb("-s " + Device + " shell pidof " + Package + ":game", 10000).Trim();
            if (String.IsNullOrEmpty(state))
                throw new InvalidOperationException("游戏进程已退出；请查看 MuMu 屏幕和 adb 日志。");

            Console.WriteLine("操作完成。MuMu 应已停在“选择形象”页，没有选择或确认形象。");
            WaitForKey();
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("执行失败：" + ex.Message);
            Console.Error.WriteLine("检查 MuMu 是否已启动、分辨率是否为横屏，然后按任意键退出。");
            WaitForKey();
            return 1;
        }
    }

    private static void WaitForKey()
    {
        if (!Console.IsInputRedirected)
        {
            Console.WriteLine("按任意键关闭此窗口。");
            Console.ReadKey(true);
        }
    }

    private static void TapRelative(double x, double y)
    {
        byte[] png = RunAdbBytes("-s " + Device + " exec-out screencap -p", 15000);
        int width;
        int height;
        using (MemoryStream stream = new MemoryStream(png))
        using (Bitmap bitmap = new Bitmap(stream))
        {
            width = bitmap.Width;
            height = bitmap.Height;
        }

        int tapX = (int)Math.Round(width * x);
        int tapY = (int)Math.Round(height * y);
        Console.WriteLine("点击屏幕位置 " + tapX + "," + tapY + "（截图 " + width + "x" + height + "）");
        RunAdb("-s " + Device + " shell input tap " + tapX + " " + tapY, 10000);
    }

    private static string RunAdb(string arguments, int timeoutMs)
    {
        byte[] output = RunAdbBytes(arguments, timeoutMs);
        return Encoding.UTF8.GetString(output);
    }

    private static byte[] RunAdbBytes(string arguments, int timeoutMs)
    {
        ProcessStartInfo info = new ProcessStartInfo
        {
            FileName = AdbPath,
            Arguments = arguments,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };

        using (Process process = Process.Start(info))
        using (MemoryStream output = new MemoryStream())
        {
            if (process == null)
                throw new InvalidOperationException("无法启动 adb.exe。");

            byte[] buffer = new byte[8192];
            using (Stream stream = process.StandardOutput.BaseStream)
            {
                int count;
                while ((count = stream.Read(buffer, 0, buffer.Length)) > 0)
                    output.Write(buffer, 0, count);
            }

            string error = process.StandardError.ReadToEnd();
            if (!process.WaitForExit(timeoutMs))
            {
                process.Kill();
                throw new TimeoutException("adb 命令超时：" + arguments);
            }

            if (process.ExitCode != 0)
                throw new InvalidOperationException("adb 命令失败：" + arguments + Environment.NewLine + error.Trim());

            return output.ToArray();
        }
    }
}
