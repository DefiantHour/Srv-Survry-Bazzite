using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SrvSurveyLinuxUi.Services;

public sealed class CmdrDecodeFile
{
    public string FilePath { get; init; } = "";
    public string Fid { get; init; } = "";
    public string Commander { get; init; } = "";
    public HashSet<string> DecodeTheLogs { get; init; } = new(StringComparer.Ordinal);
    public HashSet<string> DecodeTheRuins { get; init; } = new(StringComparer.Ordinal);
    public string LogsMissionActive { get; init; } = "NotStarted";
    public string RuinsMissionActive { get; init; } = "NotStarted";
}

public static class CmdrDecodeStore
{
    public static IReadOnlyList<CmdrDecodeFile> ListCmdrFiles()
    {
        var dir = DataFileLocator.CmdrDirectory;
        var files = Directory.Exists(dir)
            ? Directory.GetFiles(dir, "*.json")
            : Array.Empty<string>();

        // Also accept legacy flat data-folder cmdr files.
        var legacy = Directory.Exists(LinuxPaths.DataDirectory)
            ? Directory.GetFiles(LinuxPaths.DataDirectory, "F*-live.json")
            : Array.Empty<string>();

        return files.Concat(legacy)
            .Distinct(StringComparer.Ordinal)
            .Select(TryLoad)
            .Where(f => f != null)
            .Cast<CmdrDecodeFile>()
            .OrderBy(f => f.Commander)
            .ToList();
    }

    public static CmdrDecodeFile GetOrCreateDefault(string? preferredCommander = null)
    {
        var existing = ListCmdrFiles();
        if (existing.Count > 0)
        {
            if (!string.IsNullOrWhiteSpace(preferredCommander))
            {
                var match = existing.FirstOrDefault(c =>
                    string.Equals(c.Commander, preferredCommander, StringComparison.OrdinalIgnoreCase));
                if (match != null)
                    return match;
            }

            return existing[0];
        }

        var fid = "F00000000";
        var path = Path.Combine(DataFileLocator.CmdrDirectory, $"{fid}-live.json");
        var created = new CmdrDecodeFile
        {
            FilePath = path,
            Fid = fid,
            Commander = preferredCommander ?? "Unknown",
        };
        Save(created);
        return created;
    }

    public static CmdrDecodeFile? TryLoad(string path)
    {
        if (!File.Exists(path))
            return null;
        try
        {
            using var stream = File.OpenRead(path);
            using var doc = JsonDocument.Parse(stream);
            var root = doc.RootElement;
            return new CmdrDecodeFile
            {
                FilePath = path,
                Fid = GetString(root, "fid")
                    ?? Path.GetFileNameWithoutExtension(path).Split('-')[0],
                Commander = GetString(root, "commander") ?? Path.GetFileNameWithoutExtension(path),
                DecodeTheLogs = ReadStringSet(root, "decodeTheLogs"),
                DecodeTheRuins = ReadStringSet(root, "decodeTheRuins"),
                LogsMissionActive = GetString(root, "decodeTheLogsMissionActive") ?? "NotStarted",
                RuinsMissionActive = GetString(root, "decodeTheRuinsMissionActive") ?? "NotStarted",
            };
        }
        catch
        {
            return null;
        }
    }

    public static void Save(CmdrDecodeFile file)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(file.FilePath)!);
        JsonObject root;
        if (File.Exists(file.FilePath))
        {
            try
            {
                root = JsonNode.Parse(File.ReadAllText(file.FilePath)) as JsonObject
                       ?? new JsonObject();
            }
            catch
            {
                root = new JsonObject();
            }
        }
        else
        {
            root = new JsonObject();
        }

        root["fid"] = file.Fid;
        root["commander"] = file.Commander;
        root["isOdyssey"] = true;
        root["decodeTheLogsMissionActive"] = file.LogsMissionActive;
        root["decodeTheRuinsMissionActive"] = file.RuinsMissionActive;
        root["decodeTheLogs"] = new JsonArray(
            file.DecodeTheLogs.OrderBy(x => x, StringComparer.Ordinal)
                .Select(s => JsonValue.Create(s))
                .ToArray());
        root["decodeTheRuins"] = new JsonArray(
            file.DecodeTheRuins.OrderBy(x => x, StringComparer.Ordinal)
                .Select(s => JsonValue.Create(s))
                .ToArray());

        File.WriteAllText(
            file.FilePath,
            root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
    }

    static HashSet<string> ReadStringSet(JsonElement root, string name)
    {
        var set = new HashSet<string>(StringComparer.Ordinal);
        if (!root.TryGetProperty(name, out var el))
            return set;
        if (el.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in el.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String)
                {
                    var s = item.GetString();
                    if (!string.IsNullOrWhiteSpace(s))
                        set.Add(s);
                }
            }
        }

        return set;
    }

    static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;
}
