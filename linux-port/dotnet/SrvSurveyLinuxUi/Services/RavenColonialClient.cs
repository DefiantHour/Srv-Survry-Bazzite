using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace SrvSurveyLinuxUi.Services;

public sealed class RavenColonialResult
{
    public bool Ok { get; init; }
    public bool Skipped { get; init; }
    public bool DryRun { get; init; }
    public int? StatusCode { get; init; }
    public string Body { get; init; } = "";
    public string Status { get; init; } = "";
}

public sealed class RavenProject
{
    public string BuildId { get; init; } = "";
    public long MarketId { get; init; }
    public long SystemAddress { get; init; }
    public string? SystemName { get; init; }
}

/// <summary>
/// Offline-safe RavenColonial mutating client (publishFC / updateSystem / setPrimary / updateSysBodies).
/// RCC API key is read from the XDG secrets file — never from main config.
/// </summary>
public static class RavenColonialClient
{
    const string DefaultSvcUri =
        "https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net";

    static readonly HttpClient Http = CreateClient();
    static readonly JsonSerializerOptions JsonWrite = new()
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    };

    static HttpClient CreateClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromSeconds(12) };
        client.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", WindowsWireIdentity.UserAgent);
        client.DefaultRequestHeaders.TryAddWithoutValidation("Accept", "application/json");
        return client;
    }

    public static bool IsOffline()
    {
        return EnvTruthy("SRVSURVEY_NET_OFFLINE")
               || EnvTruthy("SRVSURVEY_RCC_OFFLINE")
               || EnvTruthy("SRVSURVEY_DRY_RUN")
               || EnvTruthy("SRVSURVEY_RCC_DRY_RUN");
    }

    public static bool IsDryRunOnly() =>
        EnvTruthy("SRVSURVEY_DRY_RUN") || EnvTruthy("SRVSURVEY_RCC_DRY_RUN");

    public static string ResolveSvcUri()
    {
        var env = Environment.GetEnvironmentVariable("SRVSURVEY_BUILD_PROJECTS_URL")
                  ?? Environment.GetEnvironmentVariable("SRVSURVEY_RCC_URL")
                  ?? "";
        env = env.Trim().TrimEnd('/');
        if (!string.IsNullOrWhiteSpace(env))
            return env;
        try
        {
            var cfg = new AppConfigStore();
            cfg.Reload();
            if (!string.IsNullOrWhiteSpace(cfg.BuildProjectsUrl))
                return cfg.BuildProjectsUrl;
        }
        catch
        {
            // fall through to the Windows default Azure host
        }

        return DefaultSvcUri;
    }

    public static string? ReadRccApiKey()
    {
        try
        {
            var path = Path.Combine(LinuxPaths.ConfigDirectory, "secrets");
            if (!File.Exists(path))
                return null;
            foreach (var line in File.ReadAllLines(path))
            {
                var raw = line.Trim();
                if (raw.Length == 0 || raw.StartsWith('#') || !raw.Contains('='))
                    continue;
                var idx = raw.IndexOf('=');
                var key = raw[..idx].Trim();
                var value = raw[(idx + 1)..].Trim();
                if (key == "rcc_api_key" && value.Length > 0)
                    return value;
            }
        }
        catch
        {
            // secrets are best-effort
        }

        return null;
    }

    public static async Task<RavenColonialResult> PublishFcAsync(
        string fid,
        long marketId,
        string name,
        string displayName,
        CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(fid) || marketId <= 0)
            return Skip("Missing FID or market id.");

        var key = ReadRccApiKey();
        if (string.IsNullOrWhiteSpace(key))
            return Skip("No RCC API key in XDG secrets (Settings → External Data).");

        if (EnvTruthy("SRVSURVEY_NET_OFFLINE") || EnvTruthy("SRVSURVEY_RCC_OFFLINE"))
            return Skip("RCC offline — publish FC skipped.");

        var url = $"{ResolveSvcUri()}/api/fc/{marketId}";
        var payload = BuildPublishFcJson(marketId, name, displayName);

        if (IsDryRunOnly())
            return Dry(url, payload);

        return await SendAsync(HttpMethod.Put, url, payload, key, ct).ConfigureAwait(false);
    }

    /// <summary>Windows <c>JsonConvert.SerializeObject(FleetCarrier)</c> with cargo null.</summary>
    public static string BuildPublishFcJson(long marketId, string? name, string? displayName) =>
        JsonSerializer.Serialize(new
        {
            marketId,
            name = name ?? "",
            displayName = displayName ?? "",
            cargo = (Dictionary<string, int>?)null,
        }, JsonWrite);

    public static async Task<RavenColonialResult> UpdateSystemAsync(
        string fid,
        string nameOrNum,
        string? architect = null,
        CancellationToken ct = default)
    {
        return await UpdateSystemSitesAsync(
            fid,
            nameOrNum,
            update: null,
            delete: null,
            architect: architect,
            ct: ct).ConfigureAwait(false);
    }

    /// <summary>
    /// PUT /api/v2/system/{nameOrNum}/sites — Windows RavenColonial.updateSystem / SitesPut.
    /// </summary>
    public static async Task<RavenColonialResult> UpdateSystemSitesAsync(
        string fid,
        string nameOrNum,
        IReadOnlyList<Dictionary<string, object?>>? update = null,
        IReadOnlyList<string>? delete = null,
        string? architect = null,
        bool? open = null,
        string? reserveLevel = null,
        CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(fid) || string.IsNullOrWhiteSpace(nameOrNum))
            return Skip("Missing FID or system name.");

        var key = ReadRccApiKey();
        if (string.IsNullOrWhiteSpace(key))
            return Skip("No RCC API key in XDG secrets (Settings → External Data).");

        if (EnvTruthy("SRVSURVEY_NET_OFFLINE") || EnvTruthy("SRVSURVEY_RCC_OFFLINE"))
            return Skip("RCC offline — update system skipped.");

        var url = $"{ResolveSvcUri()}/api/v2/system/{Uri.EscapeDataString(nameOrNum.Trim())}/sites";
        var data = new Dictionary<string, object?>
        {
            ["update"] = update ?? Array.Empty<Dictionary<string, object?>>(),
            ["delete"] = delete ?? Array.Empty<string>(),
        };
        if (!string.IsNullOrWhiteSpace(architect))
            data["architect"] = architect.Trim();
        if (open.HasValue)
            data["open"] = open.Value;
        if (!string.IsNullOrWhiteSpace(reserveLevel))
            data["reserveLevel"] = reserveLevel.Trim();
        var payload = JsonSerializer.Serialize(data);

        if (IsDryRunOnly())
            return Dry(url, payload);

        return await SendAsync(HttpMethod.Put, url, payload, key, ct).ConfigureAwait(false);
    }

    /// <summary>GET /api/v2/system/{nameOrNum} — load system sites/bodies (offline returns empty).</summary>
    public static async Task<(bool Ok, string? Json, string Status)> GetSystemAsync(
        string nameOrNum,
        CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(nameOrNum))
            return (false, null, "Missing system name or id64.");

        if (EnvTruthy("SRVSURVEY_NET_OFFLINE") || EnvTruthy("SRVSURVEY_RCC_OFFLINE"))
            return (false, null, "RCC offline — get system skipped.");

        var url = $"{ResolveSvcUri()}/api/v2/system/{Uri.EscapeDataString(nameOrNum.Trim())}";
        if (IsDryRunOnly())
            return (true, "{\"name\":\"" + nameOrNum.Trim() + "\",\"sites\":[],\"bodies\":[]}", "RCC dry-run get system");

        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, url);
            using var response = await Http.SendAsync(req, ct).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return (false, null, $"RCC HTTP {(int)response.StatusCode}: {Trim(text, 120)}");
            return (true, text, $"RCC HTTP {(int)response.StatusCode} OK");
        }
        catch (Exception ex)
        {
            return (false, null, "RCC get system failed: " + ex.Message);
        }
    }

    /// <summary>GET /api/cmdr/{cmdr}/active — offline-safe summary (no Python Cli).</summary>
    public static async Task<IReadOnlyList<RavenProject>> GetActiveProjectsAsync(
        string? cmdr,
        CancellationToken ct = default)
    {
        var name = (cmdr ?? "").Trim();
        if (string.IsNullOrWhiteSpace(name) || EnvTruthy("SRVSURVEY_NET_OFFLINE") || EnvTruthy("SRVSURVEY_RCC_OFFLINE"))
            return Array.Empty<RavenProject>();
        if (IsDryRunOnly())
            return Array.Empty<RavenProject>();

        var url = $"{ResolveSvcUri()}/api/cmdr/{Uri.EscapeDataString(name)}/active";
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, url);
            using var response = await Http.SendAsync(req, ct).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode || string.IsNullOrWhiteSpace(text))
                return Array.Empty<RavenProject>();
            using var doc = JsonDocument.Parse(text);
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
                return Array.Empty<RavenProject>();
            var list = new List<RavenProject>();
            foreach (var row in doc.RootElement.EnumerateArray())
            {
                if (row.ValueKind != JsonValueKind.Object)
                    continue;
                var buildId = row.TryGetProperty("buildId", out var idEl) ? idEl.GetString() : null;
                if (string.IsNullOrWhiteSpace(buildId))
                    continue;
                list.Add(new RavenProject
                {
                    BuildId = buildId!,
                    MarketId = row.TryGetProperty("marketId", out var mid) && mid.TryGetInt64(out var market)
                        ? market
                        : 0,
                    SystemAddress = row.TryGetProperty("systemAddress", out var addr) && addr.TryGetInt64(out var sa)
                        ? sa
                        : 0,
                    SystemName = row.TryGetProperty("systemName", out var sys) && sys.ValueKind == JsonValueKind.String
                        ? sys.GetString()
                        : null,
                });
            }

            return list;
        }
        catch
        {
            return Array.Empty<RavenProject>();
        }
    }

    public static async Task<string?> GetPrimaryAsync(string? cmdr, CancellationToken ct = default)
    {
        var name = (cmdr ?? "").Trim();
        if (string.IsNullOrWhiteSpace(name) || EnvTruthy("SRVSURVEY_NET_OFFLINE") || EnvTruthy("SRVSURVEY_RCC_OFFLINE"))
            return null;
        if (IsDryRunOnly())
            return null;
        var url = $"{ResolveSvcUri()}/api/cmdr/{Uri.EscapeDataString(name)}/primary";
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, url);
            using var response = await Http.SendAsync(req, ct).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return null;
            var value = JsonSerializer.Deserialize<string>(string.IsNullOrWhiteSpace(text) ? "\"\"" : text);
            return string.IsNullOrWhiteSpace(value) ? null : value;
        }
        catch
        {
            return null;
        }
    }

    public static string? BuildIdForDock(IEnumerable<RavenProject> projects, long systemAddress, long marketId)
    {
        if (systemAddress <= 0 || marketId <= 0)
            return null;
        return projects.FirstOrDefault(p => p.SystemAddress == systemAddress && p.MarketId == marketId)?.BuildId;
    }

    public static async Task<string> FetchActiveProjectsSummaryAsync(
        string? cmdr,
        CancellationToken ct = default)
    {
        var name = (cmdr ?? "").Trim();
        if (string.IsNullOrWhiteSpace(name))
            return "No commander — start the presenter first.";

        if (EnvTruthy("SRVSURVEY_NET_OFFLINE") || EnvTruthy("SRVSURVEY_RCC_OFFLINE"))
            return "0 active project(s) (offline-safe)";

        if (IsDryRunOnly())
            return "0 active project(s) (dry-run)";

        var url = $"{ResolveSvcUri()}/api/cmdr/{Uri.EscapeDataString(name)}/active";
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, url);
            using var response = await Http.SendAsync(req, ct).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return $"RCC HTTP {(int)response.StatusCode}: {Trim(text, 120)}";

            using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(text) ? "[]" : text);
            var count = doc.RootElement.ValueKind == JsonValueKind.Array
                ? doc.RootElement.GetArrayLength()
                : 0;
            return $"{count} active project(s)";
        }
        catch (Exception ex)
        {
            return "RCC fetch active failed: " + ex.Message;
        }
    }

    public static async Task<RavenColonialResult> SetPrimaryAsync(
        string cmdr,
        string? buildId,
        CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(cmdr))
            return Skip("Missing commander name.");

        if (EnvTruthy("SRVSURVEY_NET_OFFLINE") || EnvTruthy("SRVSURVEY_RCC_OFFLINE"))
            return Skip("RCC offline — set primary skipped.");

        var baseUri = ResolveSvcUri();
        string url;
        HttpMethod method;
        if (string.IsNullOrWhiteSpace(buildId))
        {
            url = $"{baseUri}/api/cmdr/{Uri.EscapeDataString(cmdr.Trim())}/primary/";
            method = HttpMethod.Delete;
        }
        else
        {
            url =
                $"{baseUri}/api/cmdr/{Uri.EscapeDataString(cmdr.Trim())}/primary/{Uri.EscapeDataString(buildId.Trim())}";
            method = HttpMethod.Put;
        }

        if (IsDryRunOnly())
            return Dry(url, method.Method);

        return await SendAsync(method, url, null, apiKey: null, ct).ConfigureAwait(false);
    }

    public static async Task<RavenColonialResult> UpdateSysBodiesAsync(
        long address,
        string bodiesJson = "[]",
        CancellationToken ct = default)
    {
        if (address <= 0)
            return Skip("Missing system address.");

        if (EnvTruthy("SRVSURVEY_NET_OFFLINE") || EnvTruthy("SRVSURVEY_RCC_OFFLINE"))
            return Skip("RCC offline — update bodies skipped.");

        var url = $"{ResolveSvcUri()}/api/v2/system/{Uri.EscapeDataString(address.ToString())}/bodies";
        var payload = string.IsNullOrWhiteSpace(bodiesJson) ? "[]" : bodiesJson.Trim();

        if (IsDryRunOnly())
            return Dry(url, payload);

        return await SendAsync(HttpMethod.Put, url, payload, apiKey: null, ct).ConfigureAwait(false);
    }

    static async Task<RavenColonialResult> SendAsync(
        HttpMethod method,
        string url,
        string? payload,
        string? apiKey,
        CancellationToken ct)
    {
        try
        {
            using var req = new HttpRequestMessage(method, url);
            if (payload != null)
                req.Content = new StringContent(payload, Encoding.UTF8, "application/json");
            if (!string.IsNullOrWhiteSpace(apiKey))
                req.Headers.TryAddWithoutValidation("rcc-key", apiKey);

            using var response = await Http.SendAsync(req, ct).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            var code = (int)response.StatusCode;
            var ok = response.IsSuccessStatusCode;
            return new RavenColonialResult
            {
                Ok = ok,
                StatusCode = code,
                Body = text.Length > 400 ? text[..400] + "…" : text,
                Status = ok
                    ? $"RCC HTTP {code} OK"
                    : $"RCC HTTP {code}: {Trim(text, 120)}",
            };
        }
        catch (Exception ex)
        {
            return new RavenColonialResult
            {
                Ok = false,
                Body = ex.Message,
                Status = $"RCC failed: {ex.Message}",
            };
        }
    }

    static RavenColonialResult Skip(string reason) =>
        new() { Skipped = true, Status = reason, Body = reason };

    static RavenColonialResult Dry(string url, string detail) =>
        new()
        {
            Ok = true,
            DryRun = true,
            Status = "RCC dry-run — no network",
            Body = url + " :: " + Trim(detail, 160),
        };

    static bool EnvTruthy(string name)
    {
        var v = Environment.GetEnvironmentVariable(name);
        if (string.IsNullOrWhiteSpace(v))
            return false;
        return v is "1" or "true" or "TRUE" or "yes" or "YES" or "on" or "ON";
    }

    static string Trim(string text, int max) =>
        text.Length <= max ? text : text[..max] + "…";

    /// <summary>GET /api/quest/published. Offline and dry-run never GET.</summary>
    public static async Task<(bool Ok, string Status, string Json)> GetPublishedQuestsAsync(
        string fid,
        CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(fid))
            return (false, "Missing commander FID.", "");
        if (IsOffline())
            return (false, "RCC offline — published quests skipped.", "");
        var key = ReadRccApiKey();
        if (string.IsNullOrWhiteSpace(key))
            return (false, "No RCC API key in XDG secrets.", "");
        var url = $"{ResolveSvcUri()}/api/quest/published";
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, url);
            req.Headers.TryAddWithoutValidation("rcc-key", key);
            using var response = await Http.SendAsync(req, ct).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return (false, $"RCC HTTP {(int)response.StatusCode}.", "");
            return (true, "Published quests loaded.", text);
        }
        catch (Exception ex)
        {
            return (false, "Published quests failed: " + ex.Message, "");
        }
    }
}
