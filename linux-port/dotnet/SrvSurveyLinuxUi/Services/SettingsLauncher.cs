using System;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace SrvSurveyLinuxUi.Services;

public static class SettingsLauncher
{
    public static string? LastError { get; private set; }
    static Process? _settingsProcess;

    public static bool IsSettingsOpen()
    {
        if (_settingsProcess is { HasExited: false })
            return true;
        if (SettingsLockFileIsLive())
            return true;
        return SettingsProcessScanIsLive();
    }

    public static bool SettingsLockFileIsLive()
    {
        foreach (var lockPath in LinuxPaths.SettingsLockPaths)
        {
            if (LockFilePidLooksLikeSettings(lockPath))
                return true;
        }

        return false;
    }

    static bool LockFilePidLooksLikeSettings(string lockPath)
    {
        try
        {
            if (!File.Exists(lockPath))
                return false;
            var text = File.ReadAllText(lockPath).Trim();
            if (string.IsNullOrWhiteSpace(text))
                return false;
            var first = text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)[0];
            if (!int.TryParse(first, out var pid) || pid <= 0)
                return false;
            return PidLooksLikeSettings(pid);
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
        catch (IndexOutOfRangeException)
        {
            return false;
        }
    }

    public static bool SettingsProcessScanIsLive()
    {
        if (string.Equals(
            Environment.GetEnvironmentVariable("SRVSURVEY_SETTINGS_SCAN"),
            "0",
            StringComparison.Ordinal))
        {
            return false;
        }

        try
        {
            foreach (var dir in Directory.EnumerateDirectories("/proc"))
            {
                var name = Path.GetFileName(dir);
                if (!int.TryParse(name, out var pid) || pid <= 0)
                    continue;
                if (PidLooksLikeSettings(pid))
                    return true;
            }
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }

        return false;
    }

    public static bool PidLooksLikeSettings(int pid)
    {
        var cmd = ReadProcCmdline(pid);
        if (string.IsNullOrEmpty(cmd))
            return false;
        if (cmd.Contains("--settings", StringComparison.Ordinal)
            || cmd.Contains("settings_ui", StringComparison.Ordinal))
        {
            return true;
        }

        return false;
    }

    static string ReadProcCmdline(int pid)
    {
        var path = $"/proc/{pid}/cmdline";
        try
        {
            if (!File.Exists(path))
                return "";
            var bytes = File.ReadAllBytes(path);
            return Encoding.UTF8.GetString(bytes).Replace('\0', ' ');
        }
        catch (IOException)
        {
            return "";
        }
        catch (UnauthorizedAccessException)
        {
            return "";
        }
    }

    public static bool TryOpenGtkSettings()
    {
        LastError = null;
        if (IsSettingsOpen())
            return true;
        var root = LinuxPaths.FindLinuxPortRoot();
        if (root == null)
        {
            LastError = "linux-port root (srvsurvey-linux) not found";
            return false;
        }

        var launcher = Path.Combine(root, "srvsurvey-linux");
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "python3",
                ArgumentList = { launcher, "--settings" },
                UseShellExecute = false,
                WorkingDirectory = root,
            };
            _settingsProcess = Process.Start(psi);
            if (_settingsProcess == null)
            {
                LastError = "Settings process did not start";
                return false;
            }

            _settingsProcess.EnableRaisingEvents = true;
            _settingsProcess.Exited += (_, _) =>
            {
                if (_settingsProcess is { HasExited: true })
                    _settingsProcess = null;
            };
            return true;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            return false;
        }
    }

    public static string RequestQuitPath =>
        Path.Combine(LinuxPaths.DataDirectory, "request-quit");

    public static void StopPresenter()
    {
        LastError = null;
        try
        {
            Directory.CreateDirectory(LinuxPaths.DataDirectory);
            File.WriteAllText(RequestQuitPath, "1\n");
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
        }

        var pid = FindLivePresenterPid();
        if (pid is not > 0)
            return;
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "kill",
                ArgumentList = { "-TERM", pid.Value.ToString() },
                UseShellExecute = false,
                RedirectStandardError = true,
            };
            using var proc = Process.Start(psi);
            proc?.WaitForExit(2000);
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
        }
    }

    static void ClearPresenterQuitRequest()
    {
        try
        {
            if (File.Exists(RequestQuitPath))
                File.Delete(RequestQuitPath);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    public static bool TrySignalOverlayToggle(int hostPid)
    {
        LastError = null;
        if (hostPid <= 0)
        {
            LastError = "Presenter host is not running";
            return false;
        }

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "kill",
                ArgumentList = { "-USR1", hostPid.ToString() },
                UseShellExecute = false,
                RedirectStandardError = true,
            };
            using var proc = Process.Start(psi);
            proc?.WaitForExit(2000);
            if (proc is { ExitCode: not 0 })
            {
                LastError = proc.StandardError.ReadToEnd().Trim();
                if (string.IsNullOrWhiteSpace(LastError))
                    LastError = $"kill -USR1 exited {proc.ExitCode}";
                return false;
            }
            return true;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            return false;
        }
    }

    static DateTime _startedUtc;

    public static bool TryStartPresenter()
    {
        LastError = null;
        if (string.Equals(
            Environment.GetEnvironmentVariable("SRVSURVEY_SKIP_PRESENT_START"),
            "1",
            StringComparison.Ordinal))
        {
            LastError = "Presenter auto-start skipped";
            return false;
        }

        if (FindLivePresenterPid() is > 0)
            return true;
        if ((DateTime.UtcNow - _startedUtc).TotalSeconds < 10)
            return true;
        ClearPresenterQuitRequest();

        var allow = AllowPresentFromConfigOrEnv();
        if (!allow)
        {
            LastError = "Present is gated (allow_present=false)";
            return false;
        }

        var root = LinuxPaths.FindLinuxPortRoot();
        if (root == null)
        {
            LastError = "linux-port root (srvsurvey-linux) not found";
            return false;
        }

        var launcher = Path.Combine(root, "srvsurvey-linux");
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "python3",
                UseShellExecute = false,
                WorkingDirectory = root,
                CreateNoWindow = true,
            };
            psi.ArgumentList.Add(launcher);
            psi.ArgumentList.Add("--present");
            Process.Start(psi);
            _startedUtc = DateTime.UtcNow;
            return true;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            return false;
        }
    }

    static bool AllowPresentFromConfigOrEnv()
    {
        if (string.Equals(
            Environment.GetEnvironmentVariable("SRVSURVEY_ALLOW_PRESENT"),
            "1",
            StringComparison.Ordinal))
        {
            return true;
        }

        var config = new AppConfigStore();
        config.Reload();
        return config.AllowPresent;
    }

    public static bool HostPidIsAlive(int pid)
    {
        var text = ReadProcCmdline(pid);
        if (string.IsNullOrEmpty(text))
            return false;
        return text.Contains("srvsurvey-linux", StringComparison.Ordinal)
            || text.Contains("host.py", StringComparison.Ordinal);
    }

    public static int? FindLivePresenterPid()
    {
        var runtime = RuntimeStateSnapshot.TryLoad();
        if (runtime?.HostPid is > 0 && HostPidIsAlive(runtime.HostPid.Value))
            return runtime.HostPid;

        try
        {
            foreach (var dir in Directory.EnumerateDirectories("/proc"))
            {
                var name = Path.GetFileName(dir);
                if (!int.TryParse(name, out var pid) || pid <= 0)
                    continue;
                if (HostPidIsAlive(pid))
                    return pid;
            }
        }
        catch (IOException)
        {
            return null;
        }

        return null;
    }
}
