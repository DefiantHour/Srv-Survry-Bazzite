using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

public sealed class GuardianSiteRow
{
    public string Kind { get; init; } = "";
    public string SystemName { get; init; } = "";
    public string BodyName { get; init; } = "";
    public string SiteType { get; init; } = "";
    public long SystemAddress { get; init; }
    public int? BodyId { get; init; }
    public double? Latitude { get; init; }
    public double? Longitude { get; init; }
    public string Summary { get; init; } = "";
}

public static class GuardianSiteStore
{
    public static IReadOnlyList<GuardianSiteRow> LoadBeacons()
    {
        var path = DataFileLocator.AllBeaconsPath;
        if (!File.Exists(path))
            return Array.Empty<GuardianSiteRow>();
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
                return Array.Empty<GuardianSiteRow>();
            return doc.RootElement.EnumerateArray()
                .Select(el => new GuardianSiteRow
                {
                    Kind = "Beacon",
                    SystemName = GetString(el, "systemName") ?? "",
                    BodyName = GetString(el, "bodyName") ?? "",
                    SiteType = GetString(el, "relatedStructure") ?? "Beacon",
                    SystemAddress = GetLong(el, "systemAddress"),
                    BodyId = GetInt(el, "bodyId"),
                    Summary = FormatBeacon(el),
                })
                .OrderBy(r => r.SystemName, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }
        catch
        {
            return Array.Empty<GuardianSiteRow>();
        }
    }

    public static IReadOnlyList<GuardianSiteRow> LoadRuins()
    {
        var path = DataFileLocator.AllRuinsPath;
        if (!File.Exists(path))
            return Array.Empty<GuardianSiteRow>();
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
                return Array.Empty<GuardianSiteRow>();
            return doc.RootElement.EnumerateArray()
                .Select(el => new GuardianSiteRow
                {
                    Kind = "Ruin",
                    SystemName = GetString(el, "systemName") ?? "",
                    BodyName = GetString(el, "bodyName") ?? "",
                    SiteType = GetString(el, "siteType") ?? "Ruin",
                    SystemAddress = GetLong(el, "systemAddress"),
                    BodyId = GetInt(el, "bodyId"),
                    Latitude = GetDouble(el, "latitude"),
                    Longitude = GetDouble(el, "longitude"),
                    Summary = FormatRuin(el),
                })
                .OrderBy(r => r.SystemName, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }
        catch
        {
            return Array.Empty<GuardianSiteRow>();
        }
    }

    static string FormatBeacon(JsonElement el)
    {
        var related = GetString(el, "relatedStructure");
        var dist = GetDouble(el, "distanceToArrival");
        return dist.HasValue
            ? $"{related ?? "Beacon"} · {dist.Value:0} ls"
            : related ?? "Beacon";
    }

    static string FormatRuin(JsonElement el)
    {
        var type = GetString(el, "siteType") ?? "Ruin";
        var idx = GetInt(el, "idx");
        var progress = GetInt(el, "surveyProgress");
        var parts = new List<string> { type };
        if (idx.HasValue)
            parts.Add($"#{idx.Value}");
        if (progress.HasValue)
            parts.Add($"survey {progress.Value}%");
        return string.Join(" · ", parts);
    }

    static string? GetString(JsonElement el, string name) =>
        el.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String
            ? p.GetString()
            : null;

    static long GetLong(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p))
            return 0;
        if (p.ValueKind == JsonValueKind.Number && p.TryGetInt64(out var n))
            return n;
        return 0;
    }

    static int? GetInt(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p))
            return null;
        if (p.ValueKind == JsonValueKind.Number && p.TryGetInt32(out var n))
            return n;
        return null;
    }

    static double? GetDouble(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p))
            return null;
        if (p.ValueKind == JsonValueKind.Number && p.TryGetDouble(out var n))
            return n;
        return null;
    }
}
