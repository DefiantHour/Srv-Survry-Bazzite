using System;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

public sealed class JourneyBeginWindow : Window
{
    readonly TextBox _name;
    readonly TextBox _system;
    readonly TextBox _commander;
    readonly TextBox _description;
    readonly TextBlock _status;

    public JourneyBeginWindow(string? commander = null, string? system = null)
    {
        Title = "Start a New Journey";
        Width = 480;
        Height = 360;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _name = new TextBox { PlaceholderText = "Journey name" };
        _system = new TextBox { Text = system ?? "", PlaceholderText = "Starting system" };
        _commander = new TextBox { Text = commander ?? "", PlaceholderText = "Commander" };
        _description = new TextBox
        {
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 80,
            PlaceholderText = "Description (optional)",
        };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.85 };

        var save = new Button { Content = "Begin", MinWidth = 90, IsDefault = true };
        save.Click += (_, _) => OnBegin();
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
                    Children = { save, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock { Text = "Creates a JSON journey under ~/.local/share/srvsurvey/journey/." },
                        new TextBlock { Text = "Name" },
                        _name,
                        new TextBlock { Text = "Commander" },
                        _commander,
                        new TextBlock { Text = "Starting System" },
                        _system,
                        new TextBlock { Text = "Description" },
                        _description,
                    },
                },
            },
        };
    }

    void OnBegin()
    {
        if (string.IsNullOrWhiteSpace(_name.Text))
        {
            _status.Text = "Name is required.";
            return;
        }

        var journey = JourneyStore.Create(
            _name.Text.Trim(),
            _commander.Text?.Trim() ?? "",
            _system.Text?.Trim() ?? "",
            _description.Text ?? "");
        _status.Text = $"Created: {journey.FilePath}";
    }
}

public sealed class JourneyListWindow : Window
{
    readonly ListBox _list;
    readonly TextBlock _status;

    public JourneyListWindow()
    {
        Title = "Past Journeys";
        Width = 640;
        Height = 480;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _list = new ListBox { MinHeight = 320 };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.85 };

        var open = new Button { Content = "Open Selected", MinWidth = 120 };
        open.Click += (_, _) =>
        {
            if (_list.SelectedItem is JourneyListItem item)
                WindowHost.Show(new JourneyViewerWindow(item.Journey));
        };
        var refresh = new Button { Content = "Refresh", MinWidth = 80 };
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
                    Children = { open, refresh, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock { Text = $"Folder: {DataFileLocator.JourneyDirectory}" },
                        _list,
                    },
                },
            },
        };

        Reload();
    }

    void Reload()
    {
        var all = JourneyStore.ListAll();
        _list.ItemsSource = all.Select(j => new JourneyListItem(j)).ToList();
        _status.Text = $"{all.Count} journey file(s)";
    }

    sealed class JourneyListItem
    {
        public JourneyListItem(JourneyRecord journey) => Journey = journey;
        public JourneyRecord Journey { get; }
        public override string ToString() =>
            $"{Journey.Name} · {Journey.Commander} · {Journey.StartTime:yyyy-MM-dd} · {Journey.VisitedSystems.Count} systems";
    }
}

public sealed class JourneyViewerWindow : Window
{
    readonly JourneyRecord _journey;
    readonly TextBox _name;
    readonly TextBox _description;
    readonly TextBox _systems;
    readonly TextBlock _status;

    public JourneyViewerWindow(JourneyRecord? journey = null)
    {
        _journey = journey ?? JourneyStore.ListAll().FirstOrDefault()
                   ?? new JourneyRecord { Name = "(no journeys yet)" };

        Title = "View Journey — " + _journey.Name;
        Width = 640;
        Height = 520;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _name = new TextBox { Text = _journey.Name };
        _description = new TextBox
        {
            Text = _journey.Description,
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 80,
        };
        _systems = new TextBox
        {
            Text = string.Join(Environment.NewLine, _journey.VisitedSystems),
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 160,
            IsReadOnly = true,
        };
        _status = new TextBlock
        {
            Text = string.IsNullOrWhiteSpace(_journey.FilePath)
                ? "No journey files found. Start one from Travel → Start a New Journey."
                : _journey.FilePath,
            TextWrapping = TextWrapping.Wrap,
            Opacity = 0.85,
        };

        var save = new Button { Content = "Save", MinWidth = 80, IsDefault = true };
        save.Click += (_, _) => OnSave();
        var catchUp = new Button { Content = "Catch Up From Journal", MinWidth = 160 };
        catchUp.Click += (_, _) => OnCatchUp();
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
                    Children = { catchUp, save, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock { Text = "Name" },
                        _name,
                        new TextBlock { Text = "Description" },
                        _description,
                        new TextBlock
                        {
                            Text = $"Start: {_journey.StartTime:u} · System: {_journey.StartingSystem}",
                        },
                        new TextBlock { Text = "Visited Systems" },
                        _systems,
                    },
                },
            },
        };
    }

    void OnCatchUp()
    {
        if (string.IsNullOrWhiteSpace(_journey.FilePath))
        {
            _status.Text = "Create a journey first.";
            return;
        }

        var folder = RuntimeStateSnapshot.TryLoad()?.JournalFolder;
        var result = JourneyCatchUp.CatchUp(_journey, folder);
        _systems.Text = string.Join(Environment.NewLine, _journey.VisitedSystems);
        _status.Text = result.Status;
    }

    void OnSave()
    {
        if (string.IsNullOrWhiteSpace(_journey.FilePath))
        {
            _status.Text = "Nothing to save.";
            return;
        }

        _journey.Name = _name.Text?.Trim() ?? _journey.Name;
        _journey.Description = _description.Text ?? "";
        JourneyStore.Save(_journey);
        _status.Text = "Saved " + _journey.FilePath;
        Title = "View Journey — " + _journey.Name;
    }
}

public sealed class SystemNotesWindow : Window
{
    readonly TextBox _system;
    readonly TextBox _notes;
    readonly TextBlock _status;

    public SystemNotesWindow(string? systemName = null)
    {
        Title = "System Notes";
        Width = 520;
        Height = 400;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _system = new TextBox { Text = systemName ?? "", PlaceholderText = "System name" };
        _notes = new TextBox
        {
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 200,
        };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.85 };

        if (!string.IsNullOrWhiteSpace(systemName))
            _notes.Text = JourneyStore.LoadSystemNote(systemName);

        var load = new Button { Content = "Load", MinWidth = 80 };
        load.Click += (_, _) =>
        {
            if (string.IsNullOrWhiteSpace(_system.Text))
            {
                _status.Text = "Enter a system name.";
                return;
            }

            _notes.Text = JourneyStore.LoadSystemNote(_system.Text.Trim());
            _status.Text = "Loaded notes for " + _system.Text.Trim();
        };
        var save = new Button { Content = "Save", MinWidth = 80, IsDefault = true };
        save.Click += (_, _) =>
        {
            if (string.IsNullOrWhiteSpace(_system.Text))
            {
                _status.Text = "Enter a system name.";
                return;
            }

            JourneyStore.SaveSystemNote(_system.Text.Trim(), _notes.Text ?? "");
            _status.Text = "Saved to " + DataFileLocator.SystemNotesDirectory;
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
                    Children = { load, save, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock { Text = "System" },
                        _system,
                        new TextBlock { Text = "Notes" },
                        _notes,
                    },
                },
            },
        };
    }
}
