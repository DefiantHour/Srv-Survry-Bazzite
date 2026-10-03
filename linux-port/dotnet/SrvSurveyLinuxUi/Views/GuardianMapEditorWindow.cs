using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform.Storage;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>
/// Site editor for guardian extra_poi: drag x/y, and edit heading plus POI status.
/// Writes the commander JSON the overlay reads.
/// </summary>
public sealed class GuardianMapEditorWindow : Window
{
    static readonly string[] StatusChoices = { "unknown", "present", "absent", "empty" };

    readonly Canvas _canvas = new() { Background = new SolidColorBrush(Color.Parse("#12140f")), MinHeight = 360 };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };
    readonly TextBox _heading = new() { PlaceholderText = "Heading / rot", MinWidth = 120 };
    readonly TextBox _angle = new() { PlaceholderText = "Angle", MinWidth = 80 };
    readonly TextBox _dist = new() { PlaceholderText = "Distance", MinWidth = 90 };
    readonly ComboBox _poiStatus = new() { ItemsSource = StatusChoices, MinWidth = 140 };
    readonly TextBlock _selected = new() { Text = "No POI selected." };
    readonly List<PoiDot> _dots = new();
    string? _path;
    JsonNode? _root;
    PoiDot? _drag;
    PoiDot? _current;
    string? _backgroundPath;
    Point _grab;

    public GuardianMapEditorWindow()
    {
        Title = "Edit Guardian Map";
        Width = 720;
        Height = 640;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        var add = new Button { Content = "New POI", MinWidth = 80 };
        add.Click += (_, _) => AddPoi();
        var remove = new Button { Content = "Remove POI", MinWidth = 100 };
        remove.Click += (_, _) => RemovePoi();
        var save = new Button { Content = "Save", MinWidth = 80 };
        save.Click += (_, _) => Save();
        var background = new Button { Content = "Background", MinWidth = 100 };
        background.Click += async (_, _) => await PickBackground();
        var apply = new Button { Content = "Apply Heading / Status", MinWidth = 160 };
        apply.Click += (_, _) => ApplyFields();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();

        Content = new DockPanel
        {
            Margin = new Thickness(12),
            Children =
            {
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { background, add, remove, apply, save, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Drag a marker to move it. Angle, distance, heading, and status are written on the active guardian site.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _selected,
                        new StackPanel
                        {
                            Orientation = Orientation.Horizontal,
                            Spacing = 8,
                            Children = { _angle, _dist, _heading, _poiStatus },
                        },
                        _canvas,
                    },
                },
            },
        };

        _canvas.PointerPressed += OnPressed;
        _canvas.PointerMoved += OnMoved;
        _canvas.PointerReleased += (_, _) => _drag = null;
        Load();
    }

    void Load()
    {
        _path = Directory.GetFiles(DataFileLocator.CmdrDirectory, "*.json")
            .OrderByDescending(File.GetLastWriteTimeUtc)
            .FirstOrDefault();
        if (_path == null)
        {
            _status.Text = "No commander JSON yet. Survey a site first.";
            return;
        }
        _root = JsonNode.Parse(File.ReadAllText(_path));
        var poi = ActiveSite()?["extra_poi"] as JsonArray;
        _dots.Clear();
        if (poi != null)
        {
            var i = 0;
            foreach (var node in poi)
            {
                var angle = node?["angle"]?.GetValue<double>() ?? 0;
                var dist = node?["dist"]?.GetValue<double>() ?? 0;
                var x = 320 + (dist * Math.Sin(angle * Math.PI / 180.0));
                var y = 180 - (dist * Math.Cos(angle * Math.PI / 180.0));
                if (node?["angle"] == null && node?["x"] != null)
                    x = node["x"]!.GetValue<double>();
                if (node?["dist"] == null && node?["y"] != null)
                    y = node["y"]!.GetValue<double>();
                var name = node?["name"]?.GetValue<string>() ?? $"POI {i + 1}";
                var rot = node?["rot"]?.GetValue<double>() ?? 0;
                var poiStatus = node?["status"]?.GetValue<string>() ?? "unknown";
                _dots.Add(new PoiDot(node!, name, x, y, rot, poiStatus, angle, dist));
                i++;
            }
        }
        Redraw();
        _status.Text = _dots.Count == 0
            ? Path.GetFileName(_path) + " — no extra POI on the active site."
            : Path.GetFileName(_path) + $" — {_dots.Count} marker(s)";
    }

    JsonObject? ActiveSite()
    {
        if (_root?["guardianSites"] is not JsonObject sites)
            return null;
        var active = _root["activeGuardianSite"]?.GetValue<string>();
        if (!string.IsNullOrEmpty(active) && sites[active] is JsonObject named)
            return named;
        foreach (var pair in sites)
        {
            if (pair.Value is JsonObject site)
                return site;
        }
        return null;
    }

    void WritePolar(PoiDot dot)
    {
        var dx = dot.X - 320.0;
        var dy = 180.0 - dot.Y;
        dot.Dist = Math.Sqrt((dx * dx) + (dy * dy));
        var angle = Math.Atan2(dx, dy) * 180.0 / Math.PI;
        if (angle < 0)
            angle += 360.0;
        dot.Angle = angle;
        dot.Node["angle"] = dot.Angle;
        dot.Node["dist"] = dot.Dist;
    }

    void Redraw()
    {
        _canvas.Children.Clear();
        if (!string.IsNullOrWhiteSpace(_backgroundPath) && File.Exists(_backgroundPath))
        {
            var image = new Image
            {
                Source = new Bitmap(_backgroundPath),
                Width = 640,
                Height = 360,
                Stretch = Stretch.Uniform,
                Opacity = 0.45,
            };
            Canvas.SetLeft(image, 0);
            Canvas.SetTop(image, 0);
            _canvas.Children.Add(image);
        }
        foreach (var dot in _dots)
        {
            var mark = new Border
            {
                Width = 18,
                Height = 18,
                Background = new SolidColorBrush(Color.Parse("#d4782a")),
                BorderBrush = new SolidColorBrush(Color.Parse("#f2e6c9")),
                BorderThickness = new Thickness(1),
                Tag = dot,
            };
            Canvas.SetLeft(mark, dot.X);
            Canvas.SetTop(mark, dot.Y);
            _canvas.Children.Add(mark);
            var label = new TextBlock
            {
                Text = dot.Name,
                Foreground = new SolidColorBrush(Color.Parse("#f2e6c9")),
                FontSize = 12,
            };
            Canvas.SetLeft(label, dot.X + 22);
            Canvas.SetTop(label, dot.Y);
            _canvas.Children.Add(label);
        }
    }

    void OnPressed(object? sender, PointerPressedEventArgs e)
    {
        var point = e.GetPosition(_canvas);
        _drag = _dots.FirstOrDefault(d => Math.Abs(d.X + 9 - point.X) < 16 && Math.Abs(d.Y + 9 - point.Y) < 16);
        if (_drag != null)
        {
            _grab = new Point(point.X - _drag.X, point.Y - _drag.Y);
            Select(_drag);
        }
    }

    void OnMoved(object? sender, PointerEventArgs e)
    {
        if (_drag == null)
            return;
        var point = e.GetPosition(_canvas);
        _drag.X = Math.Max(0, point.X - _grab.X);
        _drag.Y = Math.Max(0, point.Y - _grab.Y);
        WritePolar(_drag);
        _angle.Text = _drag.Angle.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture);
        _dist.Text = _drag.Dist.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture);
        Redraw();
    }

    void AddPoi()
    {
        if (_root is not JsonObject root)
            return;
        var survey = ActiveSite();
        if (survey == null)
        {
            var sites = root["guardianSites"] as JsonObject ?? new JsonObject();
            survey = new JsonObject();
            sites["default"] = survey;
            root["guardianSites"] = sites;
            root["activeGuardianSite"] = "default";
        }
        var poi = survey["extra_poi"] as JsonArray ?? new JsonArray();
        var name = "POI " + (poi.Count + 1);
        var node = new JsonObject
        {
            ["name"] = name,
            ["type"] = "unknown",
            ["angle"] = 0,
            ["dist"] = 40,
            ["rot"] = 0,
            ["status"] = "unknown",
        };
        poi.Add(node);
        survey["extra_poi"] = poi;
        var dot = new PoiDot(node, name, 320, 140, 0, "unknown", 0, 40);
        _dots.Add(dot);
        Redraw();
        Select(dot);
        _status.Text = "Added " + name + ". Save writes the commander file.";
    }

    void RemovePoi()
    {
        if (_current == null || ActiveSite() is not JsonObject survey)
            return;
        if (survey["extra_poi"] is JsonArray poi)
            poi.Remove(_current.Node);
        _dots.Remove(_current);
        _current = null;
        _selected.Text = "No POI selected.";
        Redraw();
        _status.Text = "Removed the marker. Save writes the commander file.";
    }

    async Task PickBackground()
    {
        var top = TopLevel.GetTopLevel(this);
        if (top == null)
            return;
        var files = await top.StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = "Site background image",
            AllowMultiple = false,
            FileTypeFilter = new[]
            {
                new FilePickerFileType("PNG") { Patterns = new[] { "*.png" } },
            },
        });
        var path = files.Count > 0 ? files[0].TryGetLocalPath() : null;
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            _status.Text = "Background image was not found. Windows looks for images/<site>-background.png.";
            return;
        }
        _backgroundPath = path;
        Redraw();
        _status.Text = "Background " + Path.GetFileName(path);
    }

    void Save()
    {
        if (_path == null || _root == null)
            return;
        File.WriteAllText(_path, _root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
        _status.Text = "Saved " + _path;
    }

    void Select(PoiDot dot)
    {
        _current = dot;
        _selected.Text = dot.Name;
        _heading.Text = dot.Rot.ToString(System.Globalization.CultureInfo.InvariantCulture);
        _angle.Text = dot.Angle.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture);
        _dist.Text = dot.Dist.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture);
        _poiStatus.SelectedItem = StatusChoices.Contains(dot.Status) ? dot.Status : "unknown";
    }

    void ApplyFields()
    {
        if (_current == null)
            return;
        var rot = _current.Rot;
        if (double.TryParse(_heading.Text, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var parsed))
        {
            rot = parsed;
            _current.Rot = rot;
            _current.Node["rot"] = rot;
        }
        var status = _poiStatus.SelectedItem as string ?? "unknown";
        _current.Status = status;
        _current.Node["status"] = status;
        if (double.TryParse(_angle.Text, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var angle))
        {
            _current.Angle = angle;
            _current.Node["angle"] = angle;
        }
        if (double.TryParse(_dist.Text, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var dist))
        {
            _current.Dist = dist;
            _current.Node["dist"] = dist;
        }
        if (ActiveSite() is JsonObject survey)
        {
            var headings = survey["relic_headings"] as JsonObject ?? new JsonObject();
            headings[_current.Name] = rot;
            survey["relic_headings"] = headings;
        }
        _status.Text = $"Updated {_current.Name}: heading {rot}, status {status}.";
    }

    sealed class PoiDot
    {
        public PoiDot(JsonNode node, string name, double x, double y, double rot, string status, double angle, double dist)
        {
            Node = node;
            Name = name;
            X = x;
            Y = y;
            Rot = rot;
            Status = status;
            Angle = angle;
            Dist = dist;
        }

        public JsonNode Node { get; }
        public string Name { get; }
        public double X { get; set; }
        public double Y { get; set; }
        public double Rot { get; set; }
        public string Status { get; set; }
        public double Angle { get; set; }
        public double Dist { get; set; }
    }
}
