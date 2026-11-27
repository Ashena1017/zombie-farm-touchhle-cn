using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;

// Drain both pipes even if the disk fills or the log is locked.
public sealed class ZfGameOutput {
    const int Limit = 1024 * 1024;
    readonly object gate = new object();
    readonly string path;
    readonly StringBuilder errorTail = new StringBuilder();
    FileStream log;
    readonly Task finished;

    public ZfGameOutput(Process process, string directory) {
        path = Path.Combine(directory, "zfr_last_run.log");
        try {
            // Retain a bounded tail even when upgrading from the unbounded logger.
            if (File.Exists(path)) {
                using (var old = File.OpenRead(path))
                using (var previous = File.Create(path + ".previous")) {
                    old.Position = Math.Max(0L, old.Length - Limit);
                    old.CopyTo(previous);
                }
            }
            File.Delete(path + ".1");
            log = OpenLog();
        } catch (IOException) {} catch (UnauthorizedAccessException) {}
        finished = Task.WhenAll(Drain(process.StandardOutput, false), Drain(process.StandardError, true));
    }

    FileStream OpenLog() {
        return new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.Read | FileShare.Delete);
    }

    async Task Drain(StreamReader reader, bool stderr) {
        var chars = new char[4096];
        var encoder = Encoding.UTF8.GetEncoder();
        var bytes = new byte[Encoding.UTF8.GetMaxByteCount(chars.Length)];
        int n;
        while ((n = await reader.ReadAsync(chars, 0, chars.Length).ConfigureAwait(false)) != 0) {
            int count = encoder.GetBytes(chars, 0, n, bytes, 0, false);
            lock (gate) {
                if (stderr) {
                    errorTail.Append(chars, 0, n);
                    if (errorTail.Length > 16384) errorTail.Remove(0, errorTail.Length - 16384);
                }
                if (log == null) continue;
                try {
                    if (log.Length + count > Limit) {
                        log.Dispose();
                        File.Delete(path + ".1");
                        File.Move(path, path + ".1");
                        log = OpenLog();
                    }
                    log.Write(bytes, 0, count);
                    log.Flush();
                } catch (IOException) { CloseLog(); }
                  catch (UnauthorizedAccessException) { CloseLog(); }
            }
        }
    }

    void CloseLog() {
        if (log == null) return;
        try { log.Dispose(); } catch (IOException) {}
        log = null;
    }

    public string Finish() {
        try { finished.GetAwaiter().GetResult(); }
        finally { CloseLog(); }
        return errorTail.ToString();
    }
}
