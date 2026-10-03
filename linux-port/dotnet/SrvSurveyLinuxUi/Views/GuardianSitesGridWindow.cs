using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Controls.Templates;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>FormBeacons: Guardian Sites grid. Rows come from the public catalogue only.</summary>
public sealed class GuardianSitesGridWindow : Window
{
    static readonly string[] TypeChoices =
    {
        "All Sites",
        "Beacons",
        "All Ruins",
        "Alpha", "Beta", "Gamma",
        "All Structures",
        "Lacrosse", "Crossroads", "Fistbump", "Hammerbot", "Bear", "Bowl",
        "Turtle", "Robolobster", "Squid", "Stickyhand",
    };

    readonly TextBox _filter = new() { PlaceholderText = "Filter" };
    readonly TextBox _typeLabel = new() { IsReadOnly = true, Text = "All Ruins and Structures" };
    readonly ComboBox _type = new();
    readonly ComboBox _visited = new();
    readonly ComboBox _from = new();
    readonly CheckBox _ramTah = new() { Content = "Show Ram Tah Logs" };
    readonly ListBox _grid = new();
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };
    readonly IReadOnlyList<GuardianGridEntry> _rows;
    readonly string? _currentSystem;

    public GuardianSitesGridWindow(string? currentSystem = null, GuardianGridEntry? focus = null)
    {
        _currentSystem = currentSystem;
        Title = "Guardian Sites";
        Width = 1180;
        Height = 560;
        MinWidth = 800;
        MinHeight = 360;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _rows = GuardianCatalogue.Load();
        _type.ItemsSource = TypeChoices;
        _type.SelectedIndex = 0;
        _visited.ItemsSource = new[] { "All", "Visited", "Unvisited" };
        _visited.SelectedIndex = 0;
        var systems = GuardianCatalogue.SystemNames().ToList();
        _from.ItemsSource = systems;
        if (!string.IsNullOrWhiteSpace(currentSystem))
        {
            var match = systems.FirstOrDefault(s => string.Equals(s, currentSystem, StringComparison.OrdinalIgnoreCase));
            if (match != null)
                _from.SelectedItem = match;
        }
        if (_from.SelectedItem == null && systems.Count > 0)
            _from.SelectedIndex = 0;

        _filter.TextChanged += (_, _) => Apply();
        _type.SelectionChanged += (_, _) =>
        {
            _typeLabel.Text = TypeLabel(_type.SelectedItem as string);
            Apply();
        };
        _visited.SelectionChanged += (_, _) => Apply();
        _from.SelectionChanged += (_, _) => Apply();
        _ramTah.IsCheckedChanged += (_, _) => Apply();
        _grid.MaxHeight = 360;
        _grid.DoubleTapped += (_, _) => OpenSelected();
        _grid.ItemTemplate = new FuncDataTemplate<GridLine>((line, _) => LineRow(line));

        var filterButton = new Button { Content = "Filter", MinWidth = 72 };
        filterButton.Click += (_, _) => Apply();
        var survey = new Button { Content = "Open site survey", MinWidth = 120 };
        survey.Click += (_, _) => OpenSelected();
        var share = new Button { Content = "Share your discovered data **", IsEnabled = false, MinWidth = 180 };
        var guidance = new Menu
        {
            Items =
            {
                new MenuItem
                {
                    Header = "Guidance links",
                    Items =
                    {
                        Link("SrvSurvey Ram Tah helpers", "https://github.com/njthomson/SrvSurvey/wiki/Ram-Tah-Missions"),
                        Link("Ram Tah #1 - Decoding the Ancient Ruins", "https://canonn.science/codex/ram-tahs-mission/"),
                        Link("Ram Tah #2 - Decrypting the Guardian Logs", "https://canonn.science/codex/ram-tah-decrypting-the-guardian-logs/"),
                    },
                },
            },
        };

        var header = HeaderRow();
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(8),
            Children =
            {
                _status.WithDock(Dock.Bottom).WithMargin(0, 6, 0, 0),
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    Children = { share, guidance },
                }.WithDock(Dock.Bottom).WithMargin(0, 6, 0, 0),
                new StackPanel
                {
                    Spacing = 6,
                    Children =
                    {
                        new WrapPanel
                        {
                            Orientation = Orientation.Horizontal,
                            Children =
                            {
                                filterButton,
                                _filter.WithWidth(180),
                                new TextBlock { Text = "Type:", VerticalAlignment = VerticalAlignment.Center, Margin = new Avalonia.Thickness(8, 0, 4, 0) },
                                _type.WithWidth(150),
                                _typeLabel.WithWidth(200),
                                _visited.WithWidth(110),
                                _ramTah,
                            },
                        },
                        new StackPanel
                        {
                            Orientation = Orientation.Horizontal,
                            Spacing = 8,
                            Children =
                            {
                                new TextBlock { Text = "Measure distances from:", VerticalAlignment = VerticalAlignment.Center },
                                _from.WithWidth(280),
                                survey,
                            },
                        },
                        header,
                        _grid,
                    },
                },
            },
        };

        if (focus != null)
        {
            var type = focus.SiteType;
            if (TypeChoices.Contains(type))
                _type.SelectedItem = type;
        }
        Apply();
    }

    void OpenSelected()
    {
        if (_grid.SelectedItem is not GridLine line)
        {
            _status.Text = "Select a row to open its site survey.";
            return;
        }
        WindowHost.Show(new GuardianMapsWindow(line.Entry));
    }

    void Apply()
    {
        var origin = GuardianCatalogue.FindSystem(_from.SelectedItem as string);
        var needle = (_filter.Text ?? "").Trim();
        var type = _type.SelectedItem as string ?? "All Sites";
        var visited = _visited.SelectedIndex;
        var shown = new List<GridLine>();
        var surveyed = 0;
        foreach (var row in _rows)
        {
            if (!TypeMatches(type, row))
                continue;
            if (visited == 1)
                continue;
            if (!string.IsNullOrEmpty(needle)
                && !row.SystemName.Contains(needle, StringComparison.OrdinalIgnoreCase)
                && !row.BodyName.Contains(needle, StringComparison.OrdinalIgnoreCase)
                && !row.SiteType.Contains(needle, StringComparison.OrdinalIgnoreCase)
                && !row.Id.Contains(needle, StringComparison.OrdinalIgnoreCase))
                continue;
            var distance = "";
            if (origin is { HasStarPos: true } && row.HasStarPos)
            {
                var ly = GuardianCatalogue.DistanceLy(origin.X, origin.Y, origin.Z, row.X, row.Y, row.Z);
                distance = ly.ToString("N0", CultureInfo.InvariantCulture) + " ly";
            }
            if (row.SurveyComplete)
                surveyed++;
            shown.Add(new GridLine(row, distance));
        }
        _grid.ItemsSource = shown;
        var percent = shown.Count == 0 ? 0 : (int)Math.Round(100.0 * surveyed / shown.Count);
        var ram = _ramTah.IsChecked == true
            ? " Ram Tah log names are not in the public catalogue."
            : "";
        _status.Text =
            $"{shown.Count} of {_rows.Count} rows | visited: 0 (0%) | surveys complete: {surveyed} ({percent}%)"
            + " | last visited, images, and Ram Tah logs are not in allRuins.json, allStructures.json, or allBeacons.json."
            + (string.IsNullOrWhiteSpace(_currentSystem) ? "" : "")
            + ram;
        if (_rows.Count == 0)
            _status.Text = "No catalogue files were found (allRuins.json, allStructures.json, allBeacons.json).";
    }

    static bool TypeMatches(string choice, GuardianGridEntry row)
    {
        return choice switch
        {
            "All Sites" => true,
            "Beacons" => row.Kind == "Beacon",
            "All Ruins" => row.Kind == "Ruin",
            "All Structures" => row.Kind == "Structure",
            _ => string.Equals(row.SiteType, choice, StringComparison.OrdinalIgnoreCase),
        };
    }

    static string TypeLabel(string? choice) => choice switch
    {
        "All Sites" => "All Ruins and Structures",
        "All Ruins" => "All Ruins",
        "All Structures" => "All Structures",
        "Beacons" => "Beacons",
        null or "" => "All Ruins and Structures",
        _ => choice,
    };

    static Control LineRow(GridLine? line)
    {
        var grid = new Grid { ColumnDefinitions = Columns() };
        if (line == null)
            return grid;
        var cells = new[]
        {
            line.Entry.Id,
            line.Entry.SystemName,
            line.Entry.BodyName,
            line.Distance,
            line.Entry.ArrivalText,
            line.Entry.LastVisited,
            line.Entry.SiteType,
            line.Entry.IndexText,
            line.Entry.HasImages,
            line.Entry.SurveyText,
            line.Entry.RamTahLogs,
        };
        for (var i = 0; i < cells.Length; i++)
        {
            var text = new TextBlock
            {
                Text = cells[i],
                FontSize = 12,
                Margin = new Avalonia.Thickness(4, 1),
                TextTrimming = TextTrimming.CharacterEllipsis,
            };
            Grid.SetColumn(text, i);
            grid.Children.Add(text);
        }
        return grid;
    }

    static Grid HeaderRow()
    {
        var grid = new Grid
        {
            ColumnDefinitions = Columns(),
            Background = new SolidColorBrush(Color.Parse("#e6e6e6")),
        };
        var headers = new[]
        {
            "ID", "System", "Body", "System distance", "Arrival distance",
            "Last visited", "Site type", "Index", "Has images", "Survey status", "Ram Tah Logs",
        };
        for (var i = 0; i < headers.Length; i++)
        {
            var text = new TextBlock
            {
                Text = headers[i],
                FontWeight = FontWeight.SemiBold,
                FontSize = 12,
                Margin = new Avalonia.Thickness(4, 2),
            };
            Grid.SetColumn(text, i);
            grid.Children.Add(text);
        }
        return grid;
    }

    static ColumnDefinitions Columns() =>
        new("78,168,56,110,110,96,100,52,78,90,110");

    static MenuItem Link(string header, string url)
    {
        var item = new MenuItem { Header = header };
        item.Click += (_, _) => ExternalLauncher.TryOpenUri(url);
        return item;
    }

    sealed class GridLine
    {
        public GridLine(GuardianGridEntry entry, string distance)
        {
            Entry = entry;
            Distance = distance;
        }

        public GuardianGridEntry Entry { get; }
        public string Distance { get; }

        public override string ToString() =>
            $"{Entry.Id}  {Entry.SystemName}  {Entry.BodyName}  {Distance}  {Entry.ArrivalText}  {Entry.SiteType}  {Entry.IndexText}  {Entry.SurveyText}";
    }
}

static class WidthExt
{
    public static T WithWidth<T>(this T control, double width) where T : Control
    {
        control.Width = width;
        control.Margin = new Avalonia.Thickness(0, 0, 6, 0);
        return control;
    }
}
