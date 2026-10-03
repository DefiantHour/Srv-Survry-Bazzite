using System;
using System.Text.Json;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace SrvSurveyLinuxUi.Views;

/// <summary>
/// Spansh body search: atmosphere, volcanism, planet class, landmarks, distance.
/// Filter JSON matches Windows CriteriaBuilder.buildQuery.
/// </summary>
public sealed class NearestBodiesWindow : Window
{
    readonly TextBox _reference;
    readonly TextBox _atmosphere;
    readonly TextBox _volcanism;
    readonly TextBox _planetClass;
    readonly TextBox _landmark;
    readonly TextBox _distance;
    readonly ListBox _results;
    readonly TextBlock _status;
    bool _busy;

    public NearestBodiesWindow(string? referenceSystem = null)
    {
        Title = "Nearest Bodies";
        Width = 720;
        Height = 640;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _reference = new TextBox { Text = referenceSystem ?? "", PlaceholderText = "Reference system" };
        _atmosphere = new TextBox { PlaceholderText = "Thin Carbon dioxide" };
        _volcanism = new TextBox { PlaceholderText = "Water Magma" };
        _planetClass = new TextBox { PlaceholderText = "High metal content world" };
        _landmark = new TextBox { PlaceholderText = "Stratum/Stratum Tectonicas" };
        _distance = new TextBox { Text = "100", PlaceholderText = "Max distance (ly)" };
        _results = new ListBox { MinHeight = 240 };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap };

        var search = new Button { Content = "Search Bodies", MinWidth = 120 };
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
                            Text = "Spansh /api/bodies/search. Atmosphere, volcanism, class, and landmark filters match the Windows query.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        Label("Reference system", _reference),
                        Label("Atmosphere", _atmosphere),
                        Label("Volcanism", _volcanism),
                        Label("Planet class", _planetClass),
                        Label("Landmark type/subtype", _landmark),
                        Label("Distance (ly)", _distance),
                        _results,
                    },
                },
            },
        };
    }

    static StackPanel Label(string caption, TextBox box) =>
        new()
        {
            Spacing = 4,
            Children = { new TextBlock { Text = caption }, box },
        };

    async Task SearchAsync()
    {
        if (_busy)
            return;
        _busy = true;
        try
        {
            var query = BuildQuery();
            var (ok, status, json) = await Services.SpanshClient.SearchBodiesAsync(query);
            _status.Text = status;
            if (!ok || string.IsNullOrWhiteSpace(json))
            {
                _results.ItemsSource = null;
                return;
            }
            _results.ItemsSource = FormatHits(json);
        }
        finally
        {
            _busy = false;
        }
    }

    string BuildQuery()
    {
        var filters = new System.Collections.Generic.Dictionary<string, object>();
        AddValue(filters, "atmosphere", _atmosphere.Text);
        AddValue(filters, "volcanism_type", _volcanism.Text);
        AddValue(filters, "subtype", _planetClass.Text);
        var landmark = (_landmark.Text ?? "").Trim();
        if (landmark.Contains('/'))
        {
            var parts = landmark.Split('/', 2);
            filters["landmarks"] = new[]
            {
                new { type = parts[0].Trim(), subtype = new[] { parts[1].Trim() } },
            };
        }
        else if (landmark.Length > 0)
        {
            filters["landmarks"] = new { value = new[] { landmark } };
        }
        if (double.TryParse(_distance.Text, out var ly) && ly > 0)
            filters["distance"] = new { min = 0, max = ly };

        var query = new
        {
            filters,
            sort = new object[] { new { distance = new { direction = "asc" } } },
            size = 10,
            page = 0,
            reference_system = string.IsNullOrWhiteSpace(_reference.Text) ? null : _reference.Text.Trim(),
        };
        return JsonSerializer.Serialize(query);
    }

    static void AddValue(System.Collections.Generic.Dictionary<string, object> filters, string key, string? raw)
    {
        var text = (raw ?? "").Trim();
        if (text.Length == 0)
            return;
        filters[key] = new { value = new[] { text } };
    }

    static string[] FormatHits(string json)
    {
        using var doc = JsonDocument.Parse(json);
        if (!doc.RootElement.TryGetProperty("results", out var results) || results.ValueKind != JsonValueKind.Array)
            return new[] { "No results array." };
        var lines = new System.Collections.Generic.List<string>();
        foreach (var hit in results.EnumerateArray())
        {
            var system = Str(hit, "system_name") ?? Str(hit, "name") ?? "?";
            var body = Str(hit, "name") ?? Str(hit, "body_name") ?? "";
            var dist = hit.TryGetProperty("distance", out var d) ? d.ToString() : "";
            lines.Add($"{system}  {body}  {dist} ly");
        }
        return lines.Count == 0 ? new[] { "No bodies matched." } : lines.ToArray();
    }

    static string? Str(JsonElement el, string name) =>
        el.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;
}
