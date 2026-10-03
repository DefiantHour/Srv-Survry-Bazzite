using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

public sealed class NavRouteHop
{
    public string StarSystem { get; init; } = "";
    public long SystemAddress { get; init; }
    public string StarClass { get; init; } = "";
}

public sealed class NavRouteSummary
{
    public string? Path { get; init; }
    public string? Timestamp { get; init; }
    public IReadOnlyList<NavRouteHop> Hops { get; init; } = Array.Empty<NavRouteHop>();
    public string StatusText { get; init; } = "";
}

public static class NavRouteStore
{
    public static NavRouteSummary Load(string? journalFolder = null)
    {
        var path = DataFileLocator.FindNavRoutePath(journalFolder);
        if (path == null || !File.Exists(path))
        {
            return new NavRouteSummary
            {
                StatusText = "NavRoute.json not found (set a plotted route in Elite, or wait for the journal watcher).",
            };
        }

        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            var hops = new List<NavRouteHop>();
            if (root.TryGetProperty("Route", out var route) && route.ValueKind == JsonValueKind.Array)
            {
                foreach (var el in route.EnumerateArray())
                {
                    hops.Add(new NavRouteHop
                    {
                        StarSystem = GetString(el, "StarSystem") ?? "",
                        SystemAddress = GetLong(el, "SystemAddress"),
                        StarClass = GetString(el, "StarClass") ?? "",
                    });
                }
            }

            var dest = hops.LastOrDefault()?.StarSystem;
            var status = hops.Count == 0
                ? "Route file is empty."
                : hops.Count == 1
                    ? $"Route cleared / single system: {hops[0].StarSystem}"
                    : $"{hops.Count} hops → {dest}";

            return new NavRouteSummary
            {
                Path = path,
                Timestamp = GetString(root, "timestamp"),
                Hops = hops,
                StatusText = status,
            };
        }
        catch (Exception ex)
        {
            return new NavRouteSummary
            {
                Path = path,
                StatusText = "Failed to parse NavRoute.json: " + ex.Message,
            };
        }
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
}
