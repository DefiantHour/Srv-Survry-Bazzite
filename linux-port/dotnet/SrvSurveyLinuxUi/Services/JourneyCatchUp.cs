using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

public sealed class JourneyCatchUpResult
{
    public string Status { get; init; } = "";
    public int SystemsAdded { get; init; }
    public int SystemsTotal { get; init; }
    public int JournalsScanned { get; init; }
}

/// <summary>
/// Best-effort journal catch-up for Avalonia journeys (FSDJump / CarrierJump / Location).
/// Idempotent via visited-system set + watermark timestamp.
/// </summary>
public static class JourneyCatchUp
{
    public static JourneyCatchUpResult CatchUp(JourneyRecord journey, string? journalFolder)
    {
        if (string.IsNullOrWhiteSpace(journey.FilePath))
            return new JourneyCatchUpResult { Status = "No journey file to update." };

        var folder = ResolveJournalFolder(journalFolder);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder))
            return new JourneyCatchUpResult { Status = "Journal folder not found." };

        var watermark = LoadWatermark(journey) ?? journey.StartTime.AddMilliseconds(-1);
        var known = new HashSet<string>(
            journey.VisitedSystems.Where(s => !string.IsNullOrWhiteSpace(s)),
            StringComparer.OrdinalIgnoreCase);
        var added = 0;
        var scanned = 0;
        var latest = watermark;

        var files = Directory.EnumerateFiles(folder, "Journal.*.log")
            .OrderBy(Path.GetFileName, StringComparer.Ordinal)
            .ToList();

        foreach (var path in files)
        {
            scanned++;
            foreach (var line in File.ReadLines(path))
            {
                if (string.IsNullOrWhiteSpace(line) || line[0] != '{')
                    continue;
                try
                {
                    using var doc = JsonDocument.Parse(line);
                    var root = doc.RootElement;
                    if (!root.TryGetProperty("event", out var evtEl))
                        continue;
                    var evt = evtEl.GetString();
                    if (evt is not ("FSDJump" or "CarrierJump" or "Location"))
                        continue;

                    var ts = GetTimestamp(root);
                    if (ts == null || ts <= watermark)
                        continue;

                    var system = GetString(root, "StarSystem");
                    if (string.IsNullOrWhiteSpace(system))
                        continue;

                    if (known.Add(system))
                    {
                        journey.VisitedSystems.Add(system);
                        added++;
                    }

                    if (ts > latest)
                        latest = ts.Value;
                }
                catch (JsonException)
                {
                    // skip
                }
            }
        }

        journey.SystemNotes["__catchUpWatermark"] = latest.ToString("o");
        JourneyStore.Save(journey);

        return new JourneyCatchUpResult
        {
            Status =
                added > 0
                    ? $"Catch-up: +{added} system(s) (now {journey.VisitedSystems.Count}). Watermark {latest:u}."
                    : $"Catch-up: no new systems (visited {journey.VisitedSystems.Count}). Watermark {latest:u}.",
            SystemsAdded = added,
            SystemsTotal = journey.VisitedSystems.Count,
            JournalsScanned = scanned,
        };
    }

    static DateTimeOffset? LoadWatermark(JourneyRecord journey)
    {
        if (journey.SystemNotes.TryGetValue("__catchUpWatermark", out var raw)
            && DateTimeOffset.TryParse(raw, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var dt))
            return dt;
        return null;
    }

    static string? ResolveJournalFolder(string? journalFolder)
    {
        if (!string.IsNullOrWhiteSpace(journalFolder) && Directory.Exists(journalFolder))
            return journalFolder;
        return RuntimeStateSnapshot.TryLoad()?.JournalFolder;
    }

    static DateTimeOffset? GetTimestamp(JsonElement root)
    {
        var s = GetString(root, "timestamp");
        if (string.IsNullOrWhiteSpace(s))
            return null;
        return DateTimeOffset.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var dt)
            ? dt
            : null;
    }

    static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;
}
