using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// FormRavenUpdater build-type buckets from colonization-costs2.json.
/// </summary>
public static class RavenBuildTypes
{
    static readonly HashSet<string> Installation = new(StringComparer.OrdinalIgnoreCase) { "installation" };
    static readonly HashSet<string> OrbitalPorts = new(StringComparer.OrdinalIgnoreCase) { "outpost", "orbis" };
    static bool _ready;

    public static void EnsureLoaded()
    {
        if (_ready)
            return;
        _ready = true;
        var root = DataFileLocator.WorkspaceRoot;
        if (string.IsNullOrWhiteSpace(root))
            return;
        var path = Path.Combine(root, "SrvSurvey", "colonization-costs2.json");
        if (!File.Exists(path))
            return;
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
                return;
            foreach (var row in doc.RootElement.EnumerateArray())
            {
                var location = Text(row, "location");
                if (!string.Equals(location, "orbital", StringComparison.Ordinal))
                    continue;
                var display = Text(row, "displayName");
                var category = Text(row, "category");
                if (!row.TryGetProperty("layouts", out var layouts) || layouts.ValueKind != JsonValueKind.Array)
                    continue;
                var install = display.Contains("Installation", StringComparison.Ordinal)
                    || category.Contains("Tourist", StringComparison.Ordinal)
                    || category.Contains("Bar", StringComparison.Ordinal);
                var target = install ? Installation : OrbitalPorts;
                foreach (var layout in layouts.EnumerateArray())
                {
                    var name = layout.GetString();
                    if (!string.IsNullOrWhiteSpace(name))
                        target.Add(name);
                }
            }
        }
        catch
        {
            // The seed names still classify installation, outpost, and orbis.
        }
    }

    public static bool InPhase(string phase, int? bodyNum, string? buildType)
    {
        EnsureLoaded();
        var build = (buildType ?? "").Trim().TrimEnd('?');
        var missing = bodyNum is null || bodyNum < 0;
        var installation = Installation.Contains(build);
        var orbital = OrbitalPorts.Contains(build);
        return phase switch
        {
            "noBodyInstallation" => missing && installation,
            "noBodyOrbitalPorts" => missing && orbital,
            "allSurfaceSites" => build.Length == 0 || (!orbital && !installation),
            _ => false,
        };
    }

    static string Text(JsonElement row, string name) =>
        row.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.String
            ? prop.GetString() ?? ""
            : "";
}
