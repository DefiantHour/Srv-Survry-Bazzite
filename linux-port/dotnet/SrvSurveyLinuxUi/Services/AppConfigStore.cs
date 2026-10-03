using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// Read/write ~/.config/srvsurvey/config without wiping gs.* / panel.* keys.
/// </summary>
public sealed class AppConfigStore
{
    readonly string _path;
    readonly Dictionary<string, string> _values = new(StringComparer.Ordinal);

    public AppConfigStore(string? path = null)
    {
        _path = path ?? LinuxPaths.PrimaryConfigPath;
    }

    public string Path => _path;

    public bool AllowPresent { get; private set; }
    public bool OverlayVisible { get; private set; } = true;
    public bool BuildProjectsSuppressOtherOverlays { get; private set; }
    public bool BuildProjectsTest { get; private set; }
    public string BuildProjectsUrl { get; private set; } = "";
    public bool DarkTheme { get; private set; }
    public bool ThemeMainBlack { get; private set; }
    public bool EnableQuests { get; private set; }
    public string PreferredCommander { get; private set; } = "";
    public string Hotkey { get; private set; } = "Pause";

    public bool TargetLatLongActive { get; private set; }
    public double TargetLat { get; private set; }
    public double TargetLong { get; private set; }

    public bool BoxelSearchActive { get; private set; }
    public string BoxelSearchPrefix { get; private set; } = "";
    public string BoxelSearchCurrent { get; private set; } = "";
    public string BoxelSearchNextSystem { get; private set; } = "";

    public bool SphereLimitActive { get; private set; }
    public double SphereLimitRadiusLy { get; private set; } = 1000;
    public double SphereLimitX { get; private set; }
    public double SphereLimitY { get; private set; }
    public double SphereLimitZ { get; private set; }

    public void Reload()
    {
        AllowPresent = false;
        OverlayVisible = true;
        BuildProjectsSuppressOtherOverlays = false;
        BuildProjectsTest = false;
        BuildProjectsUrl = "";
        DarkTheme = false;
        ThemeMainBlack = false;
        EnableQuests = false;
        PreferredCommander = "";
        Hotkey = "Pause";
        TargetLatLongActive = false;
        TargetLat = 0;
        TargetLong = 0;
        BoxelSearchActive = false;
        BoxelSearchPrefix = "";
        BoxelSearchCurrent = "";
        BoxelSearchNextSystem = "";
        SphereLimitActive = false;
        SphereLimitRadiusLy = 1000;
        SphereLimitX = 0;
        SphereLimitY = 0;
        SphereLimitZ = 0;
        _values.Clear();

        if (!File.Exists(_path))
            return;

        foreach (var line in File.ReadAllLines(_path))
        {
            var raw = line.Trim();
            if (raw.Length == 0 || raw.StartsWith('#') || raw.StartsWith(';'))
                continue;
            var eq = raw.IndexOf('=');
            if (eq <= 0)
                continue;
            var key = raw[..eq].Trim();
            var value = raw[(eq + 1)..].Trim();
            _values[key] = value;
            switch (key)
            {
                case "allow_present":
                    AllowPresent = IsTruthy(value);
                    break;
                case "overlay_visible":
                    OverlayVisible = IsTruthy(value);
                    break;
                case "hotkey":
                    if (!string.IsNullOrWhiteSpace(value))
                        Hotkey = value;
                    break;
                case "gs.buildProjectsSuppressOtherOverlays":
                    BuildProjectsSuppressOtherOverlays = IsTruthy(value);
                    break;
                case "gs.buildProjects_TEST":
                    BuildProjectsTest = IsTruthy(value);
                    break;
                case "gs.buildProjectsUrl_TEST":
                    BuildProjectsUrl = value.Trim().TrimEnd('/');
                    break;
                case "gs.darkTheme":
                    DarkTheme = IsTruthy(value);
                    break;
                case "gs.themeMainBlack":
                    ThemeMainBlack = IsTruthy(value);
                    break;
                case "gs.enableQuests":
                    EnableQuests = IsTruthy(value);
                    break;
                case "gs.preferredCommander":
                    PreferredCommander = value;
                    break;
                case "gs.targetLatLongActive":
                    TargetLatLongActive = IsTruthy(value);
                    break;
                case "gs.targetLat":
                    TargetLat = ParseDouble(value, 0);
                    break;
                case "gs.targetLong":
                    TargetLong = ParseDouble(value, 0);
                    break;
                case "gs.boxelSearchActive":
                    BoxelSearchActive = IsTruthy(value);
                    break;
                case "gs.boxelSearchPrefix":
                    BoxelSearchPrefix = value;
                    break;
                case "gs.boxelSearchCurrent":
                    BoxelSearchCurrent = value;
                    break;
                case "gs.boxelSearchNextSystem":
                    BoxelSearchNextSystem = value;
                    break;
                case "gs.sphereLimitActive":
                    SphereLimitActive = IsTruthy(value);
                    break;
                case "gs.sphereLimitRadiusLy":
                    SphereLimitRadiusLy = ParseDouble(value, 1000);
                    break;
                case "gs.sphereLimitX":
                    SphereLimitX = ParseDouble(value, 0);
                    break;
                case "gs.sphereLimitY":
                    SphereLimitY = ParseDouble(value, 0);
                    break;
                case "gs.sphereLimitZ":
                    SphereLimitZ = ParseDouble(value, 0);
                    break;
            }
        }
    }

    public void SetOverlayVisible(bool visible)
    {
        OverlayVisible = visible;
        SetKey("overlay_visible", visible ? "true" : "false");
    }

    public void SetAllowPresent(bool allow)
    {
        AllowPresent = allow;
        SetKey("allow_present", allow ? "true" : "false");
    }

    public void SetBuildProjectsSuppressOtherOverlays(bool suppress)
    {
        BuildProjectsSuppressOtherOverlays = suppress;
        SetKey(
            "gs.buildProjectsSuppressOtherOverlays",
            suppress ? "true" : "false");
    }

    public void SetGroundTarget(double lat, double lng, bool active)
    {
        TargetLat = lat;
        TargetLong = lng;
        TargetLatLongActive = active;
        SetKey("gs.targetLat", FormatDouble(lat));
        SetKey("gs.targetLong", FormatDouble(lng));
        SetKey("gs.targetLatLongActive", active ? "true" : "false");
    }

    public void ClearGroundTarget()
    {
        SetGroundTarget(0, 0, false);
    }

    public void SetBoxelSearch(
        bool active,
        string prefix,
        string current,
        string nextSystem)
    {
        BoxelSearchActive = active;
        BoxelSearchPrefix = prefix ?? "";
        BoxelSearchCurrent = current ?? "";
        BoxelSearchNextSystem = nextSystem ?? "";
        SetKey("gs.boxelSearchActive", active ? "true" : "false");
        SetKey("gs.boxelSearchPrefix", BoxelSearchPrefix);
        SetKey("gs.boxelSearchCurrent", BoxelSearchCurrent);
        SetKey("gs.boxelSearchNextSystem", BoxelSearchNextSystem);
    }

    public void SetSphereLimit(
        bool active,
        double radiusLy,
        double x,
        double y,
        double z)
    {
        SphereLimitActive = active;
        SphereLimitRadiusLy = radiusLy;
        SphereLimitX = x;
        SphereLimitY = y;
        SphereLimitZ = z;
        SetKey("gs.sphereLimitActive", active ? "true" : "false");
        SetKey("gs.sphereLimitRadiusLy", FormatDouble(radiusLy));
        SetKey("gs.sphereLimitX", FormatDouble(x));
        SetKey("gs.sphereLimitY", FormatDouble(y));
        SetKey("gs.sphereLimitZ", FormatDouble(z));
    }

    void SetKey(string key, string value)
    {
        _values[key] = value;
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(_path)!);
        var lines = File.Exists(_path)
            ? new List<string>(File.ReadAllLines(_path))
            : new List<string> { "# SrvSurvey Linux settings" };

        var found = false;
        for (var i = 0; i < lines.Count; i++)
        {
            var trimmed = lines[i].TrimStart();
            if (trimmed.StartsWith('#') || trimmed.StartsWith(';'))
                continue;
            var eq = lines[i].IndexOf('=');
            if (eq <= 0)
                continue;
            if (!string.Equals(lines[i][..eq].Trim(), key, StringComparison.Ordinal))
                continue;
            lines[i] = $"{key}={value}";
            found = true;
            break;
        }

        if (!found)
            lines.Add($"{key}={value}");

        File.WriteAllLines(_path, lines);
    }

    static bool IsTruthy(string value) =>
        value.Equals("1", StringComparison.OrdinalIgnoreCase)
        || value.Equals("true", StringComparison.OrdinalIgnoreCase)
        || value.Equals("yes", StringComparison.OrdinalIgnoreCase)
        || value.Equals("on", StringComparison.OrdinalIgnoreCase);

    static double ParseDouble(string value, double fallback) =>
        double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var n)
            ? n
            : fallback;

    static string FormatDouble(double value) =>
        value.ToString("G17", CultureInfo.InvariantCulture);
}
