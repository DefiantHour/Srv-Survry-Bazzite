using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// Reads and writes <c>bodyFlags.&lt;body&gt;.first_foot</c> on an existing commander file.
/// Does not create a commander record.
/// </summary>
public static class CmdrBodyFlags
{
    public static bool? TryGetFirstFoot(string? commander, string? body)
    {
        var path = FindFile(commander);
        if (path == null || string.IsNullOrWhiteSpace(body))
            return null;
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (!doc.RootElement.TryGetProperty("bodyFlags", out var flags)
                || flags.ValueKind != JsonValueKind.Object)
                return null;
            foreach (var prop in flags.EnumerateObject())
            {
                if (!string.Equals(prop.Name, body, StringComparison.OrdinalIgnoreCase))
                    continue;
                if (prop.Value.ValueKind != JsonValueKind.Object)
                    return null;
                if (prop.Value.TryGetProperty("first_foot", out var ff)
                    && (ff.ValueKind is JsonValueKind.True or JsonValueKind.False))
                    return ff.GetBoolean();
                return null;
            }
            return null;
        }
        catch
        {
            return null;
        }
    }

    public static bool TrySetFirstFoot(string? commander, string? body, bool value)
    {
        var path = FindFile(commander);
        if (path == null || string.IsNullOrWhiteSpace(body))
            return false;
        try
        {
            var root = JsonNode.Parse(File.ReadAllText(path)) as JsonObject ?? new JsonObject();
            var flags = root["bodyFlags"] as JsonObject ?? new JsonObject();
            JsonObject? match = null;
            string? matchKey = null;
            foreach (var prop in flags)
            {
                if (!string.Equals(prop.Key, body, StringComparison.OrdinalIgnoreCase))
                    continue;
                match = prop.Value as JsonObject ?? new JsonObject();
                matchKey = prop.Key;
                break;
            }
            match ??= new JsonObject();
            match["first_foot"] = value;
            flags[matchKey ?? body] = match;
            root["bodyFlags"] = flags;
            File.WriteAllText(path, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            return true;
        }
        catch
        {
            return false;
        }
    }

    public static string? FindFile(string? commander)
    {
        if (string.IsNullOrWhiteSpace(commander))
            return null;
        var dir = Path.Combine(LinuxPaths.DataDirectory, "cmdr");
        if (!Directory.Exists(dir))
            return null;
        foreach (var path in Directory.EnumerateFiles(dir, "*.json"))
        {
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(path));
                var name = doc.RootElement.TryGetProperty("commander", out var el) && el.ValueKind == JsonValueKind.String
                    ? el.GetString()
                    : null;
                if (string.Equals(name, commander, StringComparison.OrdinalIgnoreCase))
                    return path;
            }
            catch
            {
                // skip unreadable files
            }
        }
        return null;
    }
}
