using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Input.Platform;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

public sealed class MyProjectsWindow : Window
{
    readonly ListBox _list;
    readonly TextBox _notes;
    readonly TextBlock _fcSummary;
    readonly TextBlock _status;
    ProjectNotesDocument _doc = new();
    ProjectNote? _selected;

    public MyProjectsWindow()
    {
        Title = "My Projects";
        Width = 720;
        Height = 560;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _list = new ListBox { MinHeight = 180 };
        _list.SelectionChanged += (_, _) => OnSelect();
        _notes = new TextBox
        {
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 140,
        };
        _fcSummary = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.9 };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.8 };

        var openRaven = new Button { Content = "Open Raven Colonial", MinWidth = 150 };
        openRaven.Click += (_, _) =>
        {
            var url = string.IsNullOrWhiteSpace(_selected?.RavenUrl)
                ? "https://ravencolonial.com"
                : _selected!.RavenUrl;
            ExternalLauncher.TryOpenUri(url);
            _status.Text = "Opened " + url;
        };
        var publishFc = new Button { Content = "Publish FC", MinWidth = 110 };
        publishFc.Click += async (_, _) =>
        {
            _status.Text = "Publishing FC…";
            _status.Text = await OnPublishFcAsync();
        };
        var updateSystem = new Button { Content = "Update System", MinWidth = 120 };
        updateSystem.Click += async (_, _) =>
        {
            _status.Text = "Updating system…";
            _status.Text = await OnUpdateSystemAsync();
        };
        var setPrimary = new Button { Content = "Set Primary", MinWidth = 110 };
        setPrimary.Click += async (_, _) =>
        {
            _status.Text = "Setting primary…";
            _status.Text = await OnSetPrimaryAsync();
        };
        var refreshProjects = new Button { Content = "Fetch Active", MinWidth = 110 };
        refreshProjects.Click += async (_, _) =>
        {
            _status.Text = "Fetching active…";
            var cmdr = RuntimeStateSnapshot.TryLoad()?.Commander;
            _status.Text = await RavenColonialClient.FetchActiveProjectsSummaryAsync(cmdr)
                .ConfigureAwait(true);
        };
        var editSites = new Button { Content = "Edit Sites", MinWidth = 100 };
        editSites.Click += (_, _) =>
        {
            var system = !string.IsNullOrWhiteSpace(_selected?.SystemName)
                ? _selected!.SystemName
                : RuntimeStateSnapshot.TryLoad()?.System;
            WindowHost.Show(new RavenSitesWindow(system));
            _status.Text = "Opened Update Stations / Sites";
        };
        var save = new Button { Content = "Save Notes", MinWidth = 100, IsDefault = true };
        save.Click += (_, _) => OnSave();
        var refresh = new Button { Content = "Reload", MinWidth = 80 };
        refresh.Click += (_, _) => Reload();
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
                    Children =
                    {
                        openRaven, publishFc, updateSystem, setPrimary,
                        refreshProjects, editSites, save, refresh, close,
                    },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Local project notes. RCC writes (Publish FC / Update System / Set Primary / Edit Sites / Fetch Active) use RavenColonialClient + XDG secrets rcc_api_key; fail-soft when offline or dry-run.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _fcSummary,
                        new TextBlock { Text = "Projects", FontWeight = FontWeight.SemiBold },
                        _list,
                        new TextBlock { Text = "Selected Project Notes" },
                        _notes,
                    },
                },
            },
        };

        Reload();
    }

    async System.Threading.Tasks.Task<string> OnPublishFcAsync()
    {
        var runtime = RuntimeStateSnapshot.TryLoad();
        var stored = CommanderStore.LoadOrCreate(null, runtime?.Commander);
        var fid = !string.IsNullOrWhiteSpace(stored.Fid) ? stored.Fid : (runtime?.Commander ?? "unknown");
        long marketId = 0;
        if (_selected != null && long.TryParse(_selected.Id, out var parsed))
            marketId = parsed;
        if (marketId <= 0)
            return "Select a project whose Id is a Fleet Carrier market id, or set Id to the market id.";

        var name = _selected?.Name ?? "Fleet Carrier";
        var result = await RavenColonialClient.PublishFcAsync(fid, marketId, name, name)
            .ConfigureAwait(true);
        return FormatRcc(result);
    }

    async System.Threading.Tasks.Task<string> OnUpdateSystemAsync()
    {
        var runtime = RuntimeStateSnapshot.TryLoad();
        var system = !string.IsNullOrWhiteSpace(_selected?.SystemName)
            ? _selected!.SystemName
            : runtime?.System;
        if (string.IsNullOrWhiteSpace(system))
            return "No system name on selected project or runtime state.";

        var fid = runtime?.Commander ?? "unknown";
        var architect = runtime?.Commander;
        var result = await RavenColonialClient.UpdateSystemAsync(fid, system!, architect)
            .ConfigureAwait(true);
        return FormatRcc(result);
    }

    async System.Threading.Tasks.Task<string> OnSetPrimaryAsync()
    {
        var runtime = RuntimeStateSnapshot.TryLoad();
        var cmdr = runtime?.Commander;
        if (string.IsNullOrWhiteSpace(cmdr))
            return "No commander in runtime state — start the presenter first.";
        if (_selected == null)
            return "Select a project to set as primary.";

        var buildId = await ResolveRavenBuildIdAsync(_selected).ConfigureAwait(true);
        if (string.IsNullOrWhiteSpace(buildId))
            return "Selected note has no Raven build id. Use a project from Fetch Active, or dock at the site and use Set primary on the Colonize menu.";

        var result = await RavenColonialClient.SetPrimaryAsync(cmdr!, buildId)
            .ConfigureAwait(true);
        if (result.Ok || result.DryRun)
        {
            foreach (var p in _doc.Projects)
                p.IsLocalPrimary = p.Id == _selected.Id;
            ProjectNotesStore.Save(_doc);
            Reload();
        }

        return FormatRcc(result);
    }

    static async System.Threading.Tasks.Task<string?> ResolveRavenBuildIdAsync(ProjectNote note)
    {
        if (Guid.TryParse(note.Id, out _))
            return note.Id;
        if (string.IsNullOrWhiteSpace(note.SystemName))
            return null;
        var runtime = RuntimeStateSnapshot.TryLoad();
        var projects = await RavenColonialClient.GetActiveProjectsAsync(runtime?.Commander)
            .ConfigureAwait(true);
        return projects.FirstOrDefault(p =>
            string.Equals(p.SystemName, note.SystemName, StringComparison.OrdinalIgnoreCase))?.BuildId;
    }

    static string FormatRcc(RavenColonialResult result)
    {
        if (result.Skipped)
            return result.Status;
        if (result.DryRun)
            return "Dry-run: " + result.Status + " — " + result.Body;
        return result.Status;
    }

    void Reload()
    {
        _doc = ProjectNotesStore.Load();
        _fcSummary.Text = "Linked FC: " + ProjectNotesStore.FcSummaryOrFallback();
        _list.ItemsSource = _doc.Projects.Select(p => new ProjectItem(p)).ToList();
        _status.Text = $"{_doc.Projects.Count} local project(s) · {DataFileLocator.ProjectNotesPath}";
        if (_doc.Projects.Count > 0)
            _list.SelectedIndex = 0;
    }

    void OnSelect()
    {
        if (_list.SelectedItem is ProjectItem item)
        {
            _selected = item.Note;
            _notes.Text = item.Note.Notes;
        }
    }

    void OnSave()
    {
        if (_selected == null)
        {
            _status.Text = "No project selected.";
            return;
        }

        _selected.Notes = _notes.Text ?? "";
        _selected.Updated = DateTimeOffset.UtcNow.ToString("o");
        ProjectNotesStore.Save(_doc);
        _status.Text = "Saved project notes.";
        Reload();
    }

    sealed class ProjectItem
    {
        public ProjectItem(ProjectNote note) => Note = note;
        public ProjectNote Note { get; }
        public override string ToString() =>
            $"{(Note.IsLocalPrimary ? "★ " : "")}{Note.Name} · {Note.SystemName}";
    }
}

public sealed class NewProjectWindow : Window
{
    readonly TextBox _name;
    readonly TextBox _system;
    readonly TextBox _notes;
    readonly TextBlock _status;

    public NewProjectWindow(string? systemName = null)
    {
        Title = "New Project";
        Width = 480;
        Height = 360;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _name = new TextBox { PlaceholderText = "Build / project name" };
        _system = new TextBox { Text = systemName ?? "", PlaceholderText = "System" };
        _notes = new TextBox
        {
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 100,
            PlaceholderText = "Local notes",
        };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.85 };

        var create = new Button { Content = "Create Local + Open Raven", MinWidth = 180, IsDefault = true };
        create.Click += (_, _) => OnCreate();
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
                    Children = { create, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Creates editable local project notes and opens Raven Colonial for server-side project creation.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        new TextBlock { Text = "Name" },
                        _name,
                        new TextBlock { Text = "System" },
                        _system,
                        new TextBlock { Text = "Notes" },
                        _notes,
                    },
                },
            },
        };
    }

    void OnCreate()
    {
        var note = ProjectNotesStore.Create(
            _name.Text?.Trim() ?? "New Project",
            _system.Text?.Trim() ?? "",
            _notes.Text ?? "");
        ExternalLauncher.TryOpenUri(note.RavenUrl);
        _status.Text = $"Created local project {note.Id} and opened Raven Colonial.";
    }
}

public sealed class LocalProjectWindow : Window
{
    readonly TextBox _name;
    readonly TextBox _system;
    readonly TextBox _notes;
    readonly TextBox _fcSummary;
    readonly TextBlock _status;
    ProjectNotesDocument _doc;
    ProjectNote _note;

    public LocalProjectWindow()
    {
        Title = "Local Project";
        Width = 520;
        Height = 440;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _doc = ProjectNotesStore.Load();
        _note = ProjectNotesStore.GetPrimaryOrFirst()
                ?? ProjectNotesStore.Create("Local Project", "", "");
        _doc = ProjectNotesStore.Load();
        _note = _doc.Projects.First(p => p.Id == _note.Id);

        _name = new TextBox { Text = _note.Name };
        _system = new TextBox { Text = _note.SystemName };
        _notes = new TextBox
        {
            Text = _note.Notes,
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 120,
        };
        _fcSummary = new TextBox
        {
            Text = _doc.LinkedFcSummary ?? "",
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 60,
            PlaceholderText = "Optional linked FC summary text",
        };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.85 };

        var save = new Button { Content = "Save", MinWidth = 80, IsDefault = true };
        save.Click += (_, _) => OnSave();
        var raven = new Button { Content = "Raven Colonial", MinWidth = 120 };
        raven.Click += (_, _) => ExternalLauncher.TryOpenUri(
            string.IsNullOrWhiteSpace(_note.RavenUrl) ? "https://ravencolonial.com" : _note.RavenUrl);
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
                    Children = { save, raven, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock { Text = "Name" },
                        _name,
                        new TextBlock { Text = "System" },
                        _system,
                        new TextBlock { Text = "Notes" },
                        _notes,
                        new TextBlock { Text = "Linked FC Summary (local)" },
                        _fcSummary,
                    },
                },
            },
        };
    }

    void OnSave()
    {
        _note.Name = _name.Text?.Trim() ?? _note.Name;
        _note.SystemName = _system.Text?.Trim() ?? "";
        _note.Notes = _notes.Text ?? "";
        _note.IsLocalPrimary = true;
        _note.Updated = DateTimeOffset.UtcNow.ToString("o");
        foreach (var p in _doc.Projects)
            p.IsLocalPrimary = p.Id == _note.Id;
        _doc.LinkedFcSummary = _fcSummary.Text;
        ProjectNotesStore.Save(_doc);
        _status.Text = "Saved " + DataFileLocator.ProjectNotesPath;
    }
}

public sealed class RouteWindow : Window
{
    readonly ListBox _list;
    readonly TextBlock _status;
    readonly TextBox _routeId;
    readonly CheckBox _autoCopy;
    readonly List<string> _hops = new();
    int _nextHop;
    bool _busy;

    public RouteWindow(string? journalFolder = null)
    {
        Title = "Follow a Route";
        Width = 680;
        Height = 560;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _list = new ListBox { MinHeight = 280 };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.9 };
        _routeId = new TextBox { PlaceholderText = "Spansh route id" };
        _autoCopy = new CheckBox { Content = "Auto-copy the next hop", IsChecked = true };

        var refresh = new Button { Content = "Refresh NavRoute", MinWidth = 120 };
        refresh.Click += (_, _) => Load(journalFolder);
        var import = new Button { Content = "Import Spansh", MinWidth = 110 };
        import.Click += async (_, _) => await ImportSpanshAsync();
        var copy = new Button { Content = "Copy Next Hop", MinWidth = 120 };
        copy.Click += async (_, _) => await CopyNextAsync();
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
                    Children = { refresh, import, copy, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "NavRoute.json, or paste a Spansh route id and import it. Copy Next Hop matches Windows autoCopy.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _routeId,
                        _autoCopy,
                        _list,
                    },
                },
            },
        };

        Load(journalFolder);
    }

    void Load(string? journalFolder)
    {
        var summary = NavRouteStore.Load(journalFolder);
        _hops.Clear();
        _hops.AddRange(summary.Hops.Select(h => h.StarSystem).Where(s => !string.IsNullOrWhiteSpace(s)));
        _nextHop = 0;
        ShowHops(summary.StatusText + (summary.Path != null ? Environment.NewLine + summary.Path : ""));
    }

    void ShowHops(string status)
    {
        _status.Text = status;
        _list.ItemsSource = _hops.Select((name, i) => $"{i + 1}. {name}" + (i == _nextHop ? "  ← next" : "")).ToList();
    }

    async Task ImportSpanshAsync()
    {
        if (_busy)
            return;
        _busy = true;
        try
        {
            var (ok, status, json) = await SpanshClient.FetchRouteAsync(_routeId.Text ?? "");
            if (!ok || string.IsNullOrWhiteSpace(json))
            {
                _status.Text = status;
                return;
            }
            var hops = ParseSpanshHops(json);
            if (hops.Count == 0)
            {
                _status.Text = "Spansh returned no system names.";
                return;
            }
            _hops.Clear();
            _hops.AddRange(hops);
            _nextHop = 0;
            ShowHops($"{status}: {hops.Count} systems.");
            if (_autoCopy.IsChecked == true)
                await CopyNextAsync();
        }
        finally
        {
            _busy = false;
        }
    }

    async Task CopyNextAsync()
    {
        if (_hops.Count == 0)
        {
            _status.Text = "No hops to copy.";
            return;
        }
        if (_nextHop >= _hops.Count)
            _nextHop = 0;
        var name = _hops[_nextHop];
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard == null)
        {
            _status.Text = "Clipboard unavailable. Next hop: " + name;
            return;
        }
        await clipboard.SetTextAsync(name);
        _status.Text = "Copied next hop: " + name;
        _nextHop++;
        if (_nextHop >= _hops.Count)
            _nextHop = 0;
        ShowHops(_status.Text);
    }

    static List<string> ParseSpanshHops(string json)
    {
        var names = new List<string>();
        using var doc = JsonDocument.Parse(json);
        CollectNames(doc.RootElement, names);
        return names;
    }

    static void CollectNames(JsonElement el, List<string> names)
    {
        if (el.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in el.EnumerateObject())
            {
                if (prop.NameEquals("system") || prop.NameEquals("StarSystem") || prop.NameEquals("name"))
                {
                    if (prop.Value.ValueKind == JsonValueKind.String)
                    {
                        var text = prop.Value.GetString();
                        if (!string.IsNullOrWhiteSpace(text) && (names.Count == 0 || names[^1] != text))
                            names.Add(text);
                    }
                }
                else
                {
                    CollectNames(prop.Value, names);
                }
            }
        }
        else if (el.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in el.EnumerateArray())
                CollectNames(item, names);
        }
    }
}
