using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

public sealed class CodexEntry
{
    public string EntryId { get; init; } = "";
    public string EnglishName { get; init; } = "";
    public string HudCategory { get; init; } = "";
    public string SubCategory { get; init; } = "";
    public string SubClass { get; init; } = "";
    public long Reward { get; init; }
    public string? ImageUrl { get; init; }
    public string? Name { get; init; }
}

public static class CodexRefStore
{
    static List<CodexEntry>? _cache;
    static string? _cachePath;

    public static void InvalidateCache()
    {
        _cache = null;
        _cachePath = null;
    }

    public static IReadOnlyList<CodexEntry> LoadAll()
    {
        var path = DataFileLocator.CodexRefPath;
        if (_cache != null && _cachePath == path)
            return _cache;

        var list = new List<CodexEntry>();
        if (!File.Exists(path))
        {
            _cache = list;
            _cachePath = path;
            return list;
        }

        try
        {
            using var stream = File.OpenRead(path);
            using var doc = JsonDocument.Parse(stream);
            foreach (var prop in doc.RootElement.EnumerateObject())
            {
                var el = prop.Value;
                if (el.ValueKind != JsonValueKind.Object)
                    continue;
                list.Add(ParseEntry(prop.Name, el));
            }
        }
        catch
        {
            // return whatever we have
        }

        list.Sort((a, b) =>
            string.Compare(a.EnglishName, b.EnglishName, StringComparison.OrdinalIgnoreCase));
        _cache = list;
        _cachePath = path;
        return list;
    }

    /// <summary>
    /// Merge a minimal stub into XDG codexRef when journal import sees an unknown EntryID.
    /// Returns true when a new stub was written.
    /// </summary>
    public static bool EnsureStubEntry(string entryId, string englishName, string hudCategory)
    {
        if (string.IsNullOrWhiteSpace(entryId))
            return false;

        var path = Path.Combine(LinuxPaths.DataDirectory, "codexRef.json");
        Directory.CreateDirectory(LinuxPaths.DataDirectory);

        Dictionary<string, Dictionary<string, object?>> map;
        if (File.Exists(path))
        {
            try
            {
                map = JsonSerializer.Deserialize<Dictionary<string, Dictionary<string, object?>>>(
                          File.ReadAllText(path))
                      ?? new Dictionary<string, Dictionary<string, object?>>();
            }
            catch
            {
                map = new Dictionary<string, Dictionary<string, object?>>();
            }
        }
        else
        {
            // Seed from bundled/stock path when present.
            var stock = DataFileLocator.CodexRefPath;
            if (File.Exists(stock) && !string.Equals(stock, path, StringComparison.Ordinal))
            {
                try
                {
                    File.Copy(stock, path, overwrite: false);
                    map = JsonSerializer.Deserialize<Dictionary<string, Dictionary<string, object?>>>(
                              File.ReadAllText(path))
                          ?? new Dictionary<string, Dictionary<string, object?>>();
                }
                catch
                {
                    map = new Dictionary<string, Dictionary<string, object?>>();
                }
            }
            else
            {
                map = new Dictionary<string, Dictionary<string, object?>>();
            }
        }

        if (map.ContainsKey(entryId))
            return false;

        map[entryId] = new Dictionary<string, object?>
        {
            ["english_name"] = englishName,
            ["hud_category"] = hudCategory,
            ["sub_category"] = "",
            ["sub_class"] = "",
            ["reward"] = 0,
            ["name"] = englishName,
            ["entryid"] = entryId,
            ["source"] = "journal-stub",
        };
        File.WriteAllText(path, JsonSerializer.Serialize(map, JsonOptions));
        InvalidateCache();
        return true;
    }

    static CodexEntry ParseEntry(string entryId, JsonElement el) =>
        new()
        {
            EntryId = entryId,
            EnglishName = GetString(el, "english_name") ?? entryId,
            HudCategory = GetString(el, "hud_category") ?? "",
            SubCategory = GetString(el, "sub_category") ?? "",
            SubClass = GetString(el, "sub_class") ?? "",
            Reward = GetLong(el, "reward"),
            ImageUrl = GetString(el, "image_url"),
            Name = GetString(el, "name"),
        };

    public static HashSet<string> LoadBingoProgress()
    {
        var path = DataFileLocator.CodexBingoProgressPath;
        var set = new HashSet<string>(StringComparer.Ordinal);
        if (!File.Exists(path))
            return set;
        try
        {
            using var stream = File.OpenRead(path);
            using var doc = JsonDocument.Parse(stream);
            if (doc.RootElement.ValueKind == JsonValueKind.Array)
            {
                foreach (var el in doc.RootElement.EnumerateArray())
                {
                    if (el.ValueKind == JsonValueKind.String)
                    {
                        var s = el.GetString();
                        if (!string.IsNullOrWhiteSpace(s))
                            set.Add(s);
                    }
                }
            }
            else if (doc.RootElement.TryGetProperty("completed", out var completed)
                     && completed.ValueKind == JsonValueKind.Array)
            {
                foreach (var el in completed.EnumerateArray())
                {
                    var s = el.GetString();
                    if (!string.IsNullOrWhiteSpace(s))
                        set.Add(s!);
                }
            }
        }
        catch
        {
            // empty
        }

        return set;
    }

    public static void SaveBingoProgress(IEnumerable<string> entryIds)
    {
        var path = DataFileLocator.CodexBingoProgressPath;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var payload = new
        {
            updated = DateTimeOffset.UtcNow.ToString("o"),
            completed = entryIds.Distinct(StringComparer.Ordinal).OrderBy(x => x).ToArray(),
        };
        File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions));
    }

    static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    static string? GetString(JsonElement el, string name) =>
        el.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String
            ? p.GetString()
            : null;

    static long GetLong(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p))
            return 0;
        if (p.ValueKind == JsonValueKind.Number && p.TryGetInt64(out var n))
            return n;
        if (p.ValueKind == JsonValueKind.String
            && long.TryParse(p.GetString(), out var parsed))
            return parsed;
        return 0;
    }
}
