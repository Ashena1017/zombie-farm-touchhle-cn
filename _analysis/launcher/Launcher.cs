// Tiny windowless launcher for the Zombie Farm manager UI.
//
// Why this exists: 游戏管理.bat opens a console window that stays on screen the
// whole time the manager is open. A .bat cannot avoid that, because cmd.exe is a
// console program. Compiling this as /target:winexe (subsystem 2 = GUI) means no
// console is ever allocated for the launcher itself, and CreateNoWindow below
// stops PowerShell from allocating one either.
//
// It does no real work -- GameManager.ps1 is the actual implementation. This just
// starts it hidden and waits, so that closing the UI ends the process.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        // The manager script must sit next to this executable.
        string dir = Path.GetDirectoryName(Application.ExecutablePath);
        string script = Path.Combine(dir, "GameManager.ps1");

        if (!File.Exists(script))
        {
            MessageBox.Show(
                "找不到 GameManager.ps1。\r\n\r\n请确认它和本程序在同一个文件夹里：\r\n" + dir,
                "Zombie Farm 游戏管理",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            Environment.Exit(1);
            return;
        }

        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = "-NoProfile -ExecutionPolicy Bypass -STA -File \"" + script + "\"",
            WorkingDirectory = dir,
            UseShellExecute = false,
            // Together these guarantee no console window: UseShellExecute=false
            // lets CreateNoWindow take effect, and WindowStyle=Hidden covers the
            // case where a window would still be shown.
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };

        try
        {
            using (Process p = Process.Start(psi))
            {
                if (p == null)
                {
                    MessageBox.Show("无法启动 PowerShell。", "Zombie Farm 游戏管理",
                        MessageBoxButtons.OK, MessageBoxIcon.Error);
                    Environment.Exit(1);
                    return;
                }
                p.WaitForExit();
                Environment.Exit(p.ExitCode);
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show("启动失败：\r\n\r\n" + ex.Message, "Zombie Farm 游戏管理",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            Environment.Exit(1);
        }
    }
}
