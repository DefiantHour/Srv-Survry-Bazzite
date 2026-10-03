using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Layout;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>
/// FormRavenUpdater scan/review flow. Uses the same RCC get-system and update-bodies calls
/// as the site editor. Phases follow journal FSS progress, then installations, orbital ports, and surface sites.
/// </summary>
public sealed class RavenScanWindow : Window
{
    readonly TextBox _system = new() { PlaceholderText = "System name or id64" };
    readonly TextBlock _task = new() { TextWrapping = Avalonia.Media.TextWrapping.Wrap };
    readonly ListBox _list = new();
    readonly TextBlock _status = new() { TextWrapping = Avalonia.Media.TextWrapping.Wrap };
    string _phase = "preamble";
    bool _scanDone;
    List<Dictionary<string, string>> _sites = new();

    public RavenScanWindow(string? systemHint = null)
    {
        Title = "Scan Stations / Sites";
        Width = 720;
        Height = 560;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        if (!string.IsNullOrWhiteSpace(systemHint))
            _system.Text = systemHint;
        var load = new Button { Content = "Load", MinWidth = 80 };
        load.Click += async (_, _) => await LoadAsync();
        var next = new Button { Content = "Next", MinWidth = 80 };
        next.Click += (_, _) => Advance();
        var bodies = new Button { Content = "Import Bodies", MinWidth = 120 };
        bodies.Click += async (_, _) => await ImportBodiesAsync();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { load, next, bodies, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        _system,
                        _task,
                        _list,
                    },
                },
            },
        };
        _task.Text = "Load the system, then step through the scan review.";
    }

    async Task LoadAsync()
    {
        var id = (_system.Text ?? "").Trim();
        var (ok, json, status) = await RavenColonialClient.GetSystemAsync(id);
        _status.Text = status;
        _sites = new List<Dictionary<string, string>>();
        if (!ok || string.IsNullOrWhiteSpace(json))
        {
            _phase = "scanning";
            _task.Text = status;
            return;
        }
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.TryGetProperty("sites", out var sites) && sites.ValueKind == JsonValueKind.Array)
            {
                foreach (var site in sites.EnumerateArray())
                {
                    var row = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    foreach (var name in new[] { "name", "buildType", "bodyNum", "status" })
                    {
                        if (!site.TryGetProperty(name, out var prop))
                            continue;
                        row[name] = prop.ValueKind == JsonValueKind.String
                            ? prop.GetString() ?? ""
                            : prop.ToString();
                    }
                    _sites.Add(row);
                }
            }
            var bodies = root.TryGetProperty("bodies", out var bodyEl) && bodyEl.ValueKind == JsonValueKind.Array
                ? bodyEl.GetArrayLength()
                : 0;
            var journal = ReadJournalScan();
            if (!journal.Complete && journal.Progress is null)
            {
                _scanDone = false;
                _phase = "scanning";
                _task.Text = "Discovery Scan needed ...";
            }
            else if (!journal.Complete && journal.Progress < 1)
            {
                _scanDone = false;
                _phase = "scanning";
                _task.Text = "Complete system FSS ...";
            }
            else if (journal.BodyCount is int total && journal.Scanned < total)
            {
                _scanDone = false;
                _phase = "scanning";
                _task.Text = "Scan the Nav Beacon ...";
            }
            else if (journal.BodyCount is int expected && bodies < expected)
            {
                _scanDone = false;
                _phase = "scanning";
                _task.Text = "Import system bodies.";
            }
            else
            {
                _scanDone = true;
                _phase = "preamble";
                Advance();
            }
            ApplyDockedMarkets(_sites);
            ShowBucket();
        }
        catch (Exception ex)
        {
            _status.Text = "Could not read system JSON: " + ex.Message;
        }
    }

    void Advance()
    {
        if (!_scanDone)
        {
            _task.Text = "Finish the system scan before reviewing sites.";
            return;
        }
        var order = new[] { "noBodyInstallation", "noBodyOrbitalPorts", "allSurfaceSites", "allDone" };
        var start = 0;
        var idx = Array.IndexOf(order, _phase);
        if (idx >= 0)
            start = idx + 1;
        if (start >= order.Length)
            return;
        while (start < order.Length)
        {
            _phase = order[start];
            if (_phase == "allDone")
            {
                _task.Text = "You may hit Submit in Update Stations to update Raven Colonial, or Reload to start over. Dock at Odyssey settlements to identify their types.";
                _list.ItemsSource = Array.Empty<string>();
                return;
            }
            var rows = Bucket(_phase);
            if (rows.Count == 0)
            {
                start++;
                continue;
            }
            _task.Text = Prompt(_phase) + $" ({rows.Count})";
            _list.ItemsSource = rows;
            return;
        }
    }

    void ShowBucket()
    {
        if (_phase is "scanning" or "preamble")
        {
            _list.ItemsSource = _sites.Select(Describe).ToList();
            return;
        }
        _list.ItemsSource = Bucket(_phase);
    }

    List<string> Bucket(string phase)
    {
        bool Match(Dictionary<string, string> site)
        {
            var build = site.GetValueOrDefault("buildType") ?? "";
            var bodyText = site.GetValueOrDefault("bodyNum") ?? "";
            int? body = int.TryParse(bodyText, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed)
                ? parsed
                : null;
            return RavenBuildTypes.InPhase(phase, body, build);
        }
        return _sites.Where(Match).Select(Describe).ToList();
    }

    static string Describe(Dictionary<string, string> site)
    {
        var name = site.GetValueOrDefault("name") ?? "(unnamed)";
        var build = site.GetValueOrDefault("buildType") ?? "";
        var body = site.GetValueOrDefault("bodyNum") ?? "?";
        var status = site.GetValueOrDefault("status") ?? "";
        var market = site.GetValueOrDefault("marketId") ?? "";
        var marketText = string.IsNullOrWhiteSpace(market) ? "" : $" · market {market}";
        return $"{name} · {build} · body {body} · {status}{marketText}";
    }

    static string Prompt(string phase) => phase switch
    {
        "noBodyInstallation" => "On the left/external panel, set the filter to Points of Interest or use the system map. Select the following installations:",
        "noBodyOrbitalPorts" => "Open the system map. Select each orbital port, then set its parent body.",
        "allSurfaceSites" => "In the left/external panel, set the filter to show settlements only, then select the first settlement.",
        _ => "Review sites.",
    };

    async Task ImportBodiesAsync()
    {
        var id = (_system.Text ?? "").Trim();
        if (!long.TryParse(id, NumberStyles.Integer, CultureInfo.InvariantCulture, out var address))
        {
            _status.Text = "Import bodies needs a numeric system address.";
            return;
        }
        var result = await RavenColonialClient.UpdateSysBodiesAsync(address, "[]");
        _status.Text = result.Status;
        if (result.Ok && !result.DryRun && !result.Skipped)
            await LoadAsync();
    }

    static (bool Complete, double? Progress, int? BodyCount, int Scanned) ReadJournalScan()
    {
        var runtime = RuntimeStateSnapshot.TryLoad();
        var folder = runtime?.JournalFolder;
        var file = runtime?.JournalFile;
        if (string.IsNullOrWhiteSpace(file) && !string.IsNullOrWhiteSpace(folder))
        {
            file = Directory.GetFiles(folder, "Journal.*.log")
                .OrderByDescending(File.GetLastWriteTimeUtc)
                .FirstOrDefault();
        }
        if (string.IsNullOrWhiteSpace(file) || !File.Exists(file))
            return (false, null, null, 0);
        double? progress = null;
        int? bodyCount = null;
        var complete = false;
        var scanned = new HashSet<int>();
        foreach (var line in File.ReadLines(file))
        {
            if (string.IsNullOrWhiteSpace(line))
                continue;
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                var ev = root.TryGetProperty("event", out var eventEl) ? eventEl.GetString() : null;
                if (ev == "FSSDiscoveryScan")
                {
                    if (root.TryGetProperty("Progress", out var p) && p.TryGetDouble(out var value))
                        progress = value;
                    if (root.TryGetProperty("BodyCount", out var c) && c.TryGetInt32(out var count))
                        bodyCount = count;
                }
                else if (ev == "FSSAllBodiesFound")
                {
                    complete = true;
                    if (root.TryGetProperty("Count", out var c) && c.TryGetInt32(out var count))
                        bodyCount = count;
                }
                else if (ev == "Scan" && root.TryGetProperty("BodyID", out var id) && id.TryGetInt32(out var bodyId))
                    scanned.Add(bodyId);
                else if (ev is "FSDJump" or "CarrierJump")
                {
                    progress = null;
                    bodyCount = null;
                    complete = false;
                    scanned.Clear();
                }
            }
            catch
            {
                // skip broken journal lines
            }
        }
        return (complete, progress, bodyCount, scanned.Count);
    }

    static void ApplyDockedMarkets(List<Dictionary<string, string>> sites)
    {
        var runtime = RuntimeStateSnapshot.TryLoad();
        var file = runtime?.JournalFile;
        var folder = runtime?.JournalFolder;
        if (string.IsNullOrWhiteSpace(file) && !string.IsNullOrWhiteSpace(folder))
        {
            file = Directory.GetFiles(folder, "Journal.*.log")
                .OrderByDescending(File.GetLastWriteTimeUtc)
                .FirstOrDefault();
        }
        if (string.IsNullOrWhiteSpace(file) || !File.Exists(file))
            return;
        var markets = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in File.ReadLines(file))
        {
            if (string.IsNullOrWhiteSpace(line))
                continue;
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                var ev = root.TryGetProperty("event", out var eventEl) ? eventEl.GetString() : null;
                if (ev is "FSDJump" or "CarrierJump")
                {
                    markets.Clear();
                    continue;
                }
                if (ev != "Docked")
                    continue;
                var station = root.TryGetProperty("StationName", out var nameEl) ? nameEl.GetString() : null;
                if (string.IsNullOrWhiteSpace(station) || !root.TryGetProperty("MarketID", out var marketEl))
                    continue;
                if (marketEl.TryGetInt64(out var market) && market > 0)
                    markets[station] = market.ToString(CultureInfo.InvariantCulture);
            }
            catch
            {
                // skip broken journal lines
            }
        }
        foreach (var site in sites)
        {
            var name = site.GetValueOrDefault("name") ?? "";
            if (!markets.TryGetValue(name, out var market))
                continue;
            var existing = site.GetValueOrDefault("marketId") ?? "";
            if (string.IsNullOrWhiteSpace(existing) || existing == "0")
                site["marketId"] = market;
        }
    }
}
