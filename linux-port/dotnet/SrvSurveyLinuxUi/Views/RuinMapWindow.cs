using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>Pan and filter the bundled guardian ruins catalogue on a star-position map.</summary>
public sealed class RuinMapWindow : Window
{
    readonly Canvas _canvas = new() { Background = new SolidColorBrush(Color.Parse("#10120e")), MinHeight = 460 };
    readonly TextBox _filter = new() { PlaceholderText = "Filter system, body, or site type" };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };
    readonly List<Ruin> _all = new();
    double _panX;
    double _panY = 40;
    Point? _last;

    public RuinMapWindow()
    {
        Title = "Guardian Ruin Map";
        Width = 860;
        Height = 640;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        _filter.TextChanged += (_, _) => Redraw();

        Content = new DockPanel
        {
            Margin = new Thickness(12),
            Children =
            {
                close.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 0),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 0),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Drag to pan. Each mark is a ruin from allRuins.json.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _filter,
                        _canvas,
                    },
                },
            },
        };

        _canvas.PointerPressed += (_, e) => _last = e.GetPosition(_canvas);
        _canvas.PointerReleased += (_, _) => _last = null;
        _canvas.PointerMoved += OnPan;
        Load();
    }

    void Load()
    {
        var path = DataFileLocator.AllRuinsPath;
        if (!File.Exists(path))
        {
            _status.Text = "allRuins.json not found.";
            return;
        }
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        foreach (var el in doc.RootElement.EnumerateArray())
        {
            if (!el.TryGetProperty("starPos", out var pos) || pos.GetArrayLength() < 3)
                continue;
            _all.Add(new Ruin(
                el.GetProperty("systemName").GetString() ?? "",
                el.TryGetProperty("bodyName", out var body) ? body.GetString() ?? "" : "",
                el.TryGetProperty("siteType", out var kind) ? kind.GetString() ?? "" : "",
                pos[0].GetDouble(),
                pos[2].GetDouble()));
        }
        _status.Text = $"{_all.Count} ruins";
        Redraw();
    }

    void OnPan(object? sender, PointerEventArgs e)
    {
        if (_last == null || !e.GetCurrentPoint(_canvas).Properties.IsLeftButtonPressed)
            return;
        var now = e.GetPosition(_canvas);
        _panX += now.X - _last.Value.X;
        _panY += now.Y - _last.Value.Y;
        _last = now;
        Redraw();
    }

    void Redraw()
    {
        _canvas.Children.Clear();
        var needle = (_filter.Text ?? "").Trim();
        var shown = 0;
        foreach (var ruin in _all)
        {
            if (needle.Length > 0
                && !ruin.System.Contains(needle, StringComparison.OrdinalIgnoreCase)
                && !ruin.Body.Contains(needle, StringComparison.OrdinalIgnoreCase)
                && !ruin.Kind.Contains(needle, StringComparison.OrdinalIgnoreCase))
                continue;
            if (shown++ > 800)
                break;
            var mark = new Border
            {
                Width = 6,
                Height = 6,
                Background = new SolidColorBrush(Color.Parse("#3ec6c6")),
            };
            ToolTip.SetTip(mark, $"{ruin.System} {ruin.Body} ({ruin.Kind})");
            Canvas.SetLeft(mark, ruin.X * 0.35 + _panX + 200);
            Canvas.SetTop(mark, ruin.Z * 0.35 + _panY + 200);
            _canvas.Children.Add(mark);
        }
        _status.Text = $"{shown} shown of {_all.Count}";
    }

    sealed record Ruin(string System, string Body, string Kind, double X, double Z);
}
