using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace SrvSurveyLinuxUi.Services;

public sealed class JourneyRecord
{
    public string FilePath { get; set; } = "";
    public string Fid { get; set; } = "";
    public string Commander { get; set; } = "";
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public string StartingSystem { get; set; } = "";
    public DateTimeOffset StartTime { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? EndTime { get; set; }
    public List<string> VisitedSystems { get; set; } = new();
    public Dictionary<string, string> SystemNotes { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

public static class JourneyStore
{
    static readonly Regex SafeName = new(@"[^A-Za-z0-9._-]+", RegexOptions.Compiled);

    public static IReadOnlyList<JourneyRecord> ListAll()
    {
        var root = DataFileLocator.JourneyDirectory;
        if (!Directory.Exists(root))
            return Array.Empty<JourneyRecord>();

        var files = Directory.GetFiles(root, "*.json", SearchOption.AllDirectories);
        return files
            .Select(TryLoad)
            .Where(j => j != null)
            .Cast<JourneyRecord>()
            .OrderByDescending(j => j.StartTime)
            .ToList();
    }

    public static JourneyRecord? TryLoad(string path)
    {
        if (!File.Exists(path))
            return null;
        try
        {
            using var stream = File.OpenRead(path);
            using var doc = JsonDocument.Parse(stream);
            var root = doc.RootElement;
            var journey = new JourneyRecord
            {
                FilePath = path,
                Fid = GetString(root, "fid") ?? "",
                Commander = GetString(root, "commander") ?? "",
                Name = GetString(root, "name") ?? Path.GetFileNameWithoutExtension(path),
                Description = GetString(root, "description") ?? "",
                StartingSystem = GetString(root, "startingSystem")
                    ?? GetString(root, "startSystem")
                    ?? "",
                StartTime = GetDate(root, "startTime") ?? DateTimeOffset.UtcNow,
                EndTime = GetDate(root, "endTime"),
            };

            if (root.TryGetProperty("visitedSystems", out var visited)
                && visited.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in visited.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.String)
                    {
                        var s = item.GetString();
                        if (!string.IsNullOrWhiteSpace(s))
                            journey.VisitedSystems.Add(s!);
                    }
                    else if (item.ValueKind == JsonValueKind.Object
                             && item.TryGetProperty("name", out var nameEl))
                    {
                        var s = nameEl.GetString();
                        if (!string.IsNullOrWhiteSpace(s))
                            journey.VisitedSystems.Add(s!);
                    }
                }
            }

            if (root.TryGetProperty("systemNotes", out var notes)
                && notes.ValueKind == JsonValueKind.Object)
            {
                foreach (var prop in notes.EnumerateObject())
                {
                    if (prop.Value.ValueKind == JsonValueKind.String)
                        journey.SystemNotes[prop.Name] = prop.Value.GetString() ?? "";
                }
            }

            return journey;
        }
        catch
        {
            return null;
        }
    }

    public static JourneyRecord Create(
        string name,
        string commander,
        string startingSystem,
        string description = "")
    {
        var fid = "local";
        var folder = Path.Combine(DataFileLocator.JourneyDirectory, fid);
        Directory.CreateDirectory(folder);
        var stamp = DateTimeOffset.UtcNow.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
        var safe = SafeName.Replace(name.Trim(), "-").Trim('-');
        if (string.IsNullOrWhiteSpace(safe))
            safe = "journey";
        var path = Path.Combine(folder, $"{stamp}-{safe}.json");
        var journey = new JourneyRecord
        {
            FilePath = path,
            Fid = fid,
            Commander = commander,
            Name = name.Trim(),
            Description = description ?? "",
            StartingSystem = startingSystem ?? "",
            StartTime = DateTimeOffset.UtcNow,
            VisitedSystems = string.IsNullOrWhiteSpace(startingSystem)
                ? new List<string>()
                : new List<string> { startingSystem },
        };
        Save(journey);
        return journey;
    }

    public static void Save(JourneyRecord journey)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(journey.FilePath)!);
        var payload = new Dictionary<string, object?>
        {
            ["fid"] = journey.Fid,
            ["commander"] = journey.Commander,
            ["name"] = journey.Name,
            ["description"] = journey.Description,
            ["startingSystem"] = journey.StartingSystem,
            ["startTime"] = journey.StartTime.ToString("o"),
            ["endTime"] = journey.EndTime?.ToString("o"),
            ["visitedSystems"] = journey.VisitedSystems,
            ["systemNotes"] = journey.SystemNotes,
        };
        File.WriteAllText(
            journey.FilePath,
            JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    }

    public static string LoadSystemNote(string systemName)
    {
        if (string.IsNullOrWhiteSpace(systemName))
            return "";
        var path = SystemNotePath(systemName);
        if (!File.Exists(path))
            return "";
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            return GetString(doc.RootElement, "notes") ?? "";
        }
        catch
        {
            return "";
        }
    }

    public static void SaveSystemNote(string systemName, string notes)
    {
        if (string.IsNullOrWhiteSpace(systemName))
            throw new ArgumentException("System name required", nameof(systemName));
        var path = SystemNotePath(systemName);
        var payload = new
        {
            system = systemName,
            notes,
            updated = DateTimeOffset.UtcNow.ToString("o"),
        };
        File.WriteAllText(
            path,
            JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    }

    static string SystemNotePath(string systemName)
    {
        var safe = SafeName.Replace(systemName.Trim(), "_");
        if (string.IsNullOrWhiteSpace(safe))
            safe = "system";
        return Path.Combine(DataFileLocator.SystemNotesDirectory, $"{safe}.json");
    }

    static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;

    static DateTimeOffset? GetDate(JsonElement root, string name)
    {
        var s = GetString(root, name);
        if (string.IsNullOrWhiteSpace(s))
            return null;
        return DateTimeOffset.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var dt)
            ? dt
            : null;
    }
}
