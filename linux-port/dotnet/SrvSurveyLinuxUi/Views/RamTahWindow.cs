using System;
using System.Collections.Generic;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

public sealed class RamTahWindow : Window
{
    readonly ComboBox _cmdrCombo;
    readonly TextBlock _missionStatus;
    readonly WrapPanel _logChecks;
    readonly WrapPanel _ruinChecks;
    readonly TextBlock _status;
    readonly List<CheckBox> _logBoxes = new();
    readonly List<CheckBox> _ruinBoxes = new();
    CmdrDecodeFile _cmdr;
    bool _suppress;

    public RamTahWindow(string? preferredCommander = null)
    {
        Title = "Ram Tah Mission";
        Width = 760;
        Height = 620;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _cmdr = CmdrDecodeStore.GetOrCreateDefault(preferredCommander);
        _cmdrCombo = new ComboBox { MinWidth = 220 };
        _missionStatus = new TextBlock { TextWrapping = TextWrapping.Wrap };
        _logChecks = new WrapPanel { Orientation = Orientation.Horizontal };
        _ruinChecks = new WrapPanel { Orientation = Orientation.Horizontal };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.85 };

        for (var i = 1; i <= 28; i++)
        {
            var box = new CheckBox { Content = $"#{i}", Margin = new Avalonia.Thickness(4) };
            var idx = i;
            box.IsCheckedChanged += (_, _) => OnLogChanged(idx, box.IsChecked == true);
            _logBoxes.Add(box);
            _logChecks.Children.Add(box);
        }

        foreach (var letter in new[] { "B", "C", "H", "L", "T" })
        {
            var max = letter is "B" ? 19 : letter is "C" or "T" ? 20 : 21;
            for (var n = 1; n <= max; n++)
            {
                var key = $"{letter}{n}";
                var box = new CheckBox { Content = key, Margin = new Avalonia.Thickness(4) };
                box.IsCheckedChanged += (_, _) => OnRuinChanged(key, box.IsChecked == true);
                _ruinBoxes.Add(box);
                _ruinChecks.Children.Add(box);
            }
        }

        var save = new Button { Content = "Save", MinWidth = 80, IsDefault = true };
        save.Click += (_, _) =>
        {
            CmdrDecodeStore.Save(_cmdr);
            _status.Text = "Saved " + _cmdr.FilePath;
        };
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();

        _cmdrCombo.SelectionChanged += (_, _) =>
        {
            if (_cmdrCombo.SelectedItem is CmdrItem item)
            {
                _cmdr = item.File;
                ApplyChecks();
            }
        };

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
                    Children = { save, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new ScrollViewer
                {
                    Content = new StackPanel
                    {
                        Spacing = 10,
                        Children =
                        {
                            new TextBlock
                            {
                                Text = "Reads/writes decode sets in ~/.local/share/srvsurvey/cmdr/*.json",
                                TextWrapping = TextWrapping.Wrap,
                            },
                            new StackPanel
                            {
                                Orientation = Orientation.Horizontal,
                                Spacing = 8,
                                Children =
                                {
                                    new TextBlock { Text = "Commander", VerticalAlignment = VerticalAlignment.Center },
                                    _cmdrCombo,
                                },
                            },
                            _missionStatus,
                            new TextBlock { Text = "Decode the Logs (#1–#28)", FontWeight = FontWeight.SemiBold },
                            _logChecks,
                            new TextBlock { Text = "Decode the Ruins (B/C/H/L/T)", FontWeight = FontWeight.SemiBold },
                            _ruinChecks,
                        },
                    },
                },
            },
        };

        ReloadCmdrList(preferredCommander);
        ApplyChecks();
    }

    void ReloadCmdrList(string? preferred)
    {
        var files = CmdrDecodeStore.ListCmdrFiles();
        if (files.Count == 0)
            files = new List<CmdrDecodeFile> { _cmdr };
        _cmdrCombo.ItemsSource = files.Select(f => new CmdrItem(f)).ToList();
        var match = files.FirstOrDefault(f =>
            preferred != null
            && string.Equals(f.Commander, preferred, StringComparison.OrdinalIgnoreCase));
        _cmdrCombo.SelectedIndex = match != null
            ? files.ToList().IndexOf(match)
            : files.ToList().FindIndex(f => f.FilePath == _cmdr.FilePath);
        if (_cmdrCombo.SelectedIndex < 0)
            _cmdrCombo.SelectedIndex = 0;
    }

    void ApplyChecks()
    {
        _suppress = true;
        try
        {
            for (var i = 0; i < _logBoxes.Count; i++)
                _logBoxes[i].IsChecked = _cmdr.DecodeTheLogs.Contains($"#{i + 1}");
            foreach (var box in _ruinBoxes)
            {
                var key = box.Content?.ToString() ?? "";
                box.IsChecked = _cmdr.DecodeTheRuins.Contains(key);
            }

            _missionStatus.Text =
                $"Logs mission: {_cmdr.LogsMissionActive} ({_cmdr.DecodeTheLogs.Count}/28) · "
                + $"Ruins mission: {_cmdr.RuinsMissionActive} ({_cmdr.DecodeTheRuins.Count}) · "
                + _cmdr.FilePath;
            _status.Text = "Loaded " + _cmdr.Commander;
        }
        finally
        {
            _suppress = false;
        }
    }

    void OnLogChanged(int idx, bool isChecked)
    {
        if (_suppress)
            return;
        var key = $"#{idx}";
        if (isChecked)
            _cmdr.DecodeTheLogs.Add(key);
        else
            _cmdr.DecodeTheLogs.Remove(key);
        _missionStatus.Text =
            $"Logs mission: {_cmdr.LogsMissionActive} ({_cmdr.DecodeTheLogs.Count}/28) · "
            + $"Ruins mission: {_cmdr.RuinsMissionActive} ({_cmdr.DecodeTheRuins.Count})";
    }

    void OnRuinChanged(string key, bool isChecked)
    {
        if (_suppress)
            return;
        if (isChecked)
            _cmdr.DecodeTheRuins.Add(key);
        else
            _cmdr.DecodeTheRuins.Remove(key);
        _missionStatus.Text =
            $"Logs mission: {_cmdr.LogsMissionActive} ({_cmdr.DecodeTheLogs.Count}/28) · "
            + $"Ruins mission: {_cmdr.RuinsMissionActive} ({_cmdr.DecodeTheRuins.Count})";
    }

    sealed class CmdrItem
    {
        public CmdrItem(CmdrDecodeFile file) => File = file;
        public CmdrDecodeFile File { get; }
        public override string ToString() => $"{File.Commander} ({File.Fid})";
    }
}
