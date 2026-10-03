using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>
/// Linux FormPredictions — journal bio signals + BioCriteria species/variant
/// predictions with codexRef rewards (rules engine, not ML).
/// </summary>
public sealed class PredictionsWindow : Window
{
    readonly string? _journalFolder;
    readonly ListBox _list;
    readonly TextBlock _detail;
    readonly TextBlock _status;

    public PredictionsWindow(string? journalFolder = null)
    {
        _journalFolder = journalFolder;
        Title = "Bio Predictions";
        Width = 720;
        Height = 560;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _list = new ListBox { MinHeight = 300 };
        _list.SelectionChanged += (_, _) => ShowDetail();
        _detail = new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 80,
            Opacity = 0.95,
        };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.8, FontSize = 11 };

        var refresh = new Button { Content = "Refresh", MinWidth = 90 };
        refresh.Click += (_, _) => Reload();
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
                    Children = { refresh, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text =
                                "Body biological signals from the journal, plus "
                                + "BioCriteria species/variant predictions (same "
                                + "SrvSurvey/bio-criteria JSON as Windows BioPredictor) "
                                + "with codexRef reward estimates when Scan props allow.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _list,
                        _detail,
                    },
                },
            },
        };

        Reload();
    }

    void Reload()
    {
        var folder = _journalFolder ?? RuntimeStateSnapshot.TryLoad()?.JournalFolder;
        var bodies = JournalSummaryReader.ReadBioBodies(folder);
        var codex = CodexRefStore.LoadAll();
        var predicted = BioPredictCli.PredictForJournal(folder);
        var rows = new List<object>();

        foreach (var body in bodies)
            rows.Add(new BioRow(body, EnrichGenuses(body, codex)));

        if (predicted.Count > 0)
        {
            rows.Add(new SectionRow($"── Predicted species ({predicted.Count}) ──"));
            foreach (var p in predicted.Take(80))
                rows.Add(new PredictionListRow(p));
        }

        _list.ItemsSource = rows;
        _status.Text = string.IsNullOrWhiteSpace(folder)
            ? "Journal folder unknown (start presenter once)."
            : $"{bodies.Count} body(ies) with bio · {predicted.Count} BioCriteria prediction(s) · {folder}";
        if (rows.Count > 0)
            _list.SelectedIndex = 0;
        else
            _detail.Text =
                "No biological signals or predictions yet. DSS a landable body "
                + "and ensure Detailed Scan fields are in the journal.";
    }

    void ShowDetail()
    {
        if (_list.SelectedItem is BioRow row)
        {
            var lines = new List<string>
            {
                $"{row.Body.BodyName} — {row.Body.BioCount} signal(s), "
                + $"{row.Body.Analyzed} analysed",
            };
            if (row.GenusLines.Count == 0)
                lines.Add("No Genuses list in journal yet (DSS / SAA often fills this).");
            else
                lines.AddRange(row.GenusLines.Select(g => "· " + g));
            _detail.Text = string.Join("\n", lines);
            return;
        }

        if (_list.SelectedItem is PredictionListRow pred)
        {
            var p = pred.Row;
            var lines = new List<string> { p.Name };
            if (p.Reward > 0)
                lines.Add($"Reward: {FormatCredits(p.Reward)}");
            if (!string.IsNullOrWhiteSpace(p.Note))
                lines.Add(p.Note);
            if (!string.IsNullOrWhiteSpace(p.Genus))
                lines.Add($"Genus: {p.Genus}");
            _detail.Text = string.Join("\n", lines);
            return;
        }

        _detail.Text = "";
    }

    static List<string> EnrichGenuses(BioBodySummary body, IReadOnlyList<CodexEntry> codex)
    {
        var lines = new List<string>();
        foreach (var genus in body.Genuses)
        {
            var matches = codex
                .Where(e =>
                    e.EnglishName.Contains(genus, StringComparison.OrdinalIgnoreCase)
                    || (e.SubClass?.Contains(genus, StringComparison.OrdinalIgnoreCase) ?? false)
                    || (e.Name?.Contains(genus, StringComparison.OrdinalIgnoreCase) ?? false))
                .ToList();
            if (matches.Count == 0)
            {
                lines.Add($"{genus} (no codexRef match)");
                continue;
            }

            var min = matches.Min(m => m.Reward);
            var max = matches.Max(m => m.Reward);
            var range = min == max
                ? FormatCredits(max)
                : $"{FormatCredits(min)}–{FormatCredits(max)}";
            lines.Add($"{genus} · {matches.Count} variant(s) · {range}");
        }

        return lines;
    }

    static string FormatCredits(long value) =>
        value.ToString("N0", CultureInfo.InvariantCulture) + " cr";

    sealed class SectionRow
    {
        public SectionRow(string text) => Text = text;
        public string Text { get; }
        public override string ToString() => Text;
    }

    sealed class PredictionListRow
    {
        public PredictionListRow(BioPredictCli.PredictionRow row) => Row = row;
        public BioPredictCli.PredictionRow Row { get; }

        public override string ToString()
        {
            if (Row.Reward > 0)
                return $"? {Row.Name}  ·  {FormatCredits(Row.Reward)}";
            return $"? {Row.Name}";
        }
    }

    sealed class BioRow
    {
        public BioRow(BioBodySummary body, List<string> genusLines)
        {
            Body = body;
            GenusLines = genusLines;
        }

        public BioBodySummary Body { get; }
        public List<string> GenusLines { get; }

        public override string ToString()
        {
            var genus = GenusLines.Count == 0
                ? "genus unknown"
                : string.Join(", ", Body.Genuses.Take(4))
                  + (Body.Genuses.Count > 4 ? "…" : "");
            return $"{Body.BodyName}  ·  {Body.BioCount} bio  ·  {Body.Analyzed} done  ·  {genus}";
        }
    }
}
