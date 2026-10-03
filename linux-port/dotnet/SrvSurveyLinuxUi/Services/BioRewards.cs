using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace SrvSurveyLinuxUi.Services;

/// <summary>Windows Main.updateBioTexts value lines from commander scans + CodexRef.</summary>
public static class BioRewards
{
    public static (int scanned, int total) SystemSignals(CommanderRecord rec)
    {
        return (
            rec.BodyScans.Values.Sum(b => b.BioAnalyzed),
            rec.BodyScans.Values.Sum(b => b.BioSignals));
    }

    public static (int scanned, int total) BodySignals(CommanderRecord rec, string? body)
    {
        if (string.IsNullOrWhiteSpace(body) || !rec.BodyScans.TryGetValue(body, out var scan))
            return (0, 0);
        return (scan.BioAnalyzed, scan.BioSignals);
    }

    public static long ActualForSystem(CommanderRecord rec)
    {
        long total = 0;
        foreach (var entry in rec.ScannedBioEntryIds)
        {
            if (!TryParse(entry, out var address, out _, out var reward, out var firstFoot))
                continue;
            if (rec.CurrentSystemAddress != 0 && address != rec.CurrentSystemAddress)
                continue;
            total += firstFoot ? reward * 5 : reward;
        }

        return total;
    }

    public static long ActualForBody(CommanderRecord rec, string? body)
    {
        if (string.IsNullOrWhiteSpace(body) || !rec.BodyScans.TryGetValue(body, out var scan))
            return 0;
        long total = 0;
        foreach (var entry in rec.ScannedBioEntryIds)
        {
            if (!TryParse(entry, out var address, out var bodyId, out var reward, out var firstFoot))
                continue;
            if (rec.CurrentSystemAddress != 0 && address != rec.CurrentSystemAddress)
                continue;
            if (scan.BodyId != 0 && bodyId != scan.BodyId)
                continue;
            total += firstFoot ? reward * 5 : reward;
        }

        return total;
    }

    public static long EstimateForBody(CommanderRecord rec, string? body, IReadOnlyList<CodexEntry> refs)
    {
        if (string.IsNullOrWhiteSpace(body) || !rec.BodyScans.TryGetValue(body, out var scan))
            return 0;
        var firstFoot = rec.BodyFirstFoot.TryGetValue(body, out var ff) && ff;
        long sum = 0;
        foreach (var genus in scan.Genuses)
        {
            var max = MaxRewardForGenus(refs, genus);
            if (max > 0)
                sum += max;
        }

        return firstFoot ? sum * 5 : sum;
    }

    public static long EstimateForSystem(CommanderRecord rec, IReadOnlyList<CodexEntry> refs)
    {
        long total = 0;
        foreach (var kv in rec.BodyScans)
            total += EstimateForBody(rec, kv.Key, refs);
        return total;
    }

    public static bool ValuesUncertain(CommanderRecord rec, string? body = null)
    {
        IEnumerable<KeyValuePair<string, BodyScanRecord>> rows = rec.BodyScans;
        if (!string.IsNullOrWhiteSpace(body))
            rows = rec.BodyScans.Where(kv => string.Equals(kv.Key, body, StringComparison.OrdinalIgnoreCase));
        return rows.Any(kv => kv.Value.BioSignals > 0 && kv.Value.Genuses.Count < kv.Value.BioSignals);
    }

    public static int FirstFootBodies(CommanderRecord rec) =>
        rec.BodyScans.Count(kv =>
            kv.Value.BioSignals > 0
            && rec.BodyFirstFoot.TryGetValue(kv.Key, out var ff)
            && ff);

    public static string FormatValues(long actual, long estimate, bool uncertain, bool firstFoot, int firstFootCount = 0)
    {
        var text = " " + CreditFormat.Credits(actual, true) + " of " + CreditFormat.Credits(estimate, true);
        if (uncertain)
            text += "?";
        if (firstFootCount > 0)
            text += $" (FF: {firstFootCount})";
        else if (firstFoot)
            text += " (FF)";
        return text;
    }

    public static string FormatUnclaimed(CommanderRecord rec) =>
        CreditFormat.Credits(rec.OrganicRewards, true)
        + ", organisms: "
        + rec.ScannedBioEntryIds.Count.ToString(CultureInfo.InvariantCulture);

    static long MaxRewardForGenus(IReadOnlyList<CodexEntry> refs, string genus)
    {
        if (string.IsNullOrWhiteSpace(genus) || refs.Count == 0)
            return 0;
        var trimmed = genus.Trim();
        long max = 0;
        foreach (var entry in refs)
        {
            if (entry.Reward <= max)
                continue;
            if (string.Equals(entry.SubClass, trimmed, StringComparison.OrdinalIgnoreCase)
                || (!string.IsNullOrWhiteSpace(entry.EnglishName)
                    && (entry.EnglishName.StartsWith(trimmed + " ", StringComparison.OrdinalIgnoreCase)
                        || string.Equals(entry.EnglishName, trimmed, StringComparison.OrdinalIgnoreCase))))
                max = entry.Reward;
        }

        return max;
    }

    static bool TryParse(string entry, out long address, out long bodyId, out long reward, out bool firstFoot)
    {
        address = 0;
        bodyId = 0;
        reward = 0;
        firstFoot = false;
        var parts = entry.Split('_');
        if (parts.Length < 4)
            return false;
        if (!long.TryParse(parts[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out address))
            return false;
        if (!long.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out bodyId))
            return false;
        if (!long.TryParse(parts[3], NumberStyles.Integer, CultureInfo.InvariantCulture, out reward))
            return false;
        firstFoot = parts.Length > 4 && !string.Equals(parts[4], bool.FalseString, StringComparison.OrdinalIgnoreCase);
        return true;
    }
}
