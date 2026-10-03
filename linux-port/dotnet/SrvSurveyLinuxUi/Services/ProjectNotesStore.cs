using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

public sealed class ProjectNote
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string SystemName { get; set; } = "";
    public string Notes { get; set; } = "";
    public string RavenUrl { get; set; } = "";
    public bool IsLocalPrimary { get; set; }
    public string Updated { get; set; } = "";
}

public sealed class ProjectNotesDocument
{
    public List<ProjectNote> Projects { get; set; } = new();
    public string? LinkedFcSummary { get; set; }
}

public static class ProjectNotesStore
{
    const string DefaultRaven = "https://ravencolonial.com";

    public static ProjectNotesDocument Load()
    {
        var path = DataFileLocator.ProjectNotesPath;
        if (!File.Exists(path))
            return new ProjectNotesDocument();
        try
        {
            var doc = JsonSerializer.Deserialize<ProjectNotesDocument>(
                File.ReadAllText(path),
                JsonOptions);
            return doc ?? new ProjectNotesDocument();
        }
        catch
        {
            return new ProjectNotesDocument();
        }
    }

    public static void Save(ProjectNotesDocument doc)
    {
        var path = DataFileLocator.ProjectNotesPath;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(doc, JsonOptions));
    }

    public static ProjectNote Create(string name, string systemName, string notes = "")
    {
        var doc = Load();
        var note = new ProjectNote
        {
            Id = Guid.NewGuid().ToString("N")[..12],
            Name = string.IsNullOrWhiteSpace(name) ? "New Project" : name.Trim(),
            SystemName = systemName?.Trim() ?? "",
            Notes = notes ?? "",
            RavenUrl = DefaultRaven,
            IsLocalPrimary = doc.Projects.Count == 0,
            Updated = DateTimeOffset.UtcNow.ToString("o"),
        };
        doc.Projects.Add(note);
        Save(doc);
        return note;
    }

    public static ProjectNote? GetPrimaryOrFirst()
    {
        var doc = Load();
        return doc.Projects.FirstOrDefault(p => p.IsLocalPrimary)
               ?? doc.Projects.FirstOrDefault();
    }

    public static string FcSummaryOrFallback()
    {
        var sidecar = TryReadPresenterFcSummary();
        if (!string.IsNullOrWhiteSpace(sidecar))
            return sidecar!;

        var doc = Load();
        if (!string.IsNullOrWhiteSpace(doc.LinkedFcSummary))
            return "Last-known local notes: " + doc.LinkedFcSummary!;

        return "FC cargo managed by presenter/Python RavenColonial sidecar. "
               + "No XDG fc-cargo.json yet — enable gs.buildProjectsShowSumFC and run present, "
               + "or edit Linked FC Summary under Local Project.";
    }

    static string? TryReadPresenterFcSummary()
    {
        var candidates = new[]
        {
            DataFileLocator.FcCargoSnapshotPath,
            Path.Combine(LinuxPaths.DataDirectory, "fc-cargo-summary.txt"),
            Path.Combine(LinuxPaths.DataDirectory, "raven-fc-cache.json"),
        };
        foreach (var path in candidates)
        {
            try
            {
                if (!File.Exists(path))
                    continue;
                if (path.EndsWith(".txt", StringComparison.OrdinalIgnoreCase))
                {
                    var text = File.ReadAllText(path).Trim();
                    if (!string.IsNullOrWhiteSpace(text))
                        return text;
                    continue;
                }

                using var doc = JsonDocument.Parse(File.ReadAllText(path));
                var root = doc.RootElement;
                if (root.TryGetProperty("summary", out var s)
                    && s.ValueKind == JsonValueKind.String
                    && !string.IsNullOrWhiteSpace(s.GetString()))
                    return s.GetString();

                var updated = GetJsonString(root, "updated") ?? "(unknown time)";
                var cmdr = GetJsonString(root, "commander") ?? "?";
                var fcCount = GetJsonInt(root, "fc_count")
                              ?? GetJsonInt(root, "fcCount")
                              ?? 0;

                if (root.TryGetProperty("cargo", out var cargo)
                    && cargo.ValueKind == JsonValueKind.Object)
                {
                    var rows = cargo.EnumerateObject()
                        .Select(p =>
                        {
                            var qty = p.Value.ValueKind == JsonValueKind.Number
                                      && p.Value.TryGetInt32(out var q)
                                ? q
                                : 0;
                            return (Name: p.Name, Qty: qty);
                        })
                        .Where(r => r.Qty > 0)
                        .OrderByDescending(r => r.Qty)
                        .ThenBy(r => r.Name, StringComparer.OrdinalIgnoreCase)
                        .Take(24)
                        .ToList();
                    var lines = new List<string>
                    {
                        $"Presenter FC snapshot · cmdr {cmdr} · {fcCount} FC · updated {updated}",
                    };
                    if (rows.Count == 0)
                        lines.Add("(no cargo quantities in snapshot)");
                    else
                    {
                        foreach (var row in rows)
                            lines.Add($"{row.Name}: {row.Qty}");
                        if (cargo.EnumerateObject().Count() > rows.Count)
                            lines.Add("…");
                    }

                    return string.Join(Environment.NewLine, lines);
                }

                return $"Presenter FC cache: {fcCount} carrier(s) · {path}";
            }
            catch
            {
                // try next
            }
        }

        return null;
    }

    static string? GetJsonString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;

    static int? GetJsonInt(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el))
            return null;
        if (el.ValueKind == JsonValueKind.Number && el.TryGetInt32(out var n))
            return n;
        return null;
    }

    static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };
}
