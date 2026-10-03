using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// Writes Guardian survey mode into the same cmdr JSON Python <c>cmdr_state</c> reads,
/// and enables the <c>guardians</c> overlay panel for the presenter.
/// </summary>
public static class GuardianModeStore
{
    public static string SetMode(string mode, string? preferredCommander = null)
    {
        var normalized = string.IsNullOrWhiteSpace(mode) ? "map" : mode.Trim().ToLowerInvariant();
        if (normalized is not ("map" or "aerial" or "heading" or "site"))
            normalized = "map";

        var cmdr = CmdrDecodeStore.GetOrCreateDefault(preferredCommander);
        JsonObject root;
        try
        {
            root = File.Exists(cmdr.FilePath)
                ? JsonNode.Parse(File.ReadAllText(cmdr.FilePath)) as JsonObject ?? new JsonObject()
                : new JsonObject();
        }
        catch
        {
            root = new JsonObject();
        }

        root["commander"] = cmdr.Commander;
        root["fid"] = cmdr.Fid;

        var sites = root["guardianSites"] as JsonObject ?? new JsonObject();
        var activeKey = root["activeGuardianSite"]?.GetValue<string>();
        if (string.IsNullOrWhiteSpace(activeKey))
            activeKey = sites.Count > 0 ? sites.First().Key : "default";

        var site = sites[activeKey!] as JsonObject ?? new JsonObject();
        site["mode"] = normalized;
        if (site["zoom"] is null)
            site["zoom"] = 1.0;
        sites[activeKey!] = site;
        root["guardianSites"] = sites;
        root["activeGuardianSite"] = activeKey;

        Directory.CreateDirectory(Path.GetDirectoryName(cmdr.FilePath)!);
        File.WriteAllText(
            cmdr.FilePath,
            root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));

        EnableGuardiansPanel();
        return normalized;
    }

    static void EnableGuardiansPanel()
    {
        try
        {
            var path = LinuxPaths.PrimaryConfigPath;
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var lines = File.Exists(path)
                ? File.ReadAllLines(path).ToList()
                : new System.Collections.Generic.List<string>();
            var found = false;
            for (var i = 0; i < lines.Count; i++)
            {
                var raw = lines[i].Trim();
                if (raw.StartsWith("panel.guardians=", StringComparison.OrdinalIgnoreCase))
                {
                    lines[i] = "panel.guardians=true";
                    found = true;
                    break;
                }
            }

            if (!found)
                lines.Add("panel.guardians=true");
            File.WriteAllLines(path, lines);
        }
        catch
        {
            // Presenter may still pick up cmdr mode on next tick.
        }
    }
}
