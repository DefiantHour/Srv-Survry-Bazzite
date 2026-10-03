using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Layout;

namespace SrvSurveyLinuxUi.Views;

/// <summary>Canonn /query/nearest/codex — Windows FormNearestSystems.</summary>
public sealed class NearestSystemsWindow : Window
{
    readonly TextBox _x = new() { Text = "0" };
    readonly TextBox _y = new() { Text = "0" };
    readonly TextBox _z = new() { Text = "0" };
    readonly TextBox _species = new() { PlaceholderText = "Species, e.g. Stratum Tectonicas" };
    readonly ListBox _results = new() { MinHeight = 220 };
    readonly TextBlock _status = new() { TextWrapping = Avalonia.Media.TextWrapping.Wrap };
    bool _busy;

    public NearestSystemsWindow()
    {
        Title = "Nearest Systems";
        Width = 640;
        Height = 520;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var search = new Button { Content = "Search", MinWidth = 90 };
        search.Click += async (_, _) => await SearchAsync();
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
                    Children = { search, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Canonn nearest codex systems from a star position. Top five, with distance.",
                            TextWrapping = Avalonia.Media.TextWrapping.Wrap,
                        },
                        new TextBlock { Text = "X  Y  Z" },
                        new StackPanel
                        {
                            Orientation = Orientation.Horizontal,
                            Spacing = 8,
                            Children = { _x, _y, _z },
                        },
                        _species,
                        _results,
                    },
                },
            },
        };
    }

    async Task SearchAsync()
    {
        if (_busy)
            return;
        if (Environment.GetEnvironmentVariable("SRVSURVEY_NET_OFFLINE") is "1" or "true"
            || Environment.GetEnvironmentVariable("SRVSURVEY_CANONN_OFFLINE") is "1" or "true")
        {
            _status.Text = "Canonn offline — nearest-system search skipped.";
            return;
        }
        var name = (_species.Text ?? "").Trim();
        if (name.Length == 0 || !double.TryParse(_x.Text, out var x)
            || !double.TryParse(_y.Text, out var y) || !double.TryParse(_z.Text, out var z))
        {
            _status.Text = "Enter X, Y, Z and a species name.";
            return;
        }
        _busy = true;
        try
        {
            var url =
                "https://us-central1-canonn-api-236217.cloudfunctions.net/query/nearest/codex"
                + $"?x={x.ToString(System.Globalization.CultureInfo.InvariantCulture)}"
                + $"&y={y.ToString(System.Globalization.CultureInfo.InvariantCulture)}"
                + $"&z={z.ToString(System.Globalization.CultureInfo.InvariantCulture)}"
                + $"&name={Uri.EscapeDataString(name)}&limit=5";
            using var http = new HttpClient();
            http.DefaultRequestHeaders.UserAgent.ParseAdd(Services.WindowsWireIdentity.UserAgent);
            var json = await http.GetStringAsync(url);
            _results.ItemsSource = Format(json);
            _status.Text = "Canonn nearest systems loaded.";
        }
        catch (Exception ex)
        {
            _status.Text = "Nearest-system search failed: " + ex.Message;
        }
        finally
        {
            _busy = false;
        }
    }

    static List<string> Format(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var lines = new List<string>();
        if (!doc.RootElement.TryGetProperty("nearest", out var nearest) || nearest.ValueKind != JsonValueKind.Array)
            return new List<string> { "No nearest list." };
        foreach (var entry in nearest.EnumerateArray())
        {
            var system = entry.TryGetProperty("system", out var s) ? s.GetString() : "?";
            var dist = entry.TryGetProperty("distance", out var d) ? d.GetDouble().ToString("0.0") : "";
            lines.Add($"{system}  {dist} ly");
            if (lines.Count >= 5)
                break;
        }
        return lines.Count == 0 ? new List<string> { "No systems matched." } : lines;
    }
}
