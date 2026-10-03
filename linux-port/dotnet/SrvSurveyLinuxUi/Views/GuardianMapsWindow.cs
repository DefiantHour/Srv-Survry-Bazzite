using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>
/// FormRuins ("Guardian Maps"). Draws the site template. Aerial photos are not bundled.
/// </summary>
public sealed class GuardianMapsWindow : Window
{
    static readonly string[] SiteTypes =
    {
        "All", "Alpha", "Beta", "Gamma", "Lacrosse", "Crossroads", "Fistbump",
        "Hammerbot", "Bear", "Bowl", "Turtle", "Robolobster", "Squid", "Stickyhand",
    };

    readonly ComboBox _siteType = new() { MinWidth = 140 };
    readonly ComboBox _site = new() { MinWidth = 360 };
    readonly CheckBox _legend = new() { Content = "Show legend", IsChecked = true };
    readonly CheckBox _notes = new() { Content = "Show notes" };
    readonly TextBox _notesBox = new() { AcceptsReturn = true, IsReadOnly = true, TextWrapping = TextWrapping.Wrap };
    readonly Canvas _canvas = new() { Background = new SolidColorBrush(Color.Parse("#141614")), MinHeight = 420 };
    readonly Border _legendBox;
    readonly TextBlock _selected = new() { Text = "" };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };
    readonly TextBlock _groups = new();
    readonly TextBlock _survey = new();
    readonly TextBlock _zoomLabel = new();
    readonly List<Placed> _placed = new();
    double _zoom = 1;
    bool _filling;

    public GuardianMapsWindow(GuardianGridEntry? focus = null)
    {
        Title = "Guardian Maps";
        Width = 980;
        Height = 680;
        MinWidth = 640;
        MinHeight = 420;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _siteType.ItemsSource = SiteTypes;
        _siteType.SelectedIndex = 0;
        _legendBox = BuildLegend();
        _notesBox.Text = "No surveyed-site notes file is loaded. The public catalogue does not include per-site notes.";
        _notes.IsCheckedChanged += (_, _) => _notesBox.IsVisible = _notes.IsChecked == true;
        _notesBox.IsVisible = false;
        _legend.IsCheckedChanged += (_, _) => _legendBox.IsVisible = _legend.IsChecked == true;
        _siteType.SelectionChanged += (_, _) => FillSites(null);
        _site.SelectionChanged += (_, _) => Redraw();
        _canvas.SizeChanged += (_, _) => Redraw();
        _canvas.PointerWheelChanged += OnWheel;
        _canvas.PointerPressed += OnPress;

        var top = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            Margin = new Thickness(8),
            Children =
            {
                _siteType,
                new TextBlock { Text = "Select site:", VerticalAlignment = VerticalAlignment.Center },
                _site,
                _legend,
                _notes,
            },
        };

        var bar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 16,
            Margin = new Thickness(8, 4),
            Children = { _selected, _status, _groups, _survey, _zoomLabel },
        };

        var mapLayer = new Grid
        {
            Children = { _canvas, _legendBox },
        };
        _legendBox.HorizontalAlignment = HorizontalAlignment.Left;
        _legendBox.VerticalAlignment = VerticalAlignment.Top;
        _legendBox.Margin = new Thickness(12);

        Content = new DockPanel
        {
            Children =
            {
                bar.WithDock(Dock.Bottom),
                top.WithDock(Dock.Top),
                new Grid
                {
                    ColumnDefinitions = new ColumnDefinitions("*,220"),
                    Children =
                    {
                        mapLayer,
                        _notesBox.WithGridColumn(1),
                    },
                },
            },
        };

        var initialType = focus?.SiteType;
        if (!string.IsNullOrWhiteSpace(initialType) && SiteTypes.Contains(initialType))
            _siteType.SelectedItem = initialType;
        FillSites(focus);
    }

    void FillSites(GuardianGridEntry? focus)
    {
        _filling = true;
        var type = _siteType.SelectedItem as string ?? "All";
        var items = new List<SiteChoice>();
        if (type == "All")
        {
            foreach (var name in SiteTypes.Skip(1))
                items.Add(SiteChoice.Template(name));
        }
        else
        {
            items.Add(SiteChoice.Template(type));
            foreach (var row in GuardianCatalogue.Load())
            {
                if (!string.Equals(row.SiteType, type, StringComparison.OrdinalIgnoreCase))
                    continue;
                if (row.Kind == "Beacon")
                    continue;
                items.Add(new SiteChoice(row));
            }
        }
        _site.ItemsSource = items;
        SiteChoice? selected = null;
        if (focus != null)
        {
            selected = items.FirstOrDefault(i =>
                i.Entry != null
                && string.Equals(i.Entry.SystemName, focus.SystemName, StringComparison.OrdinalIgnoreCase)
                && string.Equals(i.Entry.BodyName, focus.BodyName, StringComparison.OrdinalIgnoreCase)
                && i.Entry.IndexText == focus.IndexText);
        }
        _site.SelectedItem = selected ?? (items.Count > 0 ? items[0] : null);
        _filling = false;
        Redraw();
    }

    void OnWheel(object? sender, PointerWheelEventArgs e)
    {
        _zoom = Math.Clamp(_zoom * (e.Delta.Y > 0 ? 1.15 : 1 / 1.15), 0.25, 6);
        Redraw();
    }

    void OnPress(object? sender, PointerPressedEventArgs e)
    {
        var at = e.GetPosition(_canvas);
        Placed? best = null;
        var bestDist = 14.0;
        foreach (var poi in _placed)
        {
            var dx = poi.X - at.X;
            var dy = poi.Y - at.Y;
            var d = Math.Sqrt(dx * dx + dy * dy);
            if (d < bestDist)
            {
                best = poi;
                bestDist = d;
            }
        }
        _selected.Text = best == null ? "" : $"{best.Poi.Name} ({best.Poi.Type})";
    }

    void Redraw()
    {
        if (_filling)
            return;
        _canvas.Children.Clear();
        _placed.Clear();
        var choice = _site.SelectedItem as SiteChoice;
        var typeName = choice?.TemplateType ?? (_siteType.SelectedItem as string ?? "");
        var template = GuardianTemplateLoader.Load(typeName);
        var w = Math.Max(200, _canvas.Bounds.Width);
        var h = Math.Max(200, _canvas.Bounds.Height);
        var cx = w / 2;
        var cy = h / 2;

        if (template == null)
        {
            _status.Text = string.IsNullOrWhiteSpace(typeName)
                ? "Select a site type."
                : $"No template named {typeName} in guardianSiteTemplates.json.";
            _groups.Text = "Obelisk groups:";
            _survey.Text = "Survey:";
            _zoomLabel.Text = "Zoom: " + _zoom.ToString("0.##", CultureInfo.InvariantCulture);
            return;
        }

        var max = template.Pois.Count == 0 ? 1 : template.Pois.Max(p => p.Dist);
        var fit = Math.Min(w, h) * 0.42 / Math.Max(1, max);
        var scale = fit * _zoom;

        foreach (var poi in template.Pois)
        {
            var rad = poi.Angle * Math.PI / 180.0;
            var x = cx + Math.Sin(rad) * poi.Dist * scale;
            var y = cy - Math.Cos(rad) * poi.Dist * scale;
            _placed.Add(new Placed(poi, x, y));
            _canvas.Children.Add(Mark(poi, x, y));
        }

        var entry = choice?.Entry;
        if (entry?.SiteHeading is int heading && heading >= 0)
            _canvas.Children.Add(HeadingLine(cx, cy, heading, Color.Parse("#7ec8e3"), scale));
        if (entry?.RelicTowerHeading is int tower && tower > 0)
            _canvas.Children.Add(HeadingLine(cx, cy, tower, Color.Parse("#d4a017"), scale));

        var groups = template.Pois
            .Where(p => p.Type.Contains("obelisk", StringComparison.OrdinalIgnoreCase) && p.Name.Length > 0)
            .Select(p => char.ToUpperInvariant(p.Name[0]).ToString())
            .Distinct()
            .OrderBy(g => g, StringComparer.Ordinal)
            .ToList();
        _groups.Text = "Obelisk groups: " + string.Join("", groups);

        var siteHeading = entry?.SiteHeading is int sh && sh >= 0 ? sh + "°" : "?";
        var towerHeading = entry?.RelicTowerHeading is int th && th > 0 ? th + "°" : "?";
        var photo = string.IsNullOrWhiteSpace(template.BackgroundImage)
            ? "Aerial image is not in the template (backgroundImage is empty)."
            : "Background: " + template.BackgroundImage;
        _status.Text =
            $"Relic Towers: —, puddles: —, site heading: {siteHeading}, relic tower heading: {towerHeading}, active obelisks: —. {photo}";
        _survey.Text = string.IsNullOrWhiteSpace(entry?.SurveyText)
            ? "Survey: —"
            : "Survey: " + entry.SurveyText;
        _zoomLabel.Text = "Zoom: " + _zoom.ToString("0.##", CultureInfo.InvariantCulture);
        if (template.Pois.Count == 0)
            _status.Text = $"Template {typeName} has no poi list. {photo}";
    }

    static Control Mark(GuardianTemplatePoi poi, double x, double y)
    {
        var kind = poi.Type.ToLowerInvariant();
        if (kind.Contains("relic"))
        {
            var poly = new Polygon
            {
                Fill = new SolidColorBrush(Color.Parse("#d4a017")),
                Points = new Points { new Point(0, -7), new Point(6, 6), new Point(-6, 6) },
            };
            Canvas.SetLeft(poly, x);
            Canvas.SetTop(poly, y);
            return poly;
        }
        var color = kind switch
        {
            "obelisk" => "#7ec8e3",
            "brokeobelisk" => "#8a8f86",
            "orb" => "#3d9a6a",
            "casket" => "#c4a35a",
            "tablet" => "#6aa8c8",
            "totem" => "#c46b4a",
            "urn" => "#8f7352",
            "pylon" => "#d0d4c8",
            "component" => "#c46b4a",
            _ => "#c7c1b0",
        };
        var mark = new Border
        {
            Width = kind.Contains("obelisk") ? 4 : 8,
            Height = kind.Contains("obelisk") ? 12 : 8,
            Background = new SolidColorBrush(Color.Parse(color)),
        };
        Canvas.SetLeft(mark, x - mark.Width / 2);
        Canvas.SetTop(mark, y - mark.Height / 2);
        return mark;
    }

    static Line HeadingLine(double cx, double cy, int degrees, Color color, double scale)
    {
        var rad = degrees * Math.PI / 180.0;
        var len = 80 * Math.Clamp(scale * 40, 0.6, 2.4);
        var line = new Line
        {
            StartPoint = new Point(cx, cy),
            EndPoint = new Point(cx + Math.Sin(rad) * len, cy - Math.Cos(rad) * len),
            Stroke = new SolidColorBrush(color),
            StrokeThickness = 2,
        };
        return line;
    }

    static Border BuildLegend()
    {
        var stack = new StackPanel { Spacing = 2 };
        stack.Children.Add(new TextBlock { Text = "Legend", FontWeight = FontWeight.SemiBold });
        foreach (var (label, color) in new (string, string)[]
        {
            ("Relic Tower", "#d4a017"),
            ("Orb", "#3d9a6a"),
            ("Casket", "#c4a35a"),
            ("Tablet", "#6aa8c8"),
            ("Totem", "#c46b4a"),
            ("Urn", "#8f7352"),
            ("Empty puddle", "#6e675c"),
            ("Obelisk", "#7ec8e3"),
            ("Site heading", "#7ec8e3"),
            ("Tower heading", "#d4a017"),
            ("Survey needed", "#8a8f86"),
        })
        {
            stack.Children.Add(new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Spacing = 6,
                Children =
                {
                    new Border
                    {
                        Width = 10,
                        Height = 10,
                        Background = new SolidColorBrush(Color.Parse(color)),
                        VerticalAlignment = VerticalAlignment.Center,
                    },
                    new TextBlock { Text = label, FontSize = 12, Foreground = Brushes.Wheat },
                },
            });
        }
        return new Border
        {
            Background = new SolidColorBrush(Color.Parse("#CC1B1A16")),
            BorderBrush = new SolidColorBrush(Color.Parse("#8a7d62")),
            BorderThickness = new Thickness(1),
            Padding = new Thickness(8),
            Child = stack,
            IsHitTestVisible = false,
        };
    }

    sealed class SiteChoice
    {
        public SiteChoice(string templateType)
        {
            TemplateType = templateType;
            Label = templateType + " Template";
        }

        public SiteChoice(GuardianGridEntry entry)
        {
            Entry = entry;
            TemplateType = entry.SiteType;
            Label = $"{entry.SystemName} {entry.BodyName} {entry.IndexText}".Trim();
        }

        public static SiteChoice Template(string type) => new(type);

        public string TemplateType { get; }
        public string Label { get; }
        public GuardianGridEntry? Entry { get; }

        public override string ToString() => Label;
    }

    sealed class Placed
    {
        public Placed(GuardianTemplatePoi poi, double x, double y)
        {
            Poi = poi;
            X = x;
            Y = y;
        }

        public GuardianTemplatePoi Poi { get; }
        public double X { get; }
        public double Y { get; }
    }
}

static class GridColumnExt
{
    public static T WithGridColumn<T>(this T control, int column) where T : Control
    {
        Grid.SetColumn(control, column);
        return control;
    }
}
