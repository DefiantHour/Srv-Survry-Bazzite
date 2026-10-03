using System;
using System.Collections.Generic;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

public sealed class BeaconsWindow : Window
{
    readonly TextBox _filter;
    readonly ListBox _list;
    readonly TextBlock _status;
    readonly IReadOnlyList<GuardianSiteRow> _all;

    public BeaconsWindow()
    {
        Title = "Guardian Sites — Beacons";
        Width = 720;
        Height = 520;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _all = GuardianSiteStore.LoadBeacons();
        _filter = new TextBox { PlaceholderText = "Filter system / body…" };
        _filter.TextChanged += (_, _) => ApplyFilter();
        _list = new ListBox { MinHeight = 340 };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.85 };

        var canonn = new Button { Content = "Canonn Signals", MinWidth = 120 };
        canonn.Click += (_, _) =>
        {
            if (_list.SelectedItem is SiteItem item && !string.IsNullOrWhiteSpace(item.Row.SystemName))
            {
                ExternalLauncher.TryOpenUri(
                    "https://canonn-science.github.io/canonn-signals/?system="
                    + Uri.EscapeDataString(item.Row.SystemName));
            }
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
                    Children = { canonn, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = $"Source: {DataFileLocator.AllBeaconsPath}",
                            FontSize = 11,
                            Opacity = 0.75,
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _filter,
                        _list,
                    },
                },
            },
        };

        ApplyFilter();
    }

    void ApplyFilter()
    {
        var q = (_filter.Text ?? "").Trim();
        IEnumerable<GuardianSiteRow> rows = _all;
        if (!string.IsNullOrEmpty(q))
        {
            rows = rows.Where(r =>
                r.SystemName.Contains(q, StringComparison.OrdinalIgnoreCase)
                || r.BodyName.Contains(q, StringComparison.OrdinalIgnoreCase)
                || r.SiteType.Contains(q, StringComparison.OrdinalIgnoreCase));
        }

        var list = rows.Select(r => new SiteItem(r)).ToList();
        _list.ItemsSource = list;
        _status.Text = $"{list.Count} of {_all.Count} beacons";
    }

    sealed class SiteItem
    {
        public SiteItem(GuardianSiteRow row) => Row = row;
        public GuardianSiteRow Row { get; }
        public override string ToString() =>
            $"{Row.SystemName} · {Row.BodyName} · {Row.Summary}";
    }
}

public sealed class RuinsWindow : Window
{
    readonly TextBox _filter;
    readonly ListBox _list;
    readonly TextBlock _status;
    readonly IReadOnlyList<GuardianSiteRow> _all;

    public RuinsWindow()
    {
        Title = "Guardian Survey Maps — Ruins";
        Width = 780;
        Height = 560;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _all = GuardianSiteStore.LoadRuins();
        _filter = new TextBox { PlaceholderText = "Filter system / body / site type…" };
        _filter.TextChanged += (_, _) => ApplyFilter();
        _list = new ListBox { MinHeight = 380 };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.85 };

        var canonn = new Button { Content = "Canonn Signals", MinWidth = 120 };
        canonn.Click += (_, _) =>
        {
            if (_list.SelectedItem is SiteItem item && !string.IsNullOrWhiteSpace(item.Row.SystemName))
            {
                ExternalLauncher.TryOpenUri(
                    "https://canonn-science.github.io/canonn-signals/?system="
                    + Uri.EscapeDataString(item.Row.SystemName));
            }
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
                    Children = { canonn, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = $"Source: {DataFileLocator.AllRuinsPath} — list/filter only; interactive map editor remains thin on Linux.",
                            FontSize = 11,
                            Opacity = 0.75,
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _filter,
                        _list,
                    },
                },
            },
        };

        ApplyFilter();
    }

    void ApplyFilter()
    {
        var q = (_filter.Text ?? "").Trim();
        IEnumerable<GuardianSiteRow> rows = _all;
        if (!string.IsNullOrEmpty(q))
        {
            rows = rows.Where(r =>
                r.SystemName.Contains(q, StringComparison.OrdinalIgnoreCase)
                || r.BodyName.Contains(q, StringComparison.OrdinalIgnoreCase)
                || r.SiteType.Contains(q, StringComparison.OrdinalIgnoreCase)
                || r.Summary.Contains(q, StringComparison.OrdinalIgnoreCase));
        }

        var list = rows.Take(2000).Select(r => new SiteItem(r)).ToList();
        _list.ItemsSource = list;
        _status.Text = $"{list.Count} shown of {_all.Count} ruins";
    }

    sealed class SiteItem
    {
        public SiteItem(GuardianSiteRow row) => Row = row;
        public GuardianSiteRow Row { get; }
        public override string ToString()
        {
            var latlong = Row.Latitude.HasValue && Row.Longitude.HasValue
                ? $" · {Row.Latitude:0.##}, {Row.Longitude:0.##}"
                : "";
            return $"{Row.SystemName} · {Row.BodyName} · {Row.Summary}{latlong}";
        }
    }
}
