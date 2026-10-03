using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// Linux commander file under XDG <c>cmdr/</c>. Merges Windows CommanderSettings
/// exploration / bio fields into the existing Python CmdrState JSON.
/// </summary>
public sealed class CommanderRecord
{
    public string Path { get; set; } = "";
    public string Fid { get; set; } = "";
    public string Commander { get; set; } = "";
    public long ExplRewards { get; set; }
    public double DistanceTravelled { get; set; }
    public int CountJumps { get; set; }
    public int CountScans { get; set; }
    public int CountDss { get; set; }
    public int CountLanded { get; set; }
    public long OrganicRewards { get; set; }
    public HashSet<string> ScannedBioEntryIds { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, long> ExplRewardsBySystem { get; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, BodyScanRecord> BodyScans { get; } = new(StringComparer.OrdinalIgnoreCase);
    public HashSet<string> LandedBodies { get; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, bool> BodyFirstFoot { get; } = new(StringComparer.OrdinalIgnoreCase);
    public string? LastJournalFile { get; set; }
    public long LastJournalOffset { get; set; }
    public long CurrentSystemAddress { get; set; }
    public string? CurrentSystem { get; set; }
    public string? CurrentBody { get; set; }
    public string? CurrentBodyType { get; set; }
    public bool FssAllBodies { get; set; }
    public bool DssAllBonusApplied { get; set; }
    public string? LastStationName { get; set; }
    public string? LastStationType { get; set; }
    public long LastMarketId { get; set; }
    public long LastDockedSystemAddress { get; set; }
    public List<string> LastStationServices { get; } = new();
    public Dictionary<string, string> FcDisplayNames { get; } = new(StringComparer.OrdinalIgnoreCase);
    public string? LastCatchUpError { get; set; }

    public bool IsConstructionSite =>
        ColonySite.IsConstructionSite(LastStationName, LastStationServices);

    public bool IsFleetCarrier =>
        string.Equals(LastStationType, "FleetCarrier", StringComparison.OrdinalIgnoreCase);

    public string? BodyTypeFor(string? body)
    {
        if (string.IsNullOrWhiteSpace(body))
            return null;
        return BodyScans.TryGetValue(body, out var scan) ? scan.BodyType : CurrentBodyType;
    }
}

public sealed class BodyScanRecord
{
    public string? PlanetClass { get; set; }
    public string? StarType { get; set; }
    public bool Terraformable { get; set; }
    public double Mass { get; set; }
    public bool WasDiscovered { get; set; }
    public bool WasMapped { get; set; }
    public bool Landable { get; set; }
    public string BodyType { get; set; } = "Unknown";
    public int Reward { get; set; }
    public bool DssComplete { get; set; }
    public int BodyId { get; set; }
    public int BioSignals { get; set; }
    public int BioAnalyzed { get; set; }
    public int GeoSignals { get; set; }
    public double DistLs { get; set; }
    public double Radius { get; set; }
    public double Temp { get; set; }
    public double Gravity { get; set; }
    public bool TidalLock { get; set; }
    public string? Volcanism { get; set; }
    public List<string> Genuses { get; } = new();
    public List<int> Parents { get; } = new();
}

public static class ColonySite
{
    public const string Planetary = "Planetary Construction Site:";
    public const string Orbital = "Orbital Construction Site:";
    public const string ExtPanel = "$EXT_PANEL_ColonisationShip";

    public static bool IsConstructionSite(string? stationName, IReadOnlyList<string>? services)
    {
        if (string.IsNullOrWhiteSpace(stationName))
            return false;
        var named = stationName.StartsWith(Planetary, StringComparison.OrdinalIgnoreCase)
            || stationName.StartsWith(Orbital, StringComparison.OrdinalIgnoreCase)
            || stationName.StartsWith(ExtPanel, StringComparison.OrdinalIgnoreCase);
        if (!named)
            return false;
        return services != null && services.Any(s =>
            string.Equals(s, "colonisationcontribution", StringComparison.OrdinalIgnoreCase));
    }
}

public static class CommanderStore
{
    static readonly Regex SafeKey = new("[^A-Za-z0-9._-]+", RegexOptions.Compiled);
    static readonly JsonSerializerOptions JsonWrite = new() { WriteIndented = true };

    public static string FileNameFor(string fidOrName)
    {
        var cleaned = SafeKey.Replace((fidOrName ?? "").Trim(), "_");
        if (string.IsNullOrEmpty(cleaned))
            cleaned = "unknown";
        return cleaned + ".json";
    }

    public static string PathFor(string fidOrName) =>
        System.IO.Path.Combine(DataFileLocator.CmdrDirectory, FileNameFor(fidOrName));

    public static CommanderRecord LoadOrCreate(string? fid, string? commander)
    {
        var path = FindPath(fid, commander) ?? PathFor(
            !string.IsNullOrWhiteSpace(fid) ? fid! : (commander ?? "unknown"));
        var rec = LoadPath(path);
        if (!string.IsNullOrWhiteSpace(fid))
            rec.Fid = fid!;
        if (!string.IsNullOrWhiteSpace(commander))
            rec.Commander = commander!;
        rec.Path = path;
        return rec;
    }

    public static string? FindPath(string? fid, string? commander)
    {
        if (!string.IsNullOrWhiteSpace(fid))
        {
            var byFid = PathFor(fid);
            if (File.Exists(byFid))
                return byFid;
        }

        return CmdrBodyFlags.FindFile(commander);
    }

    public static CommanderRecord LoadPath(string path)
    {
        var rec = new CommanderRecord { Path = path };
        if (!File.Exists(path))
            return rec;
        try
        {
            var root = JsonNode.Parse(File.ReadAllText(path)) as JsonObject ?? new JsonObject();
            rec.Fid = GetString(root, "fid") ?? "";
            rec.Commander = GetString(root, "commander") ?? "";
            rec.ExplRewards = GetLong(root, "explRewards");
            rec.DistanceTravelled = GetDouble(root, "distanceTravelled");
            rec.CountJumps = GetInt(root, "countJumps");
            rec.CountScans = GetInt(root, "countScans");
            rec.CountDss = GetInt(root, "countDSS");
            rec.CountLanded = GetInt(root, "countLanded");
            rec.OrganicRewards = GetLong(root, "organicRewards");
            rec.LastJournalFile = GetString(root, "lastJournalFile");
            rec.LastJournalOffset = GetLong(root, "lastJournalOffset");
            rec.CurrentSystemAddress = GetLong(root, "currentSystemAddress");
            rec.CurrentSystem = GetString(root, "currentSystem");
            rec.CurrentBody = GetString(root, "currentBody");
            rec.CurrentBodyType = GetString(root, "currentBodyType");
            rec.FssAllBodies = GetBool(root, "fssAllBodies");
            rec.DssAllBonusApplied = GetBool(root, "dssAllBonusApplied");
            rec.LastStationName = GetString(root, "lastStationName");
            rec.LastStationType = GetString(root, "lastStationType");
            rec.LastMarketId = GetLong(root, "lastMarketId");
            rec.LastDockedSystemAddress = GetLong(root, "lastDockedSystemAddress");
            ReadStringList(root["lastStationServices"], rec.LastStationServices);
            if (root["fcDisplayNames"] is JsonObject names)
            {
                foreach (var prop in names)
                {
                    if (prop.Value is JsonValue val && val.TryGetValue<string>(out var s) && !string.IsNullOrWhiteSpace(s))
                        rec.FcDisplayNames[prop.Key] = s;
                }
            }
            ReadStringSet(root["scannedBioEntryIds"], rec.ScannedBioEntryIds);
            ReadStringSet(root["landedBodies"], rec.LandedBodies);
            if (root["explRewardsBySystem"] is JsonObject bySys)
            {
                foreach (var prop in bySys)
                {
                    if (prop.Value is JsonValue val && val.TryGetValue<long>(out var n))
                        rec.ExplRewardsBySystem[prop.Key] = n;
                }
            }

            if (root["bodyScans"] is JsonObject scans)
            {
                foreach (var prop in scans)
                {
                    if (prop.Value is not JsonObject obj)
                        continue;
                    var scan = new BodyScanRecord
                    {
                        PlanetClass = GetString(obj, "planetClass"),
                        StarType = GetString(obj, "starType"),
                        Terraformable = GetBool(obj, "terraformable"),
                        Mass = GetDouble(obj, "mass"),
                        WasDiscovered = GetBool(obj, "wasDiscovered"),
                        WasMapped = GetBool(obj, "wasMapped"),
                        Landable = GetBool(obj, "landable"),
                        BodyType = GetString(obj, "bodyType") ?? "Unknown",
                        Reward = GetInt(obj, "reward"),
                        DssComplete = GetBool(obj, "dssComplete"),
                        BodyId = GetInt(obj, "bodyId"),
                        BioSignals = GetInt(obj, "bioSignals"),
                        BioAnalyzed = GetInt(obj, "bioAnalyzed"),
                        GeoSignals = GetInt(obj, "geoSignals"),
                        DistLs = GetDouble(obj, "distLS"),
                        Radius = GetDouble(obj, "radius"),
                        Temp = GetDouble(obj, "temp"),
                        Gravity = GetDouble(obj, "gravity"),
                        TidalLock = GetBool(obj, "tidalLock"),
                        Volcanism = GetString(obj, "volcanism"),
                    };
                    ReadStringList(obj["genuses"], scan.Genuses);
                    ReadIntList(obj["parents"], scan.Parents);
                    rec.BodyScans[prop.Key] = scan;
                }
            }

            if (root["bodyFlags"] is JsonObject flags)
            {
                foreach (var prop in flags)
                {
                    if (prop.Value is JsonObject flagObj
                        && flagObj["first_foot"] is JsonValue ff
                        && ff.TryGetValue<bool>(out var foot))
                        rec.BodyFirstFoot[prop.Key] = foot;
                }
            }
        }
        catch (Exception ex)
        {
            rec.LastCatchUpError = ex.Message;
        }

        return rec;
    }

    public static void Save(CommanderRecord rec)
    {
        if (string.IsNullOrWhiteSpace(rec.Path))
            rec.Path = PathFor(!string.IsNullOrWhiteSpace(rec.Fid) ? rec.Fid : rec.Commander);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(rec.Path)!);

        JsonObject root;
        if (File.Exists(rec.Path))
        {
            try
            {
                root = JsonNode.Parse(File.ReadAllText(rec.Path)) as JsonObject ?? new JsonObject();
            }
            catch
            {
                root = new JsonObject();
            }
        }
        else
            root = new JsonObject();

        root["fid"] = rec.Fid;
        root["commander"] = rec.Commander;
        root["explRewards"] = rec.ExplRewards;
        root["distanceTravelled"] = rec.DistanceTravelled;
        root["countJumps"] = rec.CountJumps;
        root["countScans"] = rec.CountScans;
        root["countDSS"] = rec.CountDss;
        root["countLanded"] = rec.CountLanded;
        root["organicRewards"] = rec.OrganicRewards;
        root["lastJournalFile"] = rec.LastJournalFile;
        root["lastJournalOffset"] = rec.LastJournalOffset;
        root["currentSystemAddress"] = rec.CurrentSystemAddress;
        root["currentSystem"] = rec.CurrentSystem;
        root["currentBody"] = rec.CurrentBody;
        root["currentBodyType"] = rec.CurrentBodyType;
        root["fssAllBodies"] = rec.FssAllBodies;
        root["dssAllBonusApplied"] = rec.DssAllBonusApplied;
        root["lastStationName"] = rec.LastStationName;
        root["lastStationType"] = rec.LastStationType;
        root["lastMarketId"] = rec.LastMarketId;
        root["lastDockedSystemAddress"] = rec.LastDockedSystemAddress;
        root["lastStationServices"] = ToArray(rec.LastStationServices);
        var fcNames = new JsonObject();
        foreach (var kv in rec.FcDisplayNames)
            fcNames[kv.Key] = kv.Value;
        root["fcDisplayNames"] = fcNames;
        root["scannedBioEntryIds"] = ToArray(rec.ScannedBioEntryIds.OrderBy(x => x, StringComparer.Ordinal));
        root["landedBodies"] = ToArray(rec.LandedBodies.OrderBy(x => x, StringComparer.OrdinalIgnoreCase));

        var bySys = new JsonObject();
        foreach (var kv in rec.ExplRewardsBySystem)
            bySys[kv.Key] = kv.Value;
        root["explRewardsBySystem"] = bySys;

        var scans = new JsonObject();
        foreach (var kv in rec.BodyScans)
        {
            scans[kv.Key] = new JsonObject
            {
                ["planetClass"] = kv.Value.PlanetClass,
                ["starType"] = kv.Value.StarType,
                ["terraformable"] = kv.Value.Terraformable,
                ["mass"] = kv.Value.Mass,
                ["wasDiscovered"] = kv.Value.WasDiscovered,
                ["wasMapped"] = kv.Value.WasMapped,
                ["landable"] = kv.Value.Landable,
                ["bodyType"] = kv.Value.BodyType,
                ["reward"] = kv.Value.Reward,
                ["dssComplete"] = kv.Value.DssComplete,
                ["bodyId"] = kv.Value.BodyId,
                ["bioSignals"] = kv.Value.BioSignals,
                ["bioAnalyzed"] = kv.Value.BioAnalyzed,
                ["geoSignals"] = kv.Value.GeoSignals,
                ["distLS"] = kv.Value.DistLs,
                ["radius"] = kv.Value.Radius,
                ["temp"] = kv.Value.Temp,
                ["gravity"] = kv.Value.Gravity,
                ["tidalLock"] = kv.Value.TidalLock,
                ["volcanism"] = kv.Value.Volcanism,
                ["genuses"] = ToArray(kv.Value.Genuses),
                ["parents"] = ToIntArray(kv.Value.Parents),
            };
        }
        root["bodyScans"] = scans;

        var flags = root["bodyFlags"] as JsonObject ?? new JsonObject();
        foreach (var kv in rec.BodyFirstFoot)
        {
            var obj = flags[kv.Key] as JsonObject ?? new JsonObject();
            obj["first_foot"] = kv.Value;
            flags[kv.Key] = obj;
        }
        root["bodyFlags"] = flags;

        File.WriteAllText(rec.Path, root.ToJsonString(JsonWrite) + Environment.NewLine);
    }

    public static void ResetExploration(CommanderRecord rec)
    {
        rec.ExplRewards = 0;
        rec.ExplRewardsBySystem.Clear();
        rec.CountJumps = 0;
        rec.DistanceTravelled = 0;
        rec.CountScans = 0;
        rec.CountDss = 0;
        rec.CountLanded = 0;
        Save(rec);
    }

    public static void ResetBio(CommanderRecord rec)
    {
        rec.OrganicRewards = 0;
        rec.ScannedBioEntryIds.Clear();
        Save(rec);
    }

    public static long RecalcOrganicRewards(CommanderRecord rec)
    {
        long total = 0;
        foreach (var entry in rec.ScannedBioEntryIds)
        {
            var parts = entry.Split('_');
            if (parts.Length < 4)
                continue;
            if (!long.TryParse(parts[3], NumberStyles.Integer, CultureInfo.InvariantCulture, out var reward))
                continue;
            var firstFoot = parts.Length > 4 && !string.Equals(parts[4], bool.FalseString, StringComparison.OrdinalIgnoreCase);
            total += firstFoot ? reward * 5 : reward;
        }

        rec.OrganicRewards = total;
        return total;
    }

    public static void ApplyExplReward(CommanderRecord rec, long reward, string systemName)
    {
        rec.ExplRewards += reward;
        if (string.IsNullOrWhiteSpace(systemName))
            return;
        rec.ExplRewardsBySystem.TryGetValue(systemName, out var prior);
        rec.ExplRewardsBySystem[systemName] = prior + reward;
    }

    static JsonArray ToArray(IEnumerable<string> values)
    {
        var arr = new JsonArray();
        foreach (var value in values)
            arr.Add(value);
        return arr;
    }

    static JsonArray ToIntArray(IEnumerable<int> values)
    {
        var arr = new JsonArray();
        foreach (var value in values)
            arr.Add(value);
        return arr;
    }

    static void ReadIntList(JsonNode? node, List<int> dest)
    {
        dest.Clear();
        if (node is not JsonArray arr)
            return;
        foreach (var item in arr)
        {
            if (item is JsonValue val && val.TryGetValue<int>(out var n))
                dest.Add(n);
            else if (item is JsonValue longVal && longVal.TryGetValue<long>(out var ln))
                dest.Add((int)ln);
        }
    }

    static void ReadStringList(JsonNode? node, List<string> dest)
    {
        dest.Clear();
        if (node is not JsonArray arr)
            return;
        foreach (var item in arr)
        {
            if (item is JsonValue val && val.TryGetValue<string>(out var s) && !string.IsNullOrWhiteSpace(s))
                dest.Add(s);
        }
    }

    static void ReadStringSet(JsonNode? node, HashSet<string> dest)
    {
        dest.Clear();
        if (node is not JsonArray arr)
            return;
        foreach (var item in arr)
        {
            if (item is JsonValue val && val.TryGetValue<string>(out var s) && !string.IsNullOrWhiteSpace(s))
                dest.Add(s);
        }
    }

    static string? GetString(JsonObject root, string name) =>
        root[name] is JsonValue val && val.TryGetValue<string>(out var s) ? s : null;

    static long GetLong(JsonObject root, string name)
    {
        if (root[name] is not JsonValue val)
            return 0;
        if (val.TryGetValue<long>(out var n))
            return n;
        if (val.TryGetValue<double>(out var d))
            return (long)d;
        return 0;
    }

    static int GetInt(JsonObject root, string name) => (int)GetLong(root, name);

    static double GetDouble(JsonObject root, string name)
    {
        if (root[name] is not JsonValue val)
            return 0;
        if (val.TryGetValue<double>(out var d))
            return d;
        if (val.TryGetValue<long>(out var n))
            return n;
        return 0;
    }

    static bool GetBool(JsonObject root, string name) =>
        root[name] is JsonValue val && val.TryGetValue<bool>(out var b) && b;
}
