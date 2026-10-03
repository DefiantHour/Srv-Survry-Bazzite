using System;
using System.Globalization;
using System.Text.RegularExpressions;
using Avalonia.Controls;
using Avalonia.Input.Platform;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

public sealed class GroundTargetWindow : Window
{
    static readonly Regex PastePattern = new(
        @"([+\-.0-9]+)\s*[ ,|`/]\s*([+\-.0-9]+)",
        RegexOptions.Compiled);

    readonly TextBox _lat;
    readonly TextBox _lng;
    readonly TextBlock _status;
    readonly AppConfigStore _config = new();
    readonly string? _journalFolder;

    public GroundTargetWindow(string? journalFolder = null)
    {
        _journalFolder = journalFolder;
        Title = "Set lat/long co-ordinates";
        Width = 520;
        Height = 280;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        CanResize = false;

        _config.Reload();
        _lat = new TextBox
        {
            Text = _config.TargetLat.ToString("+0.######;-0.######;0", CultureInfo.InvariantCulture),
        };
        _lng = new TextBox
        {
            Text = _config.TargetLong.ToString("+0.######;-0.######;0", CultureInfo.InvariantCulture),
        };
        _status = new TextBlock
        {
            Text = _config.TargetLatLongActive
                ? $"Active target: {_config.TargetLat:0.####}, {_config.TargetLong:0.####}"
                : "No active ground target",
            TextWrapping = TextWrapping.Wrap,
            Opacity = 0.8,
        };

        var rowButtons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            Children =
            {
                MakeButton("Clear target", OnClear),
                MakeButton("Target current location", OnUseCurrent),
                MakeButton("Paste", OnPaste),
            },
        };
        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
            Children =
            {
                MakeButton("Set target", OnSet, isDefault: true),
                MakeButton("Cancel", (_, _) => Close()),
            },
        };

        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(16),
            Children =
            {
                buttons.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Got a tip from a mysterious stranger to go to some Lat/Long on some planet or moon?\n\nEnter some Lat/Long position and guidance will appear when you approach.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        new Grid
                        {
                            ColumnDefinitions = new ColumnDefinitions("Auto,*"),
                            RowDefinitions = new RowDefinitions("Auto,Auto,Auto"),
                            Children =
                            {
                                new TextBlock { Text = "Latitude:", VerticalAlignment = VerticalAlignment.Center },
                                _lat.WithCell(1, 0),
                                new TextBlock { Text = "Longitude:", VerticalAlignment = VerticalAlignment.Center, Margin = new Avalonia.Thickness(0, 8, 8, 0) }.WithCell(0, 1),
                                _lng.WithCell(1, 1).WithMargin(0, 8, 0, 0),
                                rowButtons.WithCell(1, 2).WithMargin(0, 8, 0, 0),
                            },
                        },
                    },
                },
            },
        };
    }

    void OnSet(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (!TryParse(_lat.Text, out var lat) || !TryParse(_lng.Text, out var lng))
        {
            _status.Text = "Enter valid latitude and longitude numbers.";
            return;
        }

        if (lat is < -90 or > 90 || lng is < -180 or > 180)
        {
            _status.Text = "Latitude must be −90…90 and longitude −180…180.";
            return;
        }

        _config.SetGroundTarget(lat, lng, true);
        _status.Text = $"Target set: {lat:0.####}, {lng:0.####}";
    }

    void OnClear(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        _config.ClearGroundTarget();
        _lat.Text = "0";
        _lng.Text = "0";
        _status.Text = "Ground target cleared.";
    }

    void OnUseCurrent(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_journalFolder))
        {
            _status.Text = "Journal folder unknown — cannot read Status.json.";
            return;
        }

        var status = EliteStatusReader.TryRead(_journalFolder);
        if (status?.Latitude == null || status.Longitude == null)
        {
            _status.Text = "Status.json has no Latitude/Longitude (need to be near a body).";
            return;
        }

        _lat.Text = status.Latitude.Value.ToString(CultureInfo.InvariantCulture);
        _lng.Text = status.Longitude.Value.ToString(CultureInfo.InvariantCulture);
        _status.Text = "Filled from Status.json current position.";
    }

    async void OnPaste(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (Clipboard == null)
        {
            _status.Text = "Clipboard unavailable.";
            return;
        }

        var text = await Clipboard.TryGetTextAsync();
        if (string.IsNullOrWhiteSpace(text))
        {
            _status.Text = "Clipboard is empty.";
            return;
        }

        text = text.Replace("°N", ", ").Replace("°W", "");
        var match = PastePattern.Match(text);
        if (!match.Success
            || !TryParse(match.Groups[1].Value, out var lat)
            || !TryParse(match.Groups[2].Value, out var lng))
        {
            _status.Text = "Clipboard did not contain lat, long.";
            return;
        }

        _lat.Text = lat.ToString(CultureInfo.InvariantCulture);
        _lng.Text = lng.ToString(CultureInfo.InvariantCulture);
        _status.Text = "Pasted from clipboard.";
    }

    static bool TryParse(string? text, out double value) =>
        double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out value)
        || double.TryParse(text, NumberStyles.Float, CultureInfo.CurrentCulture, out value);

    static Button MakeButton(
        string content,
        EventHandler<Avalonia.Interactivity.RoutedEventArgs> handler,
        bool isDefault = false)
    {
        var btn = new Button { Content = content, MinWidth = 72, IsDefault = isDefault };
        btn.Click += handler;
        return btn;
    }
}

static class ControlLayoutExtensions
{
    public static T WithDock<T>(this T control, Dock dock) where T : Control
    {
        DockPanel.SetDock(control, dock);
        return control;
    }

    public static T WithMargin<T>(this T control, double left, double top, double right, double bottom)
        where T : Control
    {
        control.Margin = new Avalonia.Thickness(left, top, right, bottom);
        return control;
    }

    public static T WithCell<T>(this T control, int column, int row) where T : Control
    {
        Grid.SetColumn(control, column);
        Grid.SetRow(control, row);
        return control;
    }
}
