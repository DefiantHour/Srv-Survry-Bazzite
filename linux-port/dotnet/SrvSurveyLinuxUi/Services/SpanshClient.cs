using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace SrvSurveyLinuxUi.Services;

public sealed class SpanshSystemHit
{
    public string Name { get; init; } = "";
    public long Id64 { get; init; }
    public double? DistanceLy { get; init; }
    public double? X { get; init; }
    public double? Y { get; init; }
    public double? Z { get; init; }

    public override string ToString()
    {
        if (DistanceLy is double d)
            return $"{Name}  ·  {d.ToString("N2", CultureInfo.InvariantCulture)} ly";
        return Id64 > 0 ? $"{Name}  ·  {Id64}" : Name;
    }
}

public sealed class SpanshLookupResult
{
    public IReadOnlyList<SpanshSystemHit> Systems { get; init; } = Array.Empty<SpanshSystemHit>();
    public string Status { get; init; } = "";
    public bool FromCache { get; init; }
    public bool Offline { get; init; }
}

/// <summary>
/// Offline-safe Spansh public API client (same endpoints as Windows Spansh.cs).
/// </summary>
public static class SpanshClient
{
    const string SystemsSearchUrl = "https://spansh.co.uk/api/systems/search";
    const string NameSuggestUrl = "https://spansh.co.uk/api/systems/field_values/system_names?q=";

    static readonly HttpClient Http = CreateClient();

    static HttpClient CreateClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromSeconds(20) };
        client.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", WindowsWireIdentity.UserAgent);
        client.DefaultRequestHeaders.TryAddWithoutValidation("Accept", "application/json");
        return client;
    }

    public static bool IsOffline()
    {
        return EnvTruthy("SRVSURVEY_NET_OFFLINE")
               || EnvTruthy("SRVSURVEY_SPANSH_OFFLINE")
               || EnvTruthy("SRVSURVEY_DRY_RUN");
    }

    public static async Task<SpanshLookupResult> LookupBoxelPrefixAsync(
        string prefix,
        int size = 50,
        CancellationToken ct = default)
    {
        var trimmed = (prefix ?? "").Trim();
        if (string.IsNullOrWhiteSpace(trimmed))
            return new SpanshLookupResult { Status = "Enter a boxel prefix first." };

        var queryName = trimmed.EndsWith('*') ? trimmed : trimmed + "*";
        var cacheKey = "boxel:" + queryName.ToLowerInvariant();
        var payload = BuildNameSearchJson(queryName, size);

        if (IsOffline())
            return FromCacheOrEmpty(cacheKey, offline: true, "Spansh offline — showing cache if available.");

        try
        {
            var json = await PostSystemsSearchAsync(payload, ct).ConfigureAwait(false);
            var hits = ParseSearchResults(json);
            // Prefer prefix filter client-side when Spansh returns fuzzy name matches.
            if (hits.Count == 0)
                hits = await SuggestNamesAsync(trimmed, size, ct).ConfigureAwait(false);
            else
                hits = FilterPrefix(hits, trimmed);

            WriteCache(cacheKey, json, hits);
            return new SpanshLookupResult
            {
                Systems = hits,
                Status = hits.Count == 0
                    ? $"No Spansh systems for prefix '{trimmed}'."
                    : $"Spansh: {hits.Count} system(s) for '{trimmed}'.",
            };
        }
        catch (Exception ex)
        {
            var cached = FromCacheOrEmpty(cacheKey, offline: false, $"Spansh failed ({ex.Message}); showing cache if available.");
            return cached;
        }
    }

    public static async Task<SpanshLookupResult> LookupSphereAsync(
        double x,
        double y,
        double z,
        double radiusLy,
        int size = 50,
        CancellationToken ct = default)
    {
        if (radiusLy <= 0)
            return new SpanshLookupResult { Status = "Radius must be greater than zero." };

        var cacheKey = string.Format(
            CultureInfo.InvariantCulture,
            "sphere:{0:F2},{1:F2},{2:F2},r{3:F2}",
            x, y, z, radiusLy);
        var payload = BuildSphereSearchJson(x, y, z, radiusLy, size);

        if (IsOffline())
            return FromCacheOrEmpty(cacheKey, offline: true, "Spansh offline — showing cache if available.");

        try
        {
            var json = await PostSystemsSearchAsync(payload, ct).ConfigureAwait(false);
            var hits = ParseSearchResults(json);
            WriteCache(cacheKey, json, hits);
            return new SpanshLookupResult
            {
                Systems = hits,
                Status = hits.Count == 0
                    ? $"No Spansh systems within {radiusLy.ToString("N1", CultureInfo.InvariantCulture)} ly."
                    : $"Spansh: {hits.Count} system(s) within {radiusLy.ToString("N1", CultureInfo.InvariantCulture)} ly.",
            };
        }
        catch (Exception ex)
        {
            return FromCacheOrEmpty(cacheKey, offline: false, $"Spansh failed ({ex.Message}); showing cache if available.");
        }
    }

    static string BuildNameSearchJson(string nameValue, int size)
    {
        // Mirrors Windows Spansh.getBoxelSystems (name value may include trailing *).
        return
            "{\"filters\":{\"name\":{\"value\":"
            + JsonSerializer.Serialize(nameValue)
            + "}},\"sort\":[{\"name\":{\"direction\":\"asc\"}}],\"size\":"
            + size.ToString(CultureInfo.InvariantCulture)
            + ",\"page\":0}";
    }

    static string BuildSphereSearchJson(double x, double y, double z, double radiusLy, int size)
    {
        var max = Math.Max(0, radiusLy).ToString("0.###", CultureInfo.InvariantCulture);
        return
            "{\"filters\":{\"distance\":{\"min\":\"0\",\"max\":\""
            + max
            + "\"}},\"sort\":[{\"distance\":{\"direction\":\"asc\"}}],\"size\":"
            + size.ToString(CultureInfo.InvariantCulture)
            + ",\"page\":0,\"reference_coords\":{\"x\":"
            + x.ToString(CultureInfo.InvariantCulture)
            + ",\"y\":"
            + y.ToString(CultureInfo.InvariantCulture)
            + ",\"z\":"
            + z.ToString(CultureInfo.InvariantCulture)
            + "}}";
    }

    static async Task<string> PostSystemsSearchAsync(string payload, CancellationToken ct)
    {
        using var content = new StringContent(payload, Encoding.UTF8, "application/json");
        using var response = await Http.PostAsync(SystemsSearchUrl, content, ct).ConfigureAwait(false);
        var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
            throw new HttpRequestException($"HTTP {(int)response.StatusCode}: {Trim(text, 120)}");
        if (text.Contains("\"error\"", StringComparison.Ordinal))
            throw new InvalidOperationException(Trim(text, 160));
        return text;
    }

    static async Task<List<SpanshSystemHit>> SuggestNamesAsync(string prefix, int size, CancellationToken ct)
    {
        var url = NameSuggestUrl + Uri.EscapeDataString(prefix);
        using var response = await Http.GetAsync(url, ct).ConfigureAwait(false);
        var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
            return new List<SpanshSystemHit>();

        var hits = new List<SpanshSystemHit>();
        using var doc = JsonDocument.Parse(text);
        if (!doc.RootElement.TryGetProperty("min_max", out var arr)
            || arr.ValueKind != JsonValueKind.Array)
            return hits;

        foreach (var el in arr.EnumerateArray())
        {
            var name = GetString(el, "name");
            if (string.IsNullOrWhiteSpace(name))
                continue;
            if (!name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                continue;
            hits.Add(new SpanshSystemHit
            {
                Name = name,
                Id64 = GetLong(el, "id64"),
                X = GetDouble(el, "x"),
                Y = GetDouble(el, "y"),
                Z = GetDouble(el, "z"),
            });
            if (hits.Count >= size)
                break;
        }

        return hits;
    }

    static List<SpanshSystemHit> ParseSearchResults(string json)
    {
        var hits = new List<SpanshSystemHit>();
        using var doc = JsonDocument.Parse(json);
        if (!doc.RootElement.TryGetProperty("results", out var results)
            || results.ValueKind != JsonValueKind.Array)
            return hits;

        foreach (var el in results.EnumerateArray())
        {
            var name = GetString(el, "name");
            if (string.IsNullOrWhiteSpace(name))
                continue;
            hits.Add(new SpanshSystemHit
            {
                Name = name!,
                Id64 = GetLong(el, "id64"),
                DistanceLy = GetDouble(el, "distance"),
                X = GetDouble(el, "x"),
                Y = GetDouble(el, "y"),
                Z = GetDouble(el, "z"),
            });
        }

        return hits;
    }

    static List<SpanshSystemHit> FilterPrefix(IEnumerable<SpanshSystemHit> hits, string prefix)
    {
        var list = new List<SpanshSystemHit>();
        foreach (var hit in hits)
        {
            if (hit.Name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                list.Add(hit);
        }

        return list.Count > 0 ? list : hits as List<SpanshSystemHit> ?? new List<SpanshSystemHit>(hits);
    }

    static SpanshLookupResult FromCacheOrEmpty(string cacheKey, bool offline, string status)
    {
        var cached = ReadCache(cacheKey);
        if (cached.Count > 0)
        {
            return new SpanshLookupResult
            {
                Systems = cached,
                Status = status + $" ({cached.Count} cached)",
                FromCache = true,
                Offline = offline,
            };
        }

        return new SpanshLookupResult
        {
            Status = status + " (no cache)",
            FromCache = false,
            Offline = offline,
        };
    }

    static void WriteCache(string cacheKey, string rawJson, IReadOnlyList<SpanshSystemHit> hits)
    {
        try
        {
            var dir = DataFileLocator.SpanshCacheDirectory;
            Directory.CreateDirectory(dir);
            var path = CachePath(cacheKey);
            var payload = new Dictionary<string, object?>
            {
                ["updated"] = DateTimeOffset.UtcNow.ToString("o"),
                ["key"] = cacheKey,
                ["count"] = hits.Count,
                ["systems"] = hits,
                ["raw"] = rawJson.Length > 200_000 ? null : rawJson,
            };
            File.WriteAllText(
                path,
                JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch
        {
            // cache is best-effort
        }
    }

    static List<SpanshSystemHit> ReadCache(string cacheKey)
    {
        var path = CachePath(cacheKey);
        if (!File.Exists(path))
            return new List<SpanshSystemHit>();
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (!doc.RootElement.TryGetProperty("systems", out var systems)
                || systems.ValueKind != JsonValueKind.Array)
                return new List<SpanshSystemHit>();
            var list = new List<SpanshSystemHit>();
            foreach (var el in systems.EnumerateArray())
            {
                var name = GetString(el, "Name") ?? GetString(el, "name");
                if (string.IsNullOrWhiteSpace(name))
                    continue;
                list.Add(new SpanshSystemHit
                {
                    Name = name!,
                    Id64 = GetLong(el, "Id64") != 0 ? GetLong(el, "Id64") : GetLong(el, "id64"),
                    DistanceLy = GetDouble(el, "DistanceLy") ?? GetDouble(el, "distance"),
                    X = GetDouble(el, "X") ?? GetDouble(el, "x"),
                    Y = GetDouble(el, "Y") ?? GetDouble(el, "y"),
                    Z = GetDouble(el, "Z") ?? GetDouble(el, "z"),
                });
            }

            return list;
        }
        catch
        {
            return new List<SpanshSystemHit>();
        }
    }

    public const string BodySearchUrl = "https://spansh.co.uk/api/bodies/search";
    public const string RouteResultUrl = "https://spansh.co.uk/api/results/";

    public static async Task<(bool Ok, string Status, string Json)> SearchBodiesAsync(
        string queryJson,
        CancellationToken ct = default)
    {
        if (IsOffline())
            return (false, "Spansh offline — body search skipped.", "");
        if (string.IsNullOrWhiteSpace(queryJson))
            return (false, "Empty body search.", "");
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Post, BodySearchUrl)
            {
                Content = new StringContent(queryJson, Encoding.UTF8, "application/json"),
            };
            using var response = await Http.SendAsync(req, ct).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return (false, $"Spansh HTTP {(int)response.StatusCode}: {Trim(text, 160)}", "");
            if (text.Contains("Invalid request", StringComparison.Ordinal))
                return (false, "Spansh rejected the body search.", "");
            return (true, "Spansh body search OK", text);
        }
        catch (Exception ex)
        {
            return (false, "Spansh body search failed: " + ex.Message, "");
        }
    }

    public static async Task<(bool Ok, string Status, string Json)> FetchRouteAsync(
        string routeId,
        CancellationToken ct = default)
    {
        var id = (routeId ?? "").Trim();
        if (string.IsNullOrWhiteSpace(id))
            return (false, "Paste a Spansh route id.", "");
        if (IsOffline())
            return (false, "Spansh offline — route import skipped.", "");
        try
        {
            using var response = await Http.GetAsync(RouteResultUrl + Uri.EscapeDataString(id), ct)
                .ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return (false, $"Spansh HTTP {(int)response.StatusCode}: {Trim(text, 160)}", "");
            return (true, "Route loaded", text);
        }
        catch (Exception ex)
        {
            return (false, "Route import failed: " + ex.Message, "");
        }
    }

    static string CachePath(string cacheKey)
    {
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(cacheKey)))[..16].ToLowerInvariant();
        return Path.Combine(DataFileLocator.SpanshCacheDirectory, hash + ".json");
    }

    static bool EnvTruthy(string name)
    {
        var v = Environment.GetEnvironmentVariable(name);
        if (string.IsNullOrWhiteSpace(v))
            return false;
        return v is "1" or "true" or "TRUE" or "yes" or "YES" or "on" or "ON";
    }

    static string Trim(string text, int max) =>
        text.Length <= max ? text : text[..max] + "…";

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
        if (p.ValueKind == JsonValueKind.String && long.TryParse(p.GetString(), out var parsed))
            return parsed;
        return 0;
    }

    static double? GetDouble(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p))
            return null;
        if (p.ValueKind == JsonValueKind.Number && p.TryGetDouble(out var d))
            return d;
        if (p.ValueKind == JsonValueKind.String
            && double.TryParse(p.GetString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed))
            return parsed;
        return null;
    }

    /// <summary>GET field_values/system_names. Offline never GETs.</summary>
    public static async Task<SpanshLookupResult> LookupSystemNamesAsync(
        string systemName,
        CancellationToken ct = default)
    {
        var name = (systemName ?? "").Trim();
        if (string.IsNullOrWhiteSpace(name))
            return new SpanshLookupResult { Status = "Enter a system name." };
        if (IsOffline())
            return new SpanshLookupResult { Offline = true, Status = "Spansh offline — name lookup skipped." };
        try
        {
            using var response = await Http.GetAsync(NameSuggestUrl + Uri.EscapeDataString(name), ct)
                .ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return new SpanshLookupResult { Status = $"Spansh HTTP {(int)response.StatusCode}." };
            var hits = new List<SpanshSystemHit>();
            using var doc = JsonDocument.Parse(text);
            if (doc.RootElement.TryGetProperty("min_max", out var arr) && arr.ValueKind == JsonValueKind.Array)
            {
                foreach (var el in arr.EnumerateArray())
                {
                    var hitName = GetString(el, "name");
                    if (string.IsNullOrWhiteSpace(hitName))
                        continue;
                    hits.Add(new SpanshSystemHit
                    {
                        Name = hitName!,
                        Id64 = GetLong(el, "id64"),
                    });
                }
            }
            return new SpanshLookupResult
            {
                Systems = hits,
                Status = hits.Count == 0 ? "No Spansh name match." : $"Spansh: {hits.Count} name(s).",
            };
        }
        catch (Exception ex)
        {
            return new SpanshLookupResult { Status = "Spansh name lookup failed: " + ex.Message };
        }
    }

    /// <summary>GET api/dump/{id64}/. Offline never GETs.</summary>
    public static async Task<(bool Ok, string Status, string Json)> GetSystemDumpAsync(
        long systemAddress,
        CancellationToken ct = default)
    {
        if (systemAddress <= 0)
            return (false, "Missing system address.", "");
        if (IsOffline())
            return (false, "Spansh offline — dump skipped.", "");
        var url = "https://spansh.co.uk/api/dump/" + systemAddress.ToString(CultureInfo.InvariantCulture) + "/";
        try
        {
            using var response = await Http.GetAsync(url, ct).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return (false, $"Spansh HTTP {(int)response.StatusCode}.", "");
            return (true, "Spansh dump loaded.", text);
        }
        catch (Exception ex)
        {
            return (false, "Spansh dump failed: " + ex.Message, "");
        }
    }

    /// <summary>One GET of api/results/{id}. Does not poll. Offline never GETs.</summary>
    public static async Task<(bool Ok, string Status, string Json)> GetRouteResultAsync(
        string routeId,
        CancellationToken ct = default)
    {
        var id = (routeId ?? "").Trim();
        if (string.IsNullOrWhiteSpace(id))
            return (false, "Missing route id.", "");
        if (IsOffline())
            return (false, "Spansh offline — route skipped.", "");
        try
        {
            using var response = await Http.GetAsync(RouteResultUrl + Uri.EscapeDataString(id), ct)
                .ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return (false, $"Spansh HTTP {(int)response.StatusCode}.", "");
            return (true, "Spansh route loaded.", text);
        }
        catch (Exception ex)
        {
            return (false, "Spansh route failed: " + ex.Message, "");
        }
    }
}
