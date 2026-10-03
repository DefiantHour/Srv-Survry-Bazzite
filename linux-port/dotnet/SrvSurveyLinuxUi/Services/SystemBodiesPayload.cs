using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SrvSurveyLinuxUi.Services;

/// <summary>Windows <c>Bod</c> JSON for RavenColonial updateSysBodies.</summary>
public static class SystemBodiesPayload
{
    static readonly JsonSerializerOptions JsonWrite = new()
    {
        PropertyNamingPolicy = null,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public static string Build(CommanderRecord rec)
    {
        var rows = rec.BodyScans
            .Where(kv => kv.Value.BodyType is not "PlanetaryRing" and not "Asteroid")
            .Select(kv => ToBod(kv.Key, kv.Value))
            .Where(b => b.Type != "un")
            .OrderBy(b => b.Num)
            .ToList();
        return JsonSerializer.Serialize(rows, JsonWrite);
    }

    static BodDto ToBod(string name, BodyScanRecord scan)
    {
        var type = MapType(scan);
        var features = new List<string>();
        if (scan.BioSignals > 0)
            features.Add("bio");
        if (scan.GeoSignals > 0)
            features.Add("geo");
        if (scan.Terraformable)
            features.Add("terraformable");
        if (scan.Landable)
            features.Add("landable");
        if (scan.TidalLock)
            features.Add("tidal");
        if (!string.IsNullOrWhiteSpace(scan.Volcanism)
            && !string.Equals(scan.Volcanism, "No volcanism", StringComparison.OrdinalIgnoreCase))
            features.Add("volcanism");

        return new BodDto
        {
            Name = name,
            Num = scan.BodyId,
            DistLS = scan.DistLs,
            Parents = scan.Parents.ToList(),
            Type = type,
            SubType = SubType(scan),
            Features = features,
            Radius = scan.Radius > 0 ? scan.Radius : -1,
            Temp = scan.Temp > 0 ? scan.Temp : -1,
            Gravity = scan.Gravity > 0 ? scan.Gravity : -1,
        };
    }

    static string MapType(BodyScanRecord scan)
    {
        if (!string.IsNullOrEmpty(scan.StarType))
        {
            var star = scan.StarType;
            if (star is "H" or "SupermassiveBlackHole" or "BH")
                return "bh";
            if (star == "NS")
                return "ns";
            if (star.Length > 0 && star[0] == 'D')
                return "wd";
            return "st";
        }

        var planet = scan.PlanetClass ?? "";
        if (planet.Contains("barycentre", StringComparison.OrdinalIgnoreCase)
            || scan.BodyType == "Barycentre")
            return "bc";
        if (planet.Contains("gas giant", StringComparison.OrdinalIgnoreCase))
            return "gg";
        if (planet.Equals("Ammonia world", StringComparison.OrdinalIgnoreCase))
            return "aw";
        if (planet.StartsWith("Earth", StringComparison.OrdinalIgnoreCase))
            return "elw";
        if (planet.Equals("High metal content body", StringComparison.OrdinalIgnoreCase))
            return "hmc";
        if (planet.Equals("Icy body", StringComparison.OrdinalIgnoreCase))
            return "ib";
        if (planet.Equals("Metal rich body", StringComparison.OrdinalIgnoreCase))
            return "mrb";
        if (planet.Equals("Rocky body", StringComparison.OrdinalIgnoreCase))
            return "rb";
        if (planet.Equals("Rocky ice body", StringComparison.OrdinalIgnoreCase))
            return "ri";
        if (planet.Equals("Water giant", StringComparison.OrdinalIgnoreCase))
            return "wg";
        if (planet.Equals("Water world", StringComparison.OrdinalIgnoreCase))
            return "ww";
        return "un";
    }

    static string? SubType(BodyScanRecord scan)
    {
        if (!string.IsNullOrWhiteSpace(scan.StarType))
            return scan.StarType;
        if (string.IsNullOrWhiteSpace(scan.PlanetClass))
            return null;
        return scan.PlanetClass.Replace("Sudarsky ", "", StringComparison.OrdinalIgnoreCase);
    }

    sealed class BodDto
    {
        [JsonPropertyName("name")] public string Name { get; set; } = "";
        [JsonPropertyName("num")] public int Num { get; set; }
        [JsonPropertyName("distLS")] public double DistLS { get; set; }
        [JsonPropertyName("parents")] public List<int> Parents { get; set; } = new();
        [JsonPropertyName("type")] public string Type { get; set; } = "un";
        [JsonPropertyName("subType")] public string? SubType { get; set; }
        [JsonPropertyName("features")] public List<string> Features { get; set; } = new();
        [JsonPropertyName("radius")] public double Radius { get; set; } = -1;
        [JsonPropertyName("temp")] public double Temp { get; set; } = -1;
        [JsonPropertyName("gravity")] public double Gravity { get; set; } = -1;
    }
}
