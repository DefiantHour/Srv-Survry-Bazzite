using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text.Json;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>
/// Linux counterpart of Windows FormRavenUpdater: edit system sites/stations
/// and PUT via RavenColonialClient.UpdateSystemSitesAsync (SitesPut).
/// Does not fake the full WinForms phase wizard / click-drag map UX.
/// </summary>
public sealed class RavenSitesWindow : Window
{
    static readonly string[] StatusChoices = { "plan", "build", "complete", "demolish" };

    readonly TextBox _systemId;
    readonly ListBox _list;
    readonly TextBox _siteName;
    readonly TextBox _bodyNum;
    readonly TextBox _buildType;
    readonly TextBox _marketId;
    readonly ComboBox _status;
    readonly TextBox _architect;
    readonly TextBlock _statusLine;
    readonly ObservableCollection<SiteRow> _sites = new();
    readonly List<string> _deleteIds = new();
    SiteRow? _selected;

    public RavenSitesWindow(string? systemHint = null)
    {
        Title = "Update Stations / Sites";
        Width = 780;
        Height = 620;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _systemId = new TextBox
        {
            Text = systemHint ?? "",
            PlaceholderText = "System name or id64",
        };
        _list = new ListBox { MinHeight = 200, ItemsSource = _sites };
        _list.SelectionChanged += (_, _) => OnSelect();
        _siteName = new TextBox { PlaceholderText = "Site name" };
        _bodyNum = new TextBox { PlaceholderText = "Body number (-1 if unknown)" };
        _buildType = new TextBox { PlaceholderText = "Build type (e.g. outpost, settlement?)" };
        _marketId = new TextBox { PlaceholderText = "Market id (optional)" };
        _status = new ComboBox
        {
            ItemsSource = StatusChoices,
            SelectedIndex = 2,
            MinWidth = 140,
        };
        _architect = new TextBox { PlaceholderText = "Architect (optional)" };
        _statusLine = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.9 };

        var load = new Button { Content = "Load System", MinWidth = 110 };
        load.Click += async (_, _) => await OnLoadAsync();
        var add = new Button { Content = "Add Site", MinWidth = 90 };
        add.Click += (_, _) => OnAdd();
        var apply = new Button { Content = "Apply Edit", MinWidth = 100 };
        apply.Click += (_, _) => OnApplyEdit();
        var remove = new Button { Content = "Remove", MinWidth = 80 };
        remove.Click += (_, _) => OnRemove();
        var submit = new Button { Content = "Submit SitesPut", MinWidth = 130, IsDefault = true };
        submit.Click += async (_, _) => await OnSubmitAsync();
        var wiki = new Button { Content = "Wiki", MinWidth = 70 };
        wiki.Click += (_, _) => ExternalLauncher.TryOpenUri(
            "https://github.com/njthomson/SrvSurvey/wiki/Colonisation-System-Update-Tool");
        var raven = new Button { Content = "Raven Colonial", MinWidth = 120 };
        raven.Click += (_, _) =>
        {
            var id = (_systemId.Text ?? "").Trim();
            ExternalLauncher.TryOpenUri(
                string.IsNullOrWhiteSpace(id)
                    ? "https://ravencolonial.com"
                    : "https://ravencolonial.com/#sys=" + Uri.EscapeDataString(id));
        };
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();

        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(16),
            Children =
            {
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { load, add, apply, remove, submit, wiki, raven, close },
                }.WithDock(Dock.Bottom),
                _statusLine.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text =
                                "Edit Raven Colonial system sites and POST SitesPut (update/delete) via HttpClient. "
                                + "Matches Windows FormRavenUpdater save path. Offline / dry-run never mutate. "
                                + "Full WinForms scanning wizard is not ported — enter or load sites here.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        new TextBlock { Text = "System", FontWeight = FontWeight.SemiBold },
                        _systemId,
                        new TextBlock { Text = "Sites", FontWeight = FontWeight.SemiBold },
                        _list,
                        new TextBlock { Text = "Selected Site" },
                        _siteName,
                        new StackPanel
                        {
                            Orientation = Orientation.Horizontal,
                            Spacing = 8,
                            Children =
                            {
                                new StackPanel
                                {
                                    Spacing = 4,
                                    Width = 160,
                                    Children =
                                    {
                                        new TextBlock { Text = "Body #" },
                                        _bodyNum,
                                    },
                                },
                                new StackPanel
                                {
                                    Spacing = 4,
                                    Width = 220,
                                    Children =
                                    {
                                        new TextBlock { Text = "Build Type" },
                                        _buildType,
                                    },
                                },
                                new StackPanel
                                {
                                    Spacing = 4,
                                    Width = 160,
                                    Children =
                                    {
                                        new TextBlock { Text = "Market Id" },
                                        _marketId,
                                    },
                                },
                                new StackPanel
                                {
                                    Spacing = 4,
                                    Children =
                                    {
                                        new TextBlock { Text = "Status" },
                                        _status,
                                    },
                                },
                            },
                        },
                        new TextBlock { Text = "Architect (optional)" },
                        _architect,
                    },
                },
            },
        };

        var runtime = RuntimeStateSnapshot.TryLoad();
        if (string.IsNullOrWhiteSpace(_systemId.Text) && !string.IsNullOrWhiteSpace(runtime?.System))
            _systemId.Text = runtime!.System;
        if (string.IsNullOrWhiteSpace(_architect.Text) && !string.IsNullOrWhiteSpace(runtime?.Commander))
            _architect.Text = runtime!.Commander;
        _statusLine.Text = "Enter a system name or id64, then Load System or Add Site.";
    }

    async System.Threading.Tasks.Task OnLoadAsync()
    {
        var system = (_systemId.Text ?? "").Trim();
        if (string.IsNullOrWhiteSpace(system))
        {
            _statusLine.Text = "Enter a system name or id64.";
            return;
        }

        _statusLine.Text = "Loading…";
        var (ok, json, status) = await RavenColonialClient.GetSystemAsync(system).ConfigureAwait(true);
        _sites.Clear();
        _deleteIds.Clear();
        _selected = null;
        if (!ok || string.IsNullOrWhiteSpace(json))
        {
            _statusLine.Text = status;
            return;
        }

        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.TryGetProperty("name", out var nameEl) && nameEl.ValueKind == JsonValueKind.String)
            {
                var n = nameEl.GetString();
                if (!string.IsNullOrWhiteSpace(n))
                    _systemId.Text = n;
            }
            if (root.TryGetProperty("architect", out var archEl) && archEl.ValueKind == JsonValueKind.String)
            {
                var a = archEl.GetString();
                if (!string.IsNullOrWhiteSpace(a))
                    _architect.Text = a;
            }
            if (root.TryGetProperty("sites", out var sitesEl) && sitesEl.ValueKind == JsonValueKind.Array)
            {
                foreach (var site in sitesEl.EnumerateArray())
                    _sites.Add(SiteRow.FromJson(site));
            }
            _statusLine.Text = $"{status} — {_sites.Count} site(s) loaded.";
            if (_sites.Count > 0)
                _list.SelectedIndex = 0;
        }
        catch (Exception ex)
        {
            _statusLine.Text = "Parse failed: " + ex.Message;
        }
    }

    void OnSelect()
    {
        if (_list.SelectedItem is not SiteRow row)
            return;
        _selected = row;
        _siteName.Text = row.Name;
        _bodyNum.Text = row.BodyNum.ToString();
        _buildType.Text = row.BuildType ?? "";
        _marketId.Text = row.MarketId?.ToString() ?? "";
        var idx = Array.IndexOf(StatusChoices, row.Status);
        _status.SelectedIndex = idx >= 0 ? idx : 2;
    }

    void OnAdd()
    {
        var row = new SiteRow
        {
            Id = "y" + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            Name = string.IsNullOrWhiteSpace(_siteName.Text) ? "New Site" : _siteName.Text!.Trim(),
            BodyNum = ParseBody(_bodyNum.Text),
            BuildType = string.IsNullOrWhiteSpace(_buildType.Text) ? "settlement?" : _buildType.Text!.Trim(),
            MarketId = ParseLong(_marketId.Text),
            Status = (_status.SelectedItem as string) ?? "complete",
            Dirty = true,
        };
        _sites.Insert(0, row);
        _list.SelectedItem = row;
        _statusLine.Text = "Added site (local). Submit to PUT SitesPut.";
    }

    void OnApplyEdit()
    {
        if (_selected == null)
        {
            _statusLine.Text = "Select a site to edit.";
            return;
        }

        _selected.Name = (_siteName.Text ?? "").Trim();
        _selected.BodyNum = ParseBody(_bodyNum.Text);
        _selected.BuildType = (_buildType.Text ?? "").Trim();
        _selected.MarketId = ParseLong(_marketId.Text);
        _selected.Status = (_status.SelectedItem as string) ?? _selected.Status;
        _selected.Dirty = true;
        var idx = _sites.IndexOf(_selected);
        if (idx >= 0)
        {
            _sites.RemoveAt(idx);
            _sites.Insert(idx, _selected);
            _list.SelectedItem = _selected;
        }
        _statusLine.Text = "Applied local edit. Submit to PUT.";
    }

    void OnRemove()
    {
        if (_selected == null)
        {
            _statusLine.Text = "Select a site to remove.";
            return;
        }

        if (!string.IsNullOrWhiteSpace(_selected.Id) && !_selected.Id.StartsWith('y'))
            _deleteIds.Add(_selected.Id);
        _sites.Remove(_selected);
        _selected = null;
        _statusLine.Text = "Marked for delete (local). Submit to PUT.";
    }

    async System.Threading.Tasks.Task OnSubmitAsync()
    {
        var system = (_systemId.Text ?? "").Trim();
        if (string.IsNullOrWhiteSpace(system))
        {
            _statusLine.Text = "Enter a system name or id64.";
            return;
        }

        var runtime = RuntimeStateSnapshot.TryLoad();
        var fid = runtime?.Commander ?? "unknown";
        var update = _sites
            .Where(s => s.Dirty || string.IsNullOrWhiteSpace(s.Id) || s.Id.StartsWith('y'))
            .Select(s => s.ToDict())
            .ToList();

        if (update.Count == 0 && _deleteIds.Count == 0
            && string.IsNullOrWhiteSpace(_architect.Text))
        {
            _statusLine.Text = "Nothing to submit — edit a site, remove one, or set architect.";
            return;
        }

        _statusLine.Text = "Submitting SitesPut…";
        var result = await RavenColonialClient.UpdateSystemSitesAsync(
            fid,
            system,
            update,
            _deleteIds.ToList(),
            string.IsNullOrWhiteSpace(_architect.Text) ? null : _architect.Text!.Trim())
            .ConfigureAwait(true);

        if (result.Skipped)
            _statusLine.Text = result.Status;
        else if (result.DryRun)
            _statusLine.Text = "Dry-run: " + result.Status + " — " + result.Body;
        else if (result.Ok)
        {
            foreach (var s in _sites)
                s.Dirty = false;
            _deleteIds.Clear();
            _statusLine.Text = result.Status + " — sites submitted.";
        }
        else
            _statusLine.Text = result.Status;
    }

    static int ParseBody(string? text)
    {
        if (int.TryParse((text ?? "").Trim(), out var n))
            return n;
        return -1;
    }

    static long? ParseLong(string? text)
    {
        if (long.TryParse((text ?? "").Trim(), out var n) && n > 0)
            return n;
        return null;
    }

    sealed class SiteRow
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public int BodyNum { get; set; } = -1;
        public string? BuildType { get; set; }
        public string? BuildId { get; set; }
        public long? MarketId { get; set; }
        public string Status { get; set; } = "complete";
        public bool Dirty { get; set; }

        public static SiteRow FromJson(JsonElement site)
        {
            long? market = null;
            if (site.TryGetProperty("marketId", out var m) && m.TryGetInt64(out var mid))
                market = mid;
            var body = -1;
            if (site.TryGetProperty("bodyNum", out var b) && b.TryGetInt32(out var bn))
                body = bn;
            return new SiteRow
            {
                Id = site.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.String
                    ? id.GetString() ?? ""
                    : "",
                Name = site.TryGetProperty("name", out var n) && n.ValueKind == JsonValueKind.String
                    ? n.GetString() ?? ""
                    : "",
                BodyNum = body,
                BuildType = site.TryGetProperty("buildType", out var bt) && bt.ValueKind == JsonValueKind.String
                    ? bt.GetString()
                    : null,
                BuildId = site.TryGetProperty("buildId", out var bi) && bi.ValueKind == JsonValueKind.String
                    ? bi.GetString()
                    : null,
                MarketId = market,
                Status = site.TryGetProperty("status", out var st) && st.ValueKind == JsonValueKind.String
                    ? st.GetString() ?? "complete"
                    : "complete",
            };
        }

        public Dictionary<string, object?> ToDict()
        {
            var d = new Dictionary<string, object?>
            {
                ["id"] = Id,
                ["name"] = Name,
                ["bodyNum"] = BodyNum,
                ["buildType"] = BuildType,
                ["status"] = Status,
            };
            if (!string.IsNullOrWhiteSpace(BuildId))
                d["buildId"] = BuildId;
            if (MarketId.HasValue)
                d["marketId"] = MarketId.Value;
            return d;
        }

        public override string ToString() =>
            $"{Name} · body {BodyNum} · {BuildType ?? "?"} · {Status}"
            + (Dirty ? " *" : "");
    }
}
