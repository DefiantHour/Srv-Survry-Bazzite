using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

public sealed class GuardianGridEntry
{
    public string Id { get; init; } = "";
    public string Kind { get; init; } = "";
    public string SystemName { get; init; } = "";
    public string BodyName { get; init; } = "";
    public string SiteType { get; init; } = "";
    public string IndexText { get; init; } = "";
    public string ArrivalText { get; init; } = "";
    public string SurveyText { get; init; } = "";
    public bool SurveyComplete { get; init; }
    public double? Latitude { get; init; }
    public double? Longitude { get; init; }
    public int? SiteHeading { get; init; }
    public int? RelicTowerHeading { get; init; }
    public double X { get; init; }
    public double Y { get; init; }
    public double Z { get; init; }
    public bool HasStarPos { get; init; }

    public string LastVisited => "";
    public string HasImages => "";
    public string RamTahLogs => "";
}

/// <summary>
/// Public catalogue rows from allRuins.json, allStructures.json, and allBeacons.json.
/// Last visited, images, and Ram Tah log lists are not in those files.
/// </summary>
public static class GuardianCatalogue
{
    static readonly object Gate = new();
    static List<GuardianGridEntry>? _cache;
    static string _stamp = "";

    public static IReadOnlyList<string> RuinTypes { get; } = new[] { "Alpha", "Beta", "Gamma" };

    public static IReadOnlyList<string> StructureTypes { get; } = new[]
    {
        "Lacrosse", "Crossroads", "Fistbump", "Hammerbot", "Bear", "Bowl",
        "Turtle", "Robolobster", "Squid", "Stickyhand",
    };

    public static IReadOnlyList<GuardianGridEntry> Load()
    {
        lock (Gate)
        {
            var stamp = Stamp(DataFileLocator.AllRuinsPath)
                + "|" + Stamp(DataFileLocator.AllStructuresPath)
                + "|" + Stamp(DataFileLocator.AllBeaconsPath);
            if (_cache != null && stamp == _stamp)
                return _cache;
            var rows = new List<GuardianGridEntry>();
            rows.AddRange(ReadSites(DataFileLocator.AllRuinsPath, "Ruin", "GR"));
            rows.AddRange(ReadSites(DataFileLocator.AllStructuresPath, "Structure", "GS"));
            rows.AddRange(ReadBeacons(DataFileLocator.AllBeaconsPath));
            _cache = rows;
            _stamp = stamp;
            return _cache;
        }
    }

    public static IReadOnlyList<string> SystemNames() =>
        Load()
            .Select(r => r.SystemName)
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(s => s, StringComparer.OrdinalIgnoreCase)
            .ToList();

    public static GuardianGridEntry? FindSystem(string? name)
    {
        if (string.IsNullOrWhiteSpace(name))
            return null;
        return Load().FirstOrDefault(r =>
            r.HasStarPos && string.Equals(r.SystemName, name.Trim(), StringComparison.OrdinalIgnoreCase));
    }

    public static double DistanceLy(double x1, double y1, double z1, double x2, double y2, double z2)
    {
        var dx = x1 - x2;
        var dy = y1 - y2;
        var dz = z1 - z2;
        return Math.Sqrt(dx * dx + dy * dy + dz * dz);
    }

    public static string FormatStarPos(double x, double y, double z) =>
        "[ "
        + x.ToString("0.####", CultureInfo.InvariantCulture)
        + ", "
        + y.ToString("0.####", CultureInfo.InvariantCulture)
        + ", "
        + z.ToString("0.####", CultureInfo.InvariantCulture)
        + " ]";

    static IEnumerable<GuardianGridEntry> ReadSites(string path, string kind, string prefix)
    {
        if (!File.Exists(path))
            yield break;
        JsonDocument doc;
        try
        {
            doc = JsonDocument.Parse(File.ReadAllText(path));
        }
        catch
        {
            yield break;
        }
        using (doc)
        {
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
                yield break;
            foreach (var el in doc.RootElement.EnumerateArray())
            {
                var id = GetInt(el, "siteID");
                var progress = GetInt(el, "surveyProgress") ?? 0;
                var idx = GetInt(el, "idx");
                var star = ReadStar(el);
                yield return new GuardianGridEntry
                {
                    Id = id.HasValue ? $"{prefix} {id.Value}" : "",
                    Kind = kind,
                    SystemName = GetString(el, "systemName") ?? "",
                    BodyName = GetString(el, "bodyName") ?? "",
                    SiteType = GetString(el, "siteType") ?? kind,
                    IndexText = idx is > 0 ? $"#{idx.Value}" : "",
                    ArrivalText = FormatArrival(GetDouble(el, "distanceToArrival")),
                    SurveyText = progress == 0 ? "" : progress.ToString("0", CultureInfo.InvariantCulture) + "%",
                    SurveyComplete = el.TryGetProperty("surveyComplete", out var done) && done.ValueKind == JsonValueKind.True,
                    Latitude = GetDouble(el, "latitude"),
                    Longitude = GetDouble(el, "longitude"),
                    SiteHeading = GetInt(el, "siteHeading"),
                    RelicTowerHeading = GetInt(el, "relicTowerHeading"),
                    X = star.X,
                    Y = star.Y,
                    Z = star.Z,
                    HasStarPos = star.Ok,
                };
            }
        }
    }

    static IEnumerable<GuardianGridEntry> ReadBeacons(string path)
    {
        if (!File.Exists(path))
            yield break;
        JsonDocument doc;
        try
        {
            doc = JsonDocument.Parse(File.ReadAllText(path));
        }
        catch
        {
            yield break;
        }
        using (doc)
        {
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
                yield break;
            foreach (var el in doc.RootElement.EnumerateArray())
            {
                var star = ReadStar(el);
                yield return new GuardianGridEntry
                {
                    Id = "",
                    Kind = "Beacon",
                    SystemName = GetString(el, "systemName") ?? "",
                    BodyName = GetString(el, "bodyName") ?? "",
                    SiteType = "Beacon",
                    ArrivalText = FormatArrival(GetDouble(el, "distanceToArrival")),
                    X = star.X,
                    Y = star.Y,
                    Z = star.Z,
                    HasStarPos = star.Ok,
                };
            }
        }
    }

    static string FormatArrival(double? ls) =>
        ls.HasValue ? ls.Value.ToString("N0", CultureInfo.InvariantCulture) + " ls" : "";

    static (bool Ok, double X, double Y, double Z) ReadStar(JsonElement el)
    {
        if (!el.TryGetProperty("starPos", out var pos) || pos.ValueKind != JsonValueKind.Array || pos.GetArrayLength() < 3)
            return (false, 0, 0, 0);
        if (!pos[0].TryGetDouble(out var x) || !pos[1].TryGetDouble(out var y) || !pos[2].TryGetDouble(out var z))
            return (false, 0, 0, 0);
        return (true, x, y, z);
    }

    static string Stamp(string path)
    {
        try
        {
            if (!File.Exists(path))
                return "missing";
            var info = new FileInfo(path);
            return info.Length + ":" + info.LastWriteTimeUtc.Ticks;
        }
        catch
        {
            return "err";
        }
    }

    static string? GetString(JsonElement el, string name) =>
        el.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;

    static int? GetInt(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p) || p.ValueKind != JsonValueKind.Number)
            return null;
        return p.TryGetInt32(out var n) ? n : null;
    }

    static double? GetDouble(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p) || p.ValueKind != JsonValueKind.Number)
            return null;
        return p.TryGetDouble(out var n) ? n : null;
    }
}
