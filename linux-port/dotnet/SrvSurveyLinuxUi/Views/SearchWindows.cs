using System;
using System.Globalization;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

public sealed class BoxelSearchWindow : Window
{
    readonly CheckBox _active;
    readonly TextBox _prefix;
    readonly TextBox _current;
    readonly TextBox _next;
    readonly ListBox _results;
    readonly TextBlock _status;
    readonly AppConfigStore _config = new();
    bool _busy;

    public BoxelSearchWindow()
    {
        Title = "Boxel Search";
        Width = 560;
        Height = 560;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _config.Reload();
        _active = new CheckBox
        {
            Content = "Boxel search active (gs.boxelSearchActive)",
            IsChecked = _config.BoxelSearchActive,
        };
        _prefix = new TextBox { Text = _config.BoxelSearchPrefix, PlaceholderText = "Prefix e.g. Col 285 Sector AB-C d" };
        _current = new TextBox { Text = _config.BoxelSearchCurrent, PlaceholderText = "Current boxel" };
        _next = new TextBox { Text = _config.BoxelSearchNextSystem, PlaceholderText = "Next system to copy" };
        _results = new ListBox { MinHeight = 180, MaxHeight = 240 };
        _results.DoubleTapped += (_, _) => UseSelectedAsNext();
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.8 };

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        buttons.Children.Add(MakeButton("Spansh Lookup", async (_, _) => await OnLookupAsync()));
        buttons.Children.Add(MakeButton("Use Selected → Next", (_, _) => UseSelectedAsNext()));
        buttons.Children.Add(MakeButton("Save", OnSave, true));
        buttons.Children.Add(MakeButton("Disable", OnDisable));
        buttons.Children.Add(MakeButton("Close", (_, _) => Close()));

        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(16),
            Children =
            {
                buttons.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new ScrollViewer
                {
                    Content = new StackPanel
                    {
                        Spacing = 8,
                        Children =
                        {
                            _active,
                            new TextBlock { Text = "Prefix" },
                            _prefix,
                            new TextBlock { Text = "Current" },
                            _current,
                            new TextBlock { Text = "Next System" },
                            _next,
                            new TextBlock { Text = "Spansh Results (double-click to set Next)" },
                            _results,
                            new TextBlock
                            {
                                Text = "Presenter PlotSphericalSearch reads gs.boxel* keys. Lookup uses Spansh systems/search (offline → cache).",
                                FontSize = 11,
                                Opacity = 0.7,
                                TextWrapping = TextWrapping.Wrap,
                            },
                        },
                    },
                },
            },
        };
    }

    async Task OnLookupAsync()
    {
        if (_busy)
            return;
        _busy = true;
        _status.Text = SpanshClient.IsOffline()
            ? "Looking up (offline/cache mode)…"
            : "Looking up on Spansh…";
        try
        {
            var result = await SpanshClient.LookupBoxelPrefixAsync(_prefix.Text ?? "");
            await Dispatcher.UIThread.InvokeAsync(() =>
            {
                _results.ItemsSource = result.Systems;
                _status.Text = result.Status;
                if (result.Systems.Count > 0
                    && string.IsNullOrWhiteSpace(_next.Text))
                    _next.Text = result.Systems[0].Name;
            });
        }
        finally
        {
            _busy = false;
        }
    }

    void UseSelectedAsNext()
    {
        if (_results.SelectedItem is SpanshSystemHit hit)
        {
            _next.Text = hit.Name;
            _status.Text = "Next system set to " + hit.Name;
        }
    }

    void OnSave(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        _config.SetBoxelSearch(
            _active.IsChecked == true,
            _prefix.Text ?? "",
            _current.Text ?? "",
            _next.Text ?? "");
        _status.Text = "Saved boxel search settings.";
    }

    void OnDisable(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        _active.IsChecked = false;
        _config.SetBoxelSearch(false, _prefix.Text ?? "", _current.Text ?? "", _next.Text ?? "");
        _status.Text = "Boxel search disabled.";
    }

    static Button MakeButton(
        string content,
        EventHandler<Avalonia.Interactivity.RoutedEventArgs> handler,
        bool isDefault = false)
    {
        var btn = new Button { Content = content, MinWidth = 80, IsDefault = isDefault };
        btn.Click += handler;
        return btn;
    }

    static Button MakeButton(
        string content,
        Func<object?, Avalonia.Interactivity.RoutedEventArgs, Task> handler)
    {
        var btn = new Button { Content = content, MinWidth = 80 };
        btn.Click += async (_, e) => await handler(_, e);
        return btn;
    }
}
