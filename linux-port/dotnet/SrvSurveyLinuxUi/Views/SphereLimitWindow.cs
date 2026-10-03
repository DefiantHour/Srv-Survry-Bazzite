using System;
using System.Globalization;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>FormSphereLimit. Writes the existing gs.sphereLimit* settings.</summary>
public sealed class SphereLimitWindow : Window
{
    readonly ComboBox _system = new() { MinWidth = 280, IsEditable = true };
    readonly TextBox _starPos = new() { IsReadOnly = true };
    readonly NumericUpDown _radius = new() { Minimum = 1, Maximum = 1000, Increment = 10, Value = 100 };
    readonly TextBox _currentSystem = new() { IsReadOnly = true };
    readonly TextBox _distance = new() { IsReadOnly = true };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap, Opacity = 0.8 };
    readonly AppConfigStore _config = new();
    readonly JournalSummary _journal;
    GuardianGridEntry? _target;

    public SphereLimitWindow()
    {
        Title = "Spherical Search";
        Width = 560;
        Height = 340;
        CanResize = false;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _config.Reload();
        var runtime = RuntimeStateSnapshot.TryLoad();
        var journalPath = runtime?.JournalFile;
        if (string.IsNullOrWhiteSpace(journalPath) && !string.IsNullOrWhiteSpace(runtime?.JournalFolder))
            journalPath = JournalSummaryReader.FindLatestJournal(runtime.JournalFolder);
        _journal = JournalSummaryReader.Read(journalPath);
        _currentSystem.Text = First(runtime?.System, _journal.System) ?? "";
        _radius.Value = (decimal)Math.Clamp(_config.SphereLimitRadiusLy, 1, 1000);

        var names = GuardianCatalogue.SystemNames().ToList();
        _system.ItemsSource = names;
        _system.SelectionChanged += (_, _) => ApplySelection(_system.SelectedItem as string ?? _system.Text);
        _system.LostFocus += (_, _) => ApplySelection(_system.Text);

        var matched = MatchSavedCenter(names);
        if (matched != null)
            _system.SelectedItem = matched;
        else if (!string.IsNullOrWhiteSpace(_currentSystem.Text)
            && names.Any(n => string.Equals(n, _currentSystem.Text, StringComparison.OrdinalIgnoreCase)))
            _system.Text = _currentSystem.Text;
        ApplySelection(_system.SelectedItem as string ?? _system.Text);

        var activate = new Button { Content = "Activate", MinWidth = 88, IsDefault = true };
        activate.Click += (_, _) => OnActivate();
        var disable = new Button { Content = "Disable", MinWidth = 88 };
        disable.Click += (_, _) =>
        {
            _config.SetSphereLimit(false, (double)_radius.Value, _config.SphereLimitX, _config.SphereLimitY, _config.SphereLimitZ);
            _status.Text = "Sphere limit disabled.";
            Close();
        };
        var cancel = new Button { Content = "Cancel", MinWidth = 88, IsCancel = true };
        cancel.Click += (_, _) => Close();

        var form = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("160,*"),
            RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,Auto"),
            Margin = new Avalonia.Thickness(0, 8, 0, 0),
        };
        AddRow(form, 0, "Enter central system:", _system);
        AddRow(form, 1, "Star pos:", _starPos);
        AddRow(form, 2, "Sphere radius:", _radius);
        AddRow(form, 3, "Current system:", _currentSystem);
        AddRow(form, 4, "Distance:", _distance);

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
                    Children = { activate, disable, cancel },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Spherical searches help navigating around within a given distance of a central system.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        form,
                    },
                },
            },
        };
    }

    void OnActivate()
    {
        ApplySelection(_system.SelectedItem as string ?? _system.Text);
        if (_target is not { HasStarPos: true })
        {
            _status.Text = "That system is not in allRuins.json or allStructures.json, so there is no star position to save.";
            return;
        }
        var radius = (double)(_radius.Value ?? 100);
        _config.SetSphereLimit(true, radius, _target.X, _target.Y, _target.Z);
        _status.Text = "Sphere limit active for " + _target.SystemName + ".";
        Close();
    }

    void ApplySelection(string? name)
    {
        _target = GuardianCatalogue.FindSystem(name);
        if (_target == null)
        {
            _starPos.Text = "";
            _distance.Text = "-";
            return;
        }
        _starPos.Text = GuardianCatalogue.FormatStarPos(_target.X, _target.Y, _target.Z);
        if (_journal.StarX is double x && _journal.StarY is double y && _journal.StarZ is double z)
        {
            var dist = GuardianCatalogue.DistanceLy(x, y, z, _target.X, _target.Y, _target.Z);
            _distance.Text = dist.ToString("N2", CultureInfo.InvariantCulture) + "ly";
        }
        else
        {
            _distance.Text = "-";
            _status.Text = "Current system star position is not in the latest journal, so distance stays blank.";
        }
    }

    string? MatchSavedCenter(System.Collections.Generic.IReadOnlyList<string> names)
    {
        if (!_config.SphereLimitActive && _config.SphereLimitX == 0 && _config.SphereLimitY == 0 && _config.SphereLimitZ == 0)
            return null;
        GuardianGridEntry? best = null;
        var bestDist = 0.05;
        foreach (var name in names)
        {
            var row = GuardianCatalogue.FindSystem(name);
            if (row is not { HasStarPos: true })
                continue;
            var dist = GuardianCatalogue.DistanceLy(
                _config.SphereLimitX, _config.SphereLimitY, _config.SphereLimitZ,
                row.X, row.Y, row.Z);
            if (dist < bestDist)
            {
                bestDist = dist;
                best = row;
            }
        }
        return best?.SystemName;
    }

    static void AddRow(Grid grid, int row, string label, Control field)
    {
        var text = new TextBlock
        {
            Text = label,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Avalonia.Thickness(0, 6, 8, 0),
        };
        Grid.SetRow(text, row);
        Grid.SetColumn(text, 0);
        field.Margin = new Avalonia.Thickness(0, 6, 0, 0);
        Grid.SetRow(field, row);
        Grid.SetColumn(field, 1);
        grid.Children.Add(text);
        grid.Children.Add(field);
    }

    static string? First(params string?[] values)
    {
        foreach (var value in values)
        {
            if (!string.IsNullOrWhiteSpace(value))
                return value;
        }
        return null;
    }
}
