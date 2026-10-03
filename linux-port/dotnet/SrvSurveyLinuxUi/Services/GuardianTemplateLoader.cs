using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

public sealed class GuardianTemplatePoi
{
    public string Name { get; init; } = "";
    public string Type { get; init; } = "";
    public double Angle { get; init; }
    public double Dist { get; init; }
}

public sealed class GuardianTemplate
{
    public string SiteType { get; init; } = "";
    public string BackgroundImage { get; init; } = "";
    public IReadOnlyList<GuardianTemplatePoi> Pois { get; init; } = Array.Empty<GuardianTemplatePoi>();
}

public static class GuardianTemplateLoader
{
    static readonly object Gate = new();
    static readonly Dictionary<string, GuardianTemplate> Cache = new(StringComparer.OrdinalIgnoreCase);

    public static GuardianTemplate? Load(string siteType)
    {
        if (string.IsNullOrWhiteSpace(siteType) || siteType.Equals("All", StringComparison.OrdinalIgnoreCase))
            return null;
        lock (Gate)
        {
            if (Cache.TryGetValue(siteType, out var hit))
                return hit;
            var loaded = Read(siteType);
            if (loaded != null)
                Cache[siteType] = loaded;
            return loaded;
        }
    }

    static GuardianTemplate? Read(string siteType)
    {
        var path = DataFileLocator.GuardianTemplatesPath;
        if (!File.Exists(path))
            return null;
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (!doc.RootElement.TryGetProperty(siteType, out var node) || node.ValueKind != JsonValueKind.Object)
                return null;
            var pois = new List<GuardianTemplatePoi>();
            if (node.TryGetProperty("poi", out var list) && list.ValueKind == JsonValueKind.Array)
            {
                foreach (var el in list.EnumerateArray())
                {
                    if (!el.TryGetProperty("angle", out var angleEl) || !angleEl.TryGetDouble(out var angle))
                        continue;
                    if (!el.TryGetProperty("dist", out var distEl) || !distEl.TryGetDouble(out var dist))
                        continue;
                    pois.Add(new GuardianTemplatePoi
                    {
                        Name = el.TryGetProperty("name", out var name) && name.ValueKind == JsonValueKind.String
                            ? name.GetString() ?? ""
                            : "",
                        Type = el.TryGetProperty("type", out var type) && type.ValueKind == JsonValueKind.String
                            ? type.GetString() ?? ""
                            : "",
                        Angle = angle,
                        Dist = dist,
                    });
                }
            }
            var background = node.TryGetProperty("backgroundImage", out var bg) && bg.ValueKind == JsonValueKind.String
                ? bg.GetString() ?? ""
                : "";
            return new GuardianTemplate
            {
                SiteType = siteType,
                BackgroundImage = background,
                Pois = pois,
            };
        }
        catch
        {
            return null;
        }
    }
}
