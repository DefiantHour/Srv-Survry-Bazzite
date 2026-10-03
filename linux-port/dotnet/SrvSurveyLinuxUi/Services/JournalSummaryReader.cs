using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// Lightweight journal scan for Main commander / system / bio summary lines.
/// Mirrors the subset of journal.py that Windows Main surfaces.
/// </summary>
public sealed class BioBodySummary
{
    public string BodyName { get; init; } = "";
    public int BioCount { get; init; }
    public int Analyzed { get; init; }
    public IReadOnlyList<string> Genuses { get; init; } = Array.Empty<string>();
}

public sealed class JournalSummary
{
    public string? Commander { get; init; }
    public string? Fid { get; init; }
    public bool? Odyssey { get; init; }
    public string? System { get; init; }
    public string? Body { get; init; }
    public string? ShipName { get; init; }
    public string? StationName { get; init; }
    public double? StarX { get; init; }
    public double? StarY { get; init; }
    public double? StarZ { get; init; }
    public string? JournalPath { get; init; }
    /// <summary>ScanOrganic Analyse events after the last SellOrganicData in this journal file.</summary>
    public int UnclaimedOrganisms { get; init; }
    public int SystemBioTotal { get; init; }
    public int SystemBioAnalyzed { get; init; }
    public int BodyBioTotal { get; init; }
    public int BodyBioAnalyzed { get; init; }
    public int OrganicSales { get; init; }
    public long OrganicSaleValue { get; init; }
    public int JumpCount { get; init; }
    public int ScanCount { get; init; }
    public int DssCount { get; init; }
}

public static class JournalSummaryReader
{
    public static string? FindLatestJournal(string journalFolder)
    {
        if (!Directory.Exists(journalFolder))
            return null;
        return Directory.EnumerateFiles(journalFolder, "Journal.*.log")
            .OrderByDescending(Path.GetFileName, StringComparer.Ordinal)
            .FirstOrDefault();
    }

    public static JournalSummary Read(string? journalPath)
    {
        if (string.IsNullOrWhiteSpace(journalPath) || !File.Exists(journalPath))
            return new JournalSummary();

        string? commander = null;
        string? fid = null;
        bool? odyssey = null;
        string? system = null;
        string? body = null;
        string? ship = null;
        string? station = null;
        double? starX = null;
        double? starY = null;
        double? starZ = null;
        var unclaimedOrganisms = 0;
        var bioByBody = new Dictionary<string, (int Total, int Analyzed)>(StringComparer.OrdinalIgnoreCase);
        var organicSales = 0;
        long organicValue = 0;
        var jumps = 0;
        var scans = 0;
        var dss = 0;

        foreach (var line in File.ReadLines(journalPath))
        {
            if (string.IsNullOrWhiteSpace(line) || line[0] != '{')
                continue;
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                if (!root.TryGetProperty("event", out var eventEl))
                    continue;
                var evt = eventEl.GetString();
                switch (evt)
                {
                    case "LoadGame":
                        commander = GetString(root, "Commander") ?? commander;
                        fid = GetString(root, "FID") ?? fid;
                        ship = GetString(root, "Ship_Localised")
                            ?? GetString(root, "ShipName")
                            ?? GetString(root, "Ship")
                            ?? ship;
                        system = GetString(root, "StarSystem") ?? system;
                        if (root.TryGetProperty("Odyssey", out var odysseyEl)
                            && (odysseyEl.ValueKind is JsonValueKind.True or JsonValueKind.False))
                            odyssey = odysseyEl.GetBoolean();
                        break;
                    case "Location":
                    case "FSDJump":
                    case "CarrierJump":
                        if (evt is "FSDJump" or "CarrierJump")
                        {
                            jumps++;
                            station = null;
                        }
                        system = GetString(root, "StarSystem") ?? system;
                        body = GetString(root, "Body");
                        ReadStarPos(root, ref starX, ref starY, ref starZ);
                        bioByBody.Clear();
                        break;
                    case "Docked":
                        station = GetString(root, "StationName") ?? station;
                        break;
                    case "Undocked":
                        station = null;
                        break;
                    case "ApproachBody":
                        body = GetString(root, "Body") ?? body;
                        break;
                    case "LeaveBody":
                        body = null;
                        break;
                    case "FSSBodySignals":
                    case "SAASignalsFound":
                    {
                        var name = GetString(root, "BodyName");
                        if (string.IsNullOrWhiteSpace(name))
                            break;
                        var bio = CountSignalType(root, "Biological");
                        if (bio <= 0 && root.TryGetProperty("Signals", out var signals) &&
                            signals.ValueKind == JsonValueKind.Array)
                        {
                            foreach (var row in signals.EnumerateArray())
                            {
                                var type = GetString(row, "Type") ?? GetString(row, "Type_Localised");
                                if (type != null && type.Contains("Bio", StringComparison.OrdinalIgnoreCase))
                                    bio += row.TryGetProperty("Count", out var c) && c.TryGetInt32(out var n) ? n : 0;
                            }
                        }
                        var prev = bioByBody.GetValueOrDefault(name);
                        bioByBody[name] = (Math.Max(prev.Total, bio), prev.Analyzed);
                        break;
                    }
                    case "ScanOrganic":
                    {
                        var scanType = GetString(root, "ScanType");
                        var name = GetString(root, "Body") ?? body;
                        if (string.Equals(scanType, "Analyse", StringComparison.OrdinalIgnoreCase)
                            && !string.IsNullOrWhiteSpace(name))
                        {
                            var prev = bioByBody.GetValueOrDefault(name);
                            bioByBody[name] = (prev.Total, prev.Analyzed + 1);
                            unclaimedOrganisms++;
                        }
                        break;
                    }
                    case "SellOrganicData":
                        unclaimedOrganisms = 0;
                        if (root.TryGetProperty("BioData", out var bioData) &&
                            bioData.ValueKind == JsonValueKind.Array)
                        {
                            foreach (var row in bioData.EnumerateArray())
                            {
                                organicSales++;
                                if (row.TryGetProperty("Value", out var v) && v.TryGetInt64(out var credits))
                                    organicValue += credits;
                                if (row.TryGetProperty("Bonus", out var b) && b.TryGetInt64(out var bonus))
                                    organicValue += bonus;
                            }
                        }
                        break;
                    case "Scan":
                        scans++;
                        break;
                    case "SAAScanComplete":
                        dss++;
                        break;
                }
            }
            catch (JsonException)
            {
                // Skip broken journal lines (same as journal.py).
            }
        }

        var systemTotal = bioByBody.Values.Sum(x => x.Total);
        var systemAnalyzed = bioByBody.Values.Sum(x => x.Analyzed);
        var bodyTotal = 0;
        var bodyAnalyzed = 0;
        if (!string.IsNullOrWhiteSpace(body) && bioByBody.TryGetValue(body, out var bodySignals))
        {
            bodyTotal = bodySignals.Total;
            bodyAnalyzed = bodySignals.Analyzed;
        }

        return new JournalSummary
        {
            Commander = commander,
            Fid = fid,
            Odyssey = odyssey,
            System = system,
            Body = body,
            ShipName = ship,
            StationName = station,
            StarX = starX,
            StarY = starY,
            StarZ = starZ,
            JournalPath = journalPath,
            UnclaimedOrganisms = unclaimedOrganisms,
            SystemBioTotal = systemTotal,
            SystemBioAnalyzed = systemAnalyzed,
            BodyBioTotal = bodyTotal,
            BodyBioAnalyzed = bodyAnalyzed,
            OrganicSales = organicSales,
            OrganicSaleValue = organicValue,
            JumpCount = jumps,
            ScanCount = scans,
            DssCount = dss,
        };
    }

    /// <summary>
    /// Per-body bio signal + genus list for FormPredictions stand-in.
    /// Resets on FSDJump like Windows system-scoped survey state.
    /// </summary>
    public static IReadOnlyList<BioBodySummary> ReadBioBodies(string? journalFolder)
    {
        if (string.IsNullOrWhiteSpace(journalFolder))
            return Array.Empty<BioBodySummary>();
        var journalPath = FindLatestJournal(journalFolder);
        if (string.IsNullOrWhiteSpace(journalPath) || !File.Exists(journalPath))
            return Array.Empty<BioBodySummary>();

        var bioByBody = new Dictionary<string, (int Total, int Analyzed, List<string> Genuses)>(
            StringComparer.OrdinalIgnoreCase);
        string? body = null;

        foreach (var line in File.ReadLines(journalPath))
        {
            if (string.IsNullOrWhiteSpace(line) || line[0] != '{')
                continue;
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                if (!root.TryGetProperty("event", out var eventEl))
                    continue;
                var evt = eventEl.GetString();
                switch (evt)
                {
                    case "Location":
                    case "FSDJump":
                    case "CarrierJump":
                        body = GetString(root, "Body");
                        bioByBody.Clear();
                        break;
                    case "ApproachBody":
                        body = GetString(root, "Body") ?? body;
                        break;
                    case "LeaveBody":
                        body = null;
                        break;
                    case "FSSBodySignals":
                    case "SAASignalsFound":
                    {
                        var name = GetString(root, "BodyName");
                        if (string.IsNullOrWhiteSpace(name))
                            break;
                        var bio = CountSignalType(root, "Biological");
                        if (bio <= 0 && root.TryGetProperty("Signals", out var signals) &&
                            signals.ValueKind == JsonValueKind.Array)
                        {
                            foreach (var row in signals.EnumerateArray())
                            {
                                var type = GetString(row, "Type") ?? GetString(row, "Type_Localised");
                                if (type != null && type.Contains("Bio", StringComparison.OrdinalIgnoreCase))
                                    bio += row.TryGetProperty("Count", out var c) && c.TryGetInt32(out var n) ? n : 0;
                            }
                        }

                        var genuses = ReadGenuses(root);
                        var prev = bioByBody.GetValueOrDefault(name);
                        var mergedGenuses = prev.Genuses ?? new List<string>();
                        foreach (var g in genuses)
                        {
                            if (!mergedGenuses.Contains(g, StringComparer.OrdinalIgnoreCase))
                                mergedGenuses.Add(g);
                        }

                        bioByBody[name] = (
                            Math.Max(prev.Total, bio),
                            prev.Analyzed,
                            mergedGenuses);
                        break;
                    }
                    case "ScanOrganic":
                    {
                        var scanType = GetString(root, "ScanType");
                        var name = GetString(root, "Body") ?? body;
                        if (string.Equals(scanType, "Analyse", StringComparison.OrdinalIgnoreCase)
                            && !string.IsNullOrWhiteSpace(name))
                        {
                            var prev = bioByBody.GetValueOrDefault(name);
                            bioByBody[name] = (
                                prev.Total,
                                prev.Analyzed + 1,
                                prev.Genuses ?? new List<string>());
                        }
                        break;
                    }
                }
            }
            catch (JsonException)
            {
                // skip
            }
        }

        return bioByBody
            .Where(kv => kv.Value.Total > 0 || kv.Value.Genuses.Count > 0)
            .OrderBy(kv => kv.Key, StringComparer.OrdinalIgnoreCase)
            .Select(kv => new BioBodySummary
            {
                BodyName = kv.Key,
                BioCount = kv.Value.Total,
                Analyzed = kv.Value.Analyzed,
                Genuses = kv.Value.Genuses,
            })
            .ToList();
    }

    static List<string> ReadGenuses(JsonElement root)
    {
        var list = new List<string>();
        if (!root.TryGetProperty("Genuses", out var genuses) || genuses.ValueKind != JsonValueKind.Array)
            return list;
        foreach (var row in genuses.EnumerateArray())
        {
            var name = GetString(row, "Genus_Localised") ?? GetString(row, "Genus");
            if (string.IsNullOrWhiteSpace(name))
                continue;
            if (name.StartsWith('$') && name.EndsWith(';'))
                name = name.Trim('$', ';').Replace('_', ' ');
            list.Add(name);
        }

        return list;
    }

    static int CountSignalType(JsonElement root, string needle)
    {
        if (!root.TryGetProperty("Signals", out var signals) || signals.ValueKind != JsonValueKind.Array)
            return 0;
        var total = 0;
        foreach (var row in signals.EnumerateArray())
        {
            var type = GetString(row, "Type") ?? "";
            if (!type.Contains(needle, StringComparison.OrdinalIgnoreCase))
                continue;
            if (row.TryGetProperty("Count", out var c) && c.TryGetInt32(out var n))
                total += n;
        }
        return total;
    }

    static void ReadStarPos(JsonElement root, ref double? x, ref double? y, ref double? z)
    {
        if (!root.TryGetProperty("StarPos", out var pos) || pos.ValueKind != JsonValueKind.Array)
            return;
        if (pos.GetArrayLength() < 3)
            return;
        if (pos[0].TryGetDouble(out var sx) && pos[1].TryGetDouble(out var sy) && pos[2].TryGetDouble(out var sz))
        {
            x = sx;
            y = sy;
            z = sz;
        }
    }

    static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;
}
