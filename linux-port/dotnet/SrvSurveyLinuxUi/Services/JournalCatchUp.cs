using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// Incremental journal catch-up for the commander trip counter and bio rewards.
/// Mirrors the Windows Game / SystemData increments that feed Main.
/// </summary>
public static class JournalCatchUp
{
    public static CommanderRecord Apply(CommanderRecord rec, string? journalFolder)
    {
        if (string.IsNullOrWhiteSpace(journalFolder) || !Directory.Exists(journalFolder))
            return rec;

        var files = Directory.EnumerateFiles(journalFolder, "Journal.*.log")
            .OrderBy(Path.GetFileName, StringComparer.Ordinal)
            .ToList();
        if (files.Count == 0)
            return rec;

        var startIndex = files.Count - 1;
        if (!string.IsNullOrWhiteSpace(rec.LastJournalFile))
        {
            var lastName = Path.GetFileName(rec.LastJournalFile);
            var idx = files.FindIndex(f =>
                string.Equals(Path.GetFileName(f), lastName, StringComparison.OrdinalIgnoreCase));
            startIndex = idx >= 0 ? idx : files.Count - 1;
        }

        var dirty = false;
        for (var i = startIndex; i < files.Count; i++)
        {
            var path = files[i];
            var offset = 0L;
            if (i == startIndex
                && string.Equals(Path.GetFileName(path), Path.GetFileName(rec.LastJournalFile ?? ""), StringComparison.OrdinalIgnoreCase))
                offset = rec.LastJournalOffset;
            if (ApplyFile(rec, path, offset))
                dirty = true;
        }

        if (dirty)
            CommanderStore.Save(rec);
        return rec;
    }

    public static bool ApplyFile(CommanderRecord rec, string path, long startOffset)
    {
        if (!File.Exists(path))
            return false;

        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        if (startOffset > stream.Length)
            startOffset = 0;
        stream.Seek(startOffset, SeekOrigin.Begin);
        using var reader = new StreamReader(stream);
        string? line;
        var changed = false;
        while ((line = reader.ReadLine()) != null)
        {
            if (ApplyLine(rec, line))
                changed = true;
        }

        rec.LastJournalFile = path;
        rec.LastJournalOffset = stream.Position;
        return changed || startOffset != rec.LastJournalOffset;
    }

    public static bool ApplyLine(CommanderRecord rec, string line)
    {
        if (string.IsNullOrWhiteSpace(line) || line[0] != '{')
            return false;
        try
        {
            using var doc = JsonDocument.Parse(line);
            return ApplyEvent(rec, doc.RootElement);
        }
        catch (JsonException)
        {
            return false;
        }
    }

    public static bool ApplyEvent(CommanderRecord rec, JsonElement root)
    {
        if (!root.TryGetProperty("event", out var evEl))
            return false;
        var evt = evEl.GetString();
        switch (evt)
        {
            case "LoadGame":
                rec.Commander = GetString(root, "Commander") ?? rec.Commander;
                rec.Fid = GetString(root, "FID") ?? rec.Fid;
                return true;
            case "FSDJump":
            case "CarrierJump":
                rec.CountJumps++;
                if (root.TryGetProperty("JumpDist", out var distEl) && distEl.TryGetDouble(out var dist))
                    rec.DistanceTravelled += dist;
                EnterSystem(rec, root);
                rec.LastStationName = null;
                rec.LastStationType = null;
                rec.LastMarketId = 0;
                rec.LastDockedSystemAddress = 0;
                rec.LastStationServices.Clear();
                rec.FssAllBodies = false;
                return true;
            case "Location":
                EnterSystem(rec, root);
                if (root.TryGetProperty("Docked", out var docked) && docked.ValueKind == JsonValueKind.True)
                    ApplyDocked(rec, root);
                return true;
            case "Docked":
                ApplyDocked(rec, root);
                return true;
            case "Undocked":
                rec.LastStationName = null;
                rec.LastStationType = null;
                rec.LastMarketId = 0;
                rec.LastDockedSystemAddress = 0;
                rec.LastStationServices.Clear();
                return true;
            case "ReceiveText":
                return FleetCarrierNames.LearnFromReceiveText(rec, GetString(root, "From"));
            case "FSSSignalDiscovered":
                return FleetCarrierNames.LearnFromFss(
                    rec,
                    GetString(root, "SignalType"),
                    GetString(root, "SignalName"));
            case "ApproachBody":
                rec.CurrentBody = GetString(root, "Body") ?? rec.CurrentBody;
                return true;
            case "LeaveBody":
                rec.CurrentBody = null;
                rec.CurrentBodyType = null;
                return true;
            case "FSSAllBodiesFound":
                rec.FssAllBodies = true;
                return true;
            case "Scan":
                return ApplyScan(rec, root);
            case "SAAScanComplete":
                return ApplyDss(rec, root);
            case "Touchdown":
                return ApplyTouchdown(rec, root);
            case "FSSBodySignals":
            case "SAASignalsFound":
                return ApplyBioSignals(rec, root);
            case "ScanOrganic":
                return ApplyScanOrganic(rec, root);
            case "SellOrganicData":
                return ApplySellOrganic(rec, root);
            case "Died":
                rec.ScannedBioEntryIds.Clear();
                rec.OrganicRewards = 0;
                foreach (var scan in rec.BodyScans.Values)
                    scan.BioAnalyzed = 0;
                return true;
            default:
                return false;
        }
    }

    static void ApplyDocked(CommanderRecord rec, JsonElement root)
    {
        rec.LastStationName = GetString(root, "StationName");
        rec.LastStationType = GetString(root, "StationType");
        rec.LastMarketId = GetLong(root, "MarketID");
        rec.LastDockedSystemAddress = GetLong(root, "SystemAddress");
        if (rec.LastDockedSystemAddress == 0)
            rec.LastDockedSystemAddress = rec.CurrentSystemAddress;
        rec.LastStationServices.Clear();
        if (root.TryGetProperty("StationServices", out var svc) && svc.ValueKind == JsonValueKind.Array)
        {
            foreach (var row in svc.EnumerateArray())
            {
                if (row.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(row.GetString()))
                    rec.LastStationServices.Add(row.GetString()!);
            }
        }
    }

    static void EnterSystem(CommanderRecord rec, JsonElement root)
    {
        var address = GetLong(root, "SystemAddress");
        var system = GetString(root, "StarSystem") ?? rec.CurrentSystem;
        var same = (address != 0 && address == rec.CurrentSystemAddress)
            || (address == 0 && string.Equals(system, rec.CurrentSystem, StringComparison.OrdinalIgnoreCase));
        rec.CurrentSystem = system;
        if (address != 0)
            rec.CurrentSystemAddress = address;
        rec.CurrentBody = GetString(root, "Body") ?? rec.CurrentBody;
        rec.CurrentBodyType = rec.BodyTypeFor(rec.CurrentBody);
        if (same)
            return;
        rec.BodyScans.Clear();
        rec.FssAllBodies = false;
        rec.DssAllBonusApplied = false;
    }

    static bool ApplyScan(CommanderRecord rec, JsonElement root)
    {
        var scanType = GetString(root, "ScanType");
        if (string.Equals(scanType, "NavBeaconDetail", StringComparison.OrdinalIgnoreCase))
            return false;
        var name = GetString(root, "BodyName");
        if (string.IsNullOrWhiteSpace(name))
            return false;

        var planet = GetString(root, "PlanetClass");
        var star = GetString(root, "StarType");
        var landable = root.TryGetProperty("Landable", out var landEl) && landEl.ValueKind == JsonValueKind.True;
        var terraform = GetString(root, "TerraformState") == "Terraformable";
        var mass = GetDouble(root, "MassEM");
        if (mass <= 0)
            mass = GetDouble(root, "StellarMass");
        var wasDiscovered = root.TryGetProperty("WasDiscovered", out var wd) && wd.ValueKind == JsonValueKind.True;
        var wasMapped = root.TryGetProperty("WasMapped", out var wm) && wm.ValueKind == JsonValueKind.True;
        var bodyType = BodyValue.BodyTypeFrom(star, planet, landable, name);
        var reward = BodyValue.GetBodyValue(
            planet ?? star,
            terraform,
            mass,
            !wasDiscovered,
            false,
            !wasMapped);

        rec.BodyScans.TryGetValue(name, out var prior);
        prior ??= new BodyScanRecord();
        prior.PlanetClass = planet;
        prior.StarType = star;
        prior.Terraformable = terraform;
        prior.Mass = mass;
        prior.WasDiscovered = wasDiscovered;
        prior.WasMapped = wasMapped;
        prior.Landable = landable;
        prior.BodyType = bodyType;
        prior.BodyId = (int)GetLong(root, "BodyID");
        prior.DistLs = GetDouble(root, "DistanceFromArrivalLS");
        prior.Radius = GetDouble(root, "Radius");
        prior.Temp = GetDouble(root, "SurfaceTemperature");
        prior.Gravity = GetDouble(root, "SurfaceGravity");
        prior.TidalLock = root.TryGetProperty("TidalLock", out var tl) && tl.ValueKind == JsonValueKind.True;
        prior.Volcanism = GetString(root, "Volcanism");
        if (root.TryGetProperty("Parents", out var parents) && parents.ValueKind == JsonValueKind.Array)
        {
            prior.Parents.Clear();
            foreach (var row in parents.EnumerateArray())
            {
                if (row.ValueKind != JsonValueKind.Object)
                    continue;
                foreach (var prop in row.EnumerateObject())
                {
                    if (prop.Value.ValueKind == JsonValueKind.Number && prop.Value.TryGetInt32(out var id))
                        prior.Parents.Add(id);
                }
            }
        }

        rec.BodyScans[name] = prior;
        rec.CurrentBodyType = string.Equals(name, rec.CurrentBody, StringComparison.OrdinalIgnoreCase)
            ? bodyType
            : rec.CurrentBodyType;

        if (prior.Reward < reward)
        {
            CommanderStore.ApplyExplReward(rec, reward - prior.Reward, rec.CurrentSystem ?? "");
            prior.Reward = reward;
            rec.CountScans++;
        }

        return true;
    }

    static bool ApplyDss(CommanderRecord rec, JsonElement root)
    {
        var name = GetString(root, "BodyName");
        if (string.IsNullOrWhiteSpace(name))
            return false;
        rec.BodyScans.TryGetValue(name, out var prior);
        prior ??= new BodyScanRecord { BodyType = rec.BodyTypeFor(name) ?? "Unknown" };
        var probes = (int)GetLong(root, "ProbesUsed");
        var target = (int)GetLong(root, "EfficiencyTarget");
        var efficient = target <= 0 || probes <= target;
        var reward = BodyValue.GetBodyValue(
            prior.PlanetClass ?? prior.StarType,
            prior.Terraformable,
            prior.Mass,
            !prior.WasDiscovered,
            true,
            !prior.WasMapped,
            efficient);
        prior.DssComplete = true;
        rec.BodyScans[name] = prior;
        if (prior.Reward < reward)
        {
            CommanderStore.ApplyExplReward(rec, reward - prior.Reward, rec.CurrentSystem ?? "");
            prior.Reward = reward;
            rec.CountDss++;
        }

        var mappable = rec.BodyScans.Values.Count(b =>
            b.BodyType is "LandableBody" or "SolidBody" or "Giant");
        var mapped = rec.BodyScans.Values.Count(b =>
            b.DssComplete && b.BodyType is "LandableBody" or "SolidBody" or "Giant");
        if (mappable > 0 && mapped == mappable && !rec.DssAllBonusApplied)
        {
            CommanderStore.ApplyExplReward(rec, mappable * 10_000L, rec.CurrentSystem ?? "");
            rec.DssAllBonusApplied = true;
        }

        return true;
    }

    static bool ApplyTouchdown(CommanderRecord rec, JsonElement root)
    {
        if (root.TryGetProperty("OnPlanet", out var onPlanet) && onPlanet.ValueKind == JsonValueKind.False)
            return false;
        var name = GetString(root, "Body") ?? rec.CurrentBody;
        if (string.IsNullOrWhiteSpace(name))
            return false;
        var key = rec.CurrentSystemAddress + "_" + name;
        if (!rec.LandedBodies.Add(key))
            return false;
        rec.CountLanded++;
        return true;
    }

    static bool ApplyBioSignals(CommanderRecord rec, JsonElement root)
    {
        var name = GetString(root, "BodyName");
        if (string.IsNullOrWhiteSpace(name))
            return false;
        var bio = 0;
        var geo = 0;
        if (root.TryGetProperty("Signals", out var signals) && signals.ValueKind == JsonValueKind.Array)
        {
            foreach (var row in signals.EnumerateArray())
            {
                var type = GetString(row, "Type") ?? GetString(row, "Type_Localised") ?? "";
                var isBio = type.Contains("Bio", StringComparison.OrdinalIgnoreCase)
                    || type == "$SAA_SignalType_Biological;";
                var isGeo = type.Contains("Geo", StringComparison.OrdinalIgnoreCase)
                    || type == "$SAA_SignalType_Geological;";
                if (!isBio && !isGeo)
                    continue;
                if (row.TryGetProperty("Count", out var c) && c.TryGetInt32(out var n))
                {
                    if (isBio)
                        bio += n;
                    else
                        geo += n;
                }
            }
        }

        rec.BodyScans.TryGetValue(name, out var prior);
        prior ??= new BodyScanRecord();
        prior.BioSignals = Math.Max(prior.BioSignals, bio);
        prior.GeoSignals = Math.Max(prior.GeoSignals, geo);
        if (root.TryGetProperty("Genuses", out var genuses) && genuses.ValueKind == JsonValueKind.Array)
        {
            foreach (var row in genuses.EnumerateArray())
            {
                var genus = GetString(row, "Genus_Localised") ?? GetString(row, "Genus");
                if (string.IsNullOrWhiteSpace(genus))
                    continue;
                if (genus.StartsWith('$') && genus.EndsWith(';'))
                    genus = genus.Trim('$', ';').Replace('_', ' ');
                if (!prior.Genuses.Contains(genus, StringComparer.OrdinalIgnoreCase))
                    prior.Genuses.Add(genus);
            }
        }

        rec.BodyScans[name] = prior;
        return true;
    }

    static bool ApplyScanOrganic(CommanderRecord rec, JsonElement root)
    {
        if (!string.Equals(GetString(root, "ScanType"), "Analyse", StringComparison.OrdinalIgnoreCase))
            return false;
        var body = GetString(root, "Body") ?? rec.CurrentBody ?? "";
        var species = GetString(root, "Species_Localised") ?? GetString(root, "Species") ?? "";
        var address = GetLong(root, "SystemAddress");
        if (address == 0)
            address = rec.CurrentSystemAddress;
        var bodyId = GetLong(root, "BodyID");
        var match = LookupSpecies(species);
        var entryId = match?.EntryId ?? "0";
        var reward = match?.Reward ?? 0;
        var firstFoot = rec.BodyFirstFoot.TryGetValue(body, out var ff) && ff;
        var key = $"{address}_{bodyId}_{entryId}_{reward}_{firstFoot}";
        if (!rec.ScannedBioEntryIds.Add(key))
            return false;
        if (!string.IsNullOrWhiteSpace(body))
        {
            rec.BodyScans.TryGetValue(body, out var scan);
            scan ??= new BodyScanRecord();
            scan.BioAnalyzed++;
            rec.BodyScans[body] = scan;
        }

        CommanderStore.RecalcOrganicRewards(rec);
        return true;
    }

    static bool ApplySellOrganic(CommanderRecord rec, JsonElement root)
    {
        if (!root.TryGetProperty("BioData", out var bio) || bio.ValueKind != JsonValueKind.Array)
        {
            rec.ScannedBioEntryIds.Clear();
            rec.OrganicRewards = 0;
            return true;
        }

        foreach (var row in bio.EnumerateArray())
        {
            var species = GetString(row, "Species_Localised") ?? GetString(row, "Species") ?? "";
            var value = GetLong(row, "Value");
            var match = LookupSpecies(species);
            string? victim = null;
            foreach (var id in rec.ScannedBioEntryIds)
            {
                var parts = id.Split('_');
                if (match != null && parts.Length > 2 && parts[2] == match.EntryId)
                {
                    victim = id;
                    break;
                }

                if (parts.Length > 3
                    && long.TryParse(parts[3], NumberStyles.Integer, CultureInfo.InvariantCulture, out var reward)
                    && reward == value)
                {
                    victim = id;
                    break;
                }
            }

            if (victim != null)
                rec.ScannedBioEntryIds.Remove(victim);
        }

        CommanderStore.RecalcOrganicRewards(rec);
        return true;
    }

    static CodexEntry? LookupSpecies(string? species)
    {
        if (string.IsNullOrWhiteSpace(species))
            return null;
        return CodexRefStore.LoadAll().FirstOrDefault(e =>
            string.Equals(e.EnglishName, species, StringComparison.OrdinalIgnoreCase)
            || (!string.IsNullOrWhiteSpace(e.EnglishName)
                && e.EnglishName.StartsWith(species, StringComparison.OrdinalIgnoreCase))
            || string.Equals(e.Name, species, StringComparison.OrdinalIgnoreCase));
    }

    static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;

    static long GetLong(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el))
            return 0;
        if (el.ValueKind == JsonValueKind.Number && el.TryGetInt64(out var n))
            return n;
        if (el.ValueKind == JsonValueKind.String
            && long.TryParse(el.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed))
            return parsed;
        return 0;
    }

    static double GetDouble(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el))
            return 0;
        if (el.ValueKind == JsonValueKind.Number && el.TryGetDouble(out var d))
            return d;
        return 0;
    }
}
