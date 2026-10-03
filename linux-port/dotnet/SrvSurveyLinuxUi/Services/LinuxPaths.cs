using System;
using System.IO;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

/// <summary>XDG paths matching linux-port/runtime/paths.py and config.py.</summary>
public static class LinuxPaths
{
    public static string HomeDirectory
    {
        get
        {
            var home = Environment.GetEnvironmentVariable("HOME");
            if (!string.IsNullOrWhiteSpace(home))
                return home;
            return Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        }
    }

    public static string[] SettingsLockPaths
    {
        get
        {
            var names = new System.Collections.Generic.HashSet<string>(StringComparer.Ordinal);
            void add(string folder)
            {
                if (!string.IsNullOrWhiteSpace(folder))
                    names.Add(Path.Combine(folder, "settings.lock"));
            }

            add(ConfigDirectory);
            add(DataDirectory);
            foreach (var root in HomeRoots())
            {
                add(Path.Combine(root, ".config", "srvsurvey"));
                add(Path.Combine(root, ".local", "share", "srvsurvey"));
            }

            var xdgConfig = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");
            if (!string.IsNullOrWhiteSpace(xdgConfig))
                add(Path.Combine(xdgConfig, "srvsurvey"));
            var xdgData = Environment.GetEnvironmentVariable("XDG_DATA_HOME");
            if (!string.IsNullOrWhiteSpace(xdgData))
                add(Path.Combine(xdgData, "srvsurvey"));

            var list = new string[names.Count];
            names.CopyTo(list);
            return list;
        }
    }

    public static System.Collections.Generic.IEnumerable<string> HomeRoots()
    {
        var homes = new System.Collections.Generic.HashSet<string>(StringComparer.Ordinal);
        void add(string? path)
        {
            if (string.IsNullOrWhiteSpace(path))
                return;
            try
            {
                homes.Add(Path.GetFullPath(path));
            }
            catch (Exception)
            {
                homes.Add(path);
            }
        }

        add(Environment.GetEnvironmentVariable("HOME"));
        add(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile));
        var snapshot = new string[homes.Count];
        homes.CopyTo(snapshot);
        foreach (var home in snapshot)
        {
            var name = Path.GetFileName(home.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
            if (string.IsNullOrWhiteSpace(name))
                continue;
            if (home.StartsWith("/home/", StringComparison.Ordinal) && !home.StartsWith("/var/home/", StringComparison.Ordinal))
                add(Path.Combine("/var/home", name));
            if (home.StartsWith("/var/home/", StringComparison.Ordinal))
                add(Path.Combine("/home", name));
        }

        return homes;
    }

    public static string ConfigDirectory
    {
        get
        {
            var xdg = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");
            var root = string.IsNullOrWhiteSpace(xdg)
                ? Path.Combine(HomeDirectory, ".config")
                : xdg;
            return Path.Combine(root, "srvsurvey");
        }
    }

    public static string DataDirectory
    {
        get
        {
            var xdg = Environment.GetEnvironmentVariable("XDG_DATA_HOME");
            var root = string.IsNullOrWhiteSpace(xdg)
                ? Path.Combine(HomeDirectory, ".local", "share")
                : xdg;
            return Path.Combine(root, "srvsurvey");
        }
    }

    public static string PrimaryConfigPath => Path.Combine(ConfigDirectory, "config");

    public static string RuntimeStatePath => Path.Combine(DataDirectory, "runtime-state.json");

    public static string? FindLinuxPortRoot()
    {
        var env = Environment.GetEnvironmentVariable("SRVSURVEY_LINUX_ROOT");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(Path.Combine(env, "srvsurvey-linux")))
            return env;

        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (var i = 0; i < 8 && dir != null; i++, dir = dir.Parent)
        {
            var candidate = Path.Combine(dir.FullName, "srvsurvey-linux");
            if (File.Exists(candidate))
                return dir.FullName;
            var nested = Path.Combine(dir.FullName, "linux-port", "srvsurvey-linux");
            if (File.Exists(nested))
                return Path.Combine(dir.FullName, "linux-port");
        }

        return null;
    }
}

public sealed class RuntimeStateSnapshot
{
    public string? Updated { get; init; }
    public string? JournalFolder { get; init; }
    public string? JournalFile { get; init; }
    public int? HostPid { get; init; }
    public bool? PresentActive { get; init; }
    public string? Commander { get; init; }
    public string? System { get; init; }
    public string? Body { get; init; }
    public string? Mode { get; init; }
    public string? Vehicle { get; init; }
    public bool? OverlayVisible { get; init; }

    public static RuntimeStateSnapshot? TryLoad(string? path = null)
    {
        var file = path ?? LinuxPaths.RuntimeStatePath;
        if (!File.Exists(file))
            return null;
        try
        {
            using var stream = File.OpenRead(file);
            using var doc = JsonDocument.Parse(stream);
            var root = doc.RootElement;
            return new RuntimeStateSnapshot
            {
                Updated = GetString(root, "updated"),
                JournalFolder = GetString(root, "journal_folder"),
                JournalFile = GetString(root, "journal_file"),
                HostPid = GetInt(root, "host_pid"),
                PresentActive = GetBool(root, "present_active"),
                Commander = GetString(root, "commander"),
                System = GetString(root, "system"),
                Body = GetString(root, "body"),
                Mode = GetString(root, "mode"),
                Vehicle = GetString(root, "vehicle"),
                OverlayVisible = GetBool(root, "overlay_visible"),
            };
        }
        catch
        {
            return null;
        }
    }

    static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;

    static int? GetInt(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el))
            return null;
        if (el.ValueKind == JsonValueKind.Number && el.TryGetInt32(out var n))
            return n;
        if (el.ValueKind == JsonValueKind.Null)
            return null;
        return null;
    }

    static bool? GetBool(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el))
            return null;
        return el.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => null,
        };
    }
}
