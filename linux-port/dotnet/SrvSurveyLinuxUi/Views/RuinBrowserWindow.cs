using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>
/// Interactive ruin browser: catalogue row plus the matching site template's POIs.
/// Pan and zoom the site, click a POI for heading and type. Separate from the galactic pan map.
/// </summary>
public sealed class RuinBrowserWindow : Window
{
    readonly ListBox _list = new();
    readonly Canvas _canvas = new() { Background = new SolidColorBrush(Color.Parse("#10120e")), MinHeight = 360 };
    readonly TextBox _filter = new() { PlaceholderText = "Filter system, body, or site type" };
    readonly TextBlock _detail = new() { TextWrapping = TextWrapping.Wrap };
    readonly List<GuardianSiteRow> _ruins;
    readonly List<TemplatePoi> _pois = new();
    readonly List<GroupLabel> _groups = new();
    double _panX = 280;
    double _panY = 180;
    double _scale = 0.6;
    Point? _last;

    public RuinBrowserWindow()
    {
        Title = "Guardian Ruin Browser";
        Width = 980;
        Height = 680;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        _ruins = GuardianSiteStore.LoadRuins().ToList();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        _filter.TextChanged += (_, _) => ApplyFilter();
        _list.SelectionChanged += (_, _) => LoadSelection();
        _canvas.PointerPressed += OnPressed;
        _canvas.PointerMoved += OnMoved;
        _canvas.PointerReleased += (_, _) => _last = null;
        _canvas.PointerWheelChanged += OnWheel;
        Content = new DockPanel
        {
            Margin = new Thickness(12),
            Children =
            {
                close.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 0),
                _detail.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 0),
                new Grid
                {
                    ColumnDefinitions = new ColumnDefinitions("280,*"),
                    RowDefinitions = new RowDefinitions("Auto,*"),
                    Children =
                    {
                        _filter.WithGrid(0, 0),
                        _list.WithGrid(0, 1),
                        new TextBlock
                        {
                            Text = "Drag to pan. Wheel zooms. Obelisks are bars, relics are triangles, pylons are diamonds, components are chevrons.",
                            Margin = new Thickness(12, 0, 0, 8),
                        }.WithGrid(1, 0),
                        _canvas.WithGrid(1, 1).WithMargin(12, 0, 0, 0),
                    },
                },
            },
        };
        ApplyFilter();
    }

    void ApplyFilter()
    {
        var needle = (_filter.Text ?? "").Trim();
        var rows = string.IsNullOrWhiteSpace(needle)
            ? _ruins
            : _ruins.Where(r =>
                r.SystemName.Contains(needle, StringComparison.OrdinalIgnoreCase)
                || r.BodyName.Contains(needle, StringComparison.OrdinalIgnoreCase)
                || r.SiteType.Contains(needle, StringComparison.OrdinalIgnoreCase)
                || r.Summary.Contains(needle, StringComparison.OrdinalIgnoreCase)).ToList();
        _list.ItemsSource = rows.Select(r => $"{r.SystemName} {r.BodyName} — {r.Summary}").ToList();
        _list.Tag = rows;
        _detail.Text = $"{rows.Count} ruin(s).";
    }

    void LoadSelection()
    {
        if (_list.Tag is not List<GuardianSiteRow> rows || _list.SelectedIndex < 0 || _list.SelectedIndex >= rows.Count)
            return;
        var row = rows[_list.SelectedIndex];
        _pois.Clear();
        _groups.Clear();
        _pois.AddRange(LoadTemplate(row.SiteType, _groups));
        _detail.Text = $"{row.SystemName} {row.BodyName} · {row.Summary}"
            + (row.Latitude is double lat && row.Longitude is double lon
                ? $" · {lat:0.####}, {lon:0.####}"
                : "")
            + $" · {_pois.Count} template POI(s)";
        Redraw(null);
    }

    static IEnumerable<TemplatePoi> LoadTemplate(string siteType, List<GroupLabel> groups)
    {
        var root = DataFileLocator.WorkspaceRoot;
        if (string.IsNullOrWhiteSpace(root))
            yield break;
        var path = System.IO.Path.Combine(root, "SrvSurvey", "guardianSiteTemplates.json");
        if (!File.Exists(path))
            yield break;
        JsonDocument doc;
        try
        {
            doc = JsonDocument.Parse(File.ReadAllText(path));
        }
        catch
        {
            yield break;
        }
        using (doc)
        {
            if (!doc.RootElement.TryGetProperty(siteType, out var site)
                || !site.TryGetProperty("poi", out var poi)
                || poi.ValueKind != JsonValueKind.Array)
                yield break;
            foreach (var el in poi.EnumerateArray())
            {
                var name = el.TryGetProperty("name", out var n) ? n.GetString() : null;
                if (string.IsNullOrWhiteSpace(name))
                    continue;
                var angle = el.TryGetProperty("angle", out var a) && a.TryGetDouble(out var av) ? av : 0;
                var dist = el.TryGetProperty("dist", out var d) && d.TryGetDouble(out var dv) ? dv : 0;
                var rot = el.TryGetProperty("rot", out var r) && r.TryGetDouble(out var rv) ? rv : 0;
                var type = el.TryGetProperty("type", out var t) ? t.GetString() ?? "" : "";
                yield return new TemplatePoi(name!, type, angle, dist, rot);
            }
            if (site.TryGetProperty("obeliskGroupNameLocations", out var labels)
                && labels.ValueKind == JsonValueKind.Object)
            {
                foreach (var label in labels.EnumerateObject())
                {
                    if (label.Value.ValueKind != JsonValueKind.Object)
                        continue;
                    if (label.Value.TryGetProperty("IsEmpty", out var empty) && empty.ValueKind == JsonValueKind.True)
                        continue;
                    if (!label.Value.TryGetProperty("X", out var xEl) || !xEl.TryGetDouble(out var groupAngle))
                        continue;
                    if (!label.Value.TryGetProperty("Y", out var yEl) || !yEl.TryGetDouble(out var groupDist))
                        continue;
                    groups.Add(new GroupLabel(label.Name, groupAngle, groupDist));
                }
            }
        }
    }

    void Redraw(TemplatePoi? selected)
    {
        _canvas.Children.Clear();
        foreach (var group in _groups)
        {
            var point = Place(group.Angle, group.Dist);
            var letter = new TextBlock
            {
                Text = group.Name,
                Foreground = new SolidColorBrush(Color.Parse("#7fbfbf")),
                FontSize = 16,
            };
            Canvas.SetLeft(letter, point.X - 6);
            Canvas.SetTop(letter, point.Y - 10);
            _canvas.Children.Add(letter);
        }
        foreach (var poi in _pois)
        {
            var point = Place(poi.Angle, poi.Dist);
            var mark = MarkFor(poi, selected == poi);
            Canvas.SetLeft(mark, point.X);
            Canvas.SetTop(mark, point.Y);
            _canvas.Children.Add(mark);
        }
    }

    Point Place(double angle, double dist)
    {
        var rad = angle * Math.PI / 180.0;
        return new Point(_panX + Math.Sin(rad) * dist * _scale, _panY - Math.Cos(rad) * dist * _scale);
    }

    static Control MarkFor(TemplatePoi poi, bool selected)
    {
        var fill = new SolidColorBrush(selected ? Color.Parse("#f2e6c9") : FillFor(poi.Kind));
        var stroke = new SolidColorBrush(Color.Parse("#f2e6c9"));
        return poi.Kind switch
        {
            "obelisk" or "brokeObelisk" => new Border
            {
                Width = 8,
                Height = 14,
                Background = fill,
                BorderBrush = new SolidColorBrush(Color.Parse("#7ec8c8")),
                BorderThickness = new Thickness(1),
                Tag = poi,
            },
            "relic" => new Polygon
            {
                Points = new Points { new Point(6, 0), new Point(0, 12), new Point(12, 12) },
                Fill = fill,
                Stroke = stroke,
                Tag = poi,
            },
            "pylon" => new Polygon
            {
                Points = new Points { new Point(8, 0), new Point(16, 6), new Point(8, 12), new Point(0, 6) },
                Fill = fill,
                Stroke = stroke,
                Tag = poi,
            },
            "component" => new Polygon
            {
                Points = new Points { new Point(6, 0), new Point(0, 8), new Point(12, 8), new Point(6, 0), new Point(6, 4), new Point(2, 12), new Point(10, 12) },
                Fill = null,
                Stroke = fill,
                StrokeThickness = 1.5,
                Tag = poi,
            },
            _ => new Ellipse
            {
                Width = 8,
                Height = 8,
                Fill = fill,
                Stroke = stroke,
                Tag = poi,
            },
        };
    }

    static Color FillFor(string kind) => kind switch
    {
        "obelisk" => Color.Parse("#d8d8d8"),
        "brokeObelisk" => Color.Parse("#6e6e6e"),
        "relic" => Color.Parse("#e07020"),
        "pylon" => Color.Parse("#3aa0a0"),
        "component" => Color.Parse("#c4a15a"),
        _ => Color.Parse("#d4782a"),
    };

    void OnPressed(object? sender, PointerPressedEventArgs e)
    {
        var point = e.GetPosition(_canvas);
        TemplatePoi? hit = null;
        foreach (var poi in _pois)
        {
            var placed = Place(poi.Angle, poi.Dist);
            if (Math.Abs(placed.X - point.X) < 12 && Math.Abs(placed.Y - point.Y) < 12)
                hit = poi;
        }
        if (hit != null)
        {
            _detail.Text = $"{hit.Name} · {hit.Kind} · heading {hit.Rot:0.#}° · {hit.Dist:0} m · angle {hit.Angle:0.#}";
            Redraw(hit);
            return;
        }
        _last = point;
    }

    void OnMoved(object? sender, PointerEventArgs e)
    {
        if (_last is not Point last)
            return;
        var point = e.GetPosition(_canvas);
        _panX += point.X - last.X;
        _panY += point.Y - last.Y;
        _last = point;
        Redraw(null);
    }

    void OnWheel(object? sender, PointerWheelEventArgs e)
    {
        _scale = Math.Clamp(_scale + e.Delta.Y * 0.08, 0.15, 3);
        Redraw(null);
    }

    sealed record TemplatePoi(string Name, string Kind, double Angle, double Dist, double Rot);

    sealed record GroupLabel(string Name, double Angle, double Dist);
}

static class GridAttach
{
    public static T WithGrid<T>(this T control, int column, int row) where T : Control
    {
        Grid.SetColumn(control, column);
        Grid.SetRow(control, row);
        return control;
    }
}
