using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace SrvSurveyLinuxUi.Services;

public sealed class CodexImportResult
{
    public string Status { get; init; } = "";
    public int RefEntries { get; init; }
    public int BingoAdded { get; init; }
    public int BingoTotal { get; init; }
    public bool UsedCacheFallback { get; init; }
}

/// <summary>
/// Canonn / journal Codex import into XDG codexRef + bingo progress.
/// </summary>
public static class CodexImportStore
{
    const string CanonnUrl =
        "https://us-central1-canonn-api-236217.cloudfunctions.net/query/codex/ref";
    const string GithubFallbackUrl =
        "https://raw.githubusercontent.com/njthomson/SrvSurvey/refs/heads/main/docs/codexRef.json";

    static readonly HttpClient Http = CreateClient();

    static HttpClient CreateClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
        client.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", WindowsWireIdentity.UserAgent);
        client.DefaultRequestHeaders.TryAddWithoutValidation("Accept", "application/json");
        return client;
    }

    public static async Task<CodexImportResult> ImportCanonnRefAsync(CancellationToken ct = default)
    {
        var dest = Path.Combine(LinuxPaths.DataDirectory, "codexRef.json");
        Directory.CreateDirectory(LinuxPaths.DataDirectory);

        if (NetOffline())
        {
            if (File.Exists(dest) || File.Exists(DataFileLocator.CodexRefPath))
            {
                CodexRefStore.InvalidateCache();
                var count = CodexRefStore.LoadAll().Count;
                return new CodexImportResult
                {
                    Status = $"Network offline — using existing codexRef ({count} entries).",
                    RefEntries = count,
                    BingoTotal = CodexRefStore.LoadBingoProgress().Count,
                    UsedCacheFallback = true,
                };
            }

            return new CodexImportResult
            {
                Status = "Network offline and no local codexRef.json found.",
                UsedCacheFallback = true,
            };
        }

        try
        {
            var json = await DownloadTextAsync(CanonnUrl, ct).ConfigureAwait(false);
            if (!LooksLikeCodexMap(json))
                json = await DownloadTextAsync(GithubFallbackUrl, ct).ConfigureAwait(false);
            File.WriteAllText(dest, json);
            CodexRefStore.InvalidateCache();
            var count = CodexRefStore.LoadAll().Count;
            return new CodexImportResult
            {
                Status = $"Imported Canonn/codexRef → {dest} ({count} entries).",
                RefEntries = count,
                BingoTotal = CodexRefStore.LoadBingoProgress().Count,
            };
        }
        catch (Exception ex)
        {
            // Prefer bundled / existing file.
            var existing = DataFileLocator.CodexRefPath;
            if (File.Exists(existing))
            {
                try
                {
                    if (!string.Equals(existing, dest, StringComparison.Ordinal))
                        File.Copy(existing, dest, overwrite: true);
                }
                catch
                {
                    // ignore copy failure
                }

                CodexRefStore.InvalidateCache();
                var count = CodexRefStore.LoadAll().Count;
                return new CodexImportResult
                {
                    Status = $"Canonn download failed ({ex.Message}); kept local/bundled ref ({count} entries).",
                    RefEntries = count,
                    BingoTotal = CodexRefStore.LoadBingoProgress().Count,
                    UsedCacheFallback = true,
                };
            }

            return new CodexImportResult
            {
                Status = $"Canonn download failed: {ex.Message}",
                UsedCacheFallback = true,
            };
        }
    }

    public static CodexImportResult ImportJournalCodexEntries(string? journalFolder)
    {
        var folder = ResolveJournalFolder(journalFolder);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder))
            return new CodexImportResult { Status = "Journal folder not found." };

        var done = CodexRefStore.LoadBingoProgress();
        var before = done.Count;
        var stubbed = 0;
        var files = Directory.EnumerateFiles(folder, "Journal.*.log")
            .OrderBy(Path.GetFileName, StringComparer.Ordinal)
            .ToList();

        foreach (var path in files)
        {
            foreach (var line in File.ReadLines(path))
            {
                if (string.IsNullOrWhiteSpace(line) || line[0] != '{')
                    continue;
                try
                {
                    using var doc = JsonDocument.Parse(line);
                    var root = doc.RootElement;
                    if (!root.TryGetProperty("event", out var evt)
                        || !string.Equals(evt.GetString(), "CodexEntry", StringComparison.Ordinal))
                        continue;

                    var entryId = GetEntryId(root);
                    if (string.IsNullOrWhiteSpace(entryId))
                        continue;
                    if (done.Add(entryId))
                    {
                        // Ensure a minimal local stub exists when ref is missing this id.
                        if (CodexRefStore.EnsureStubEntry(
                                entryId,
                                GetString(root, "Name_Localised")
                                ?? GetString(root, "Name")
                                ?? entryId,
                                GetString(root, "Category_Localised")
                                ?? GetString(root, "Category")
                                ?? "Unknown"))
                            stubbed++;
                    }
                }
                catch (JsonException)
                {
                    // skip broken lines
                }
            }
        }

        CodexRefStore.SaveBingoProgress(done);
        CodexRefStore.InvalidateCache();
        return new CodexImportResult
        {
            Status =
                $"Journal CodexEntry import: +{done.Count - before} bingo "
                + $"(now {done.Count}); {stubbed} stub(s) merged into XDG codexRef. "
                + $"Scanned {files.Count} journal file(s).",
            BingoAdded = done.Count - before,
            BingoTotal = done.Count,
            RefEntries = CodexRefStore.LoadAll().Count,
        };
    }

    static string? ResolveJournalFolder(string? journalFolder)
    {
        if (!string.IsNullOrWhiteSpace(journalFolder) && Directory.Exists(journalFolder))
            return journalFolder;
        var runtime = RuntimeStateSnapshot.TryLoad();
        return runtime?.JournalFolder;
    }

    static async Task<string> DownloadTextAsync(string url, CancellationToken ct)
    {
        using var response = await Http.GetAsync(url, ct).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
    }

    static bool LooksLikeCodexMap(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            return doc.RootElement.ValueKind == JsonValueKind.Object
                   && doc.RootElement.EnumerateObject().Any();
        }
        catch
        {
            return false;
        }
    }

    static bool NetOffline()
    {
        foreach (var name in new[] { "SRVSURVEY_NET_OFFLINE", "SRVSURVEY_DRY_RUN" })
        {
            var v = Environment.GetEnvironmentVariable(name);
            if (v is "1" or "true" or "TRUE" or "yes" or "YES" or "on" or "ON")
                return true;
        }

        return false;
    }

    static string? GetEntryId(JsonElement root)
    {
        if (root.TryGetProperty("EntryID", out var id))
        {
            if (id.ValueKind == JsonValueKind.Number && id.TryGetInt64(out var n))
                return n.ToString();
            if (id.ValueKind == JsonValueKind.String)
                return id.GetString();
        }

        return GetString(root, "entryid") ?? GetString(root, "EntryId");
    }

    static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;
}
