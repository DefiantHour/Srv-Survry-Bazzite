using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

public sealed class CodexShowWindow : Window
{
    TextBox _filter = null!;
    ListBox _list = null!;
    TextBlock _detail = null!;
    TextBlock _status = null!;
    IReadOnlyList<CodexEntry> _all = Array.Empty<CodexEntry>();

    public CodexShowWindow()
    {
        Title = "Show Codex Species";
        Width = 720;
        Height = 560;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _all = CodexRefStore.LoadAll();
        _filter = new TextBox { PlaceholderText = "Filter by name or category…" };
        _filter.TextChanged += (_, _) => ApplyFilter();
        _list = new ListBox { MinHeight = 260 };
        _list.SelectionChanged += (_, _) => ShowDetail();
        _detail = new TextBlock { TextWrapping = TextWrapping.Wrap, MinHeight = 60 };
        _status = new TextBlock
        {
            Text = FileStatus(),
            FontSize = 11,
            Opacity = 0.75,
            TextWrapping = TextWrapping.Wrap,
        };

        var openImage = new Button { Content = "Open Image URL", MinWidth = 120 };
        openImage.Click += (_, _) =>
        {
            if (_list.SelectedItem is CodexListItem item
                && !string.IsNullOrWhiteSpace(item.Entry.ImageUrl))
            {
                ExternalLauncher.TryOpenUri(item.Entry.ImageUrl);
            }
        };
        var importCanonn = new Button { Content = "Import Canonn Ref", MinWidth = 140 };
        importCanonn.Click += async (_, _) => await ImportCanonnAsync();
        var importJournal = new Button { Content = "Import Journal Codex", MinWidth = 150 };
        importJournal.Click += (_, _) => ImportJournal();

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        buttons.Children.Add(importCanonn);
        buttons.Children.Add(importJournal);
        buttons.Children.Add(openImage);
        buttons.Children.Add(MakeClose());

        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(16),
            Children =
            {
                buttons.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Species from codexRef.json (XDG or bundled). Import Canonn ref or journal CodexEntry events.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _filter,
                        _list,
                        _detail,
                    },
                },
            },
        };

        ApplyFilter();
    }

    async Task ImportCanonnAsync()
    {
        _status.Text = "Downloading Canonn/codexRef…";
        var result = await CodexImportStore.ImportCanonnRefAsync();
        await Dispatcher.UIThread.InvokeAsync(() =>
        {
            _all = CodexRefStore.LoadAll();
            ApplyFilter();
            _status.Text = result.Status;
        });
    }

    void ImportJournal()
    {
        var result = CodexImportStore.ImportJournalCodexEntries(
            RuntimeStateSnapshot.TryLoad()?.JournalFolder);
        _all = CodexRefStore.LoadAll();
        ApplyFilter();
        _status.Text = result.Status;
    }

    void ApplyFilter()
    {
        var q = (_filter.Text ?? "").Trim();
        IEnumerable<CodexEntry> rows = _all;
        if (!string.IsNullOrEmpty(q))
        {
            rows = rows.Where(e =>
                e.EnglishName.Contains(q, StringComparison.OrdinalIgnoreCase)
                || e.HudCategory.Contains(q, StringComparison.OrdinalIgnoreCase)
                || e.SubCategory.Contains(q, StringComparison.OrdinalIgnoreCase)
                || e.EntryId.Contains(q, StringComparison.OrdinalIgnoreCase));
        }

        var filtered = rows.Take(2000).Select(e => new CodexListItem(e)).ToList();
        _list.ItemsSource = filtered;
        _status.Text = $"{filtered.Count} shown · {FileStatus()}";
    }

    void ShowDetail()
    {
        if (_list.SelectedItem is not CodexListItem item)
        {
            _detail.Text = "";
            return;
        }

        var e = item.Entry;
        _detail.Text =
            $"{e.EnglishName}\n"
            + $"Category: {e.HudCategory} / {e.SubCategory} / {e.SubClass}\n"
            + $"Entry: {e.EntryId} · Reward: {e.Reward.ToString("N0", CultureInfo.InvariantCulture)} cr\n"
            + $"Image: {e.ImageUrl ?? "(none)"}";
    }

    static string FileStatus()
    {
        var path = DataFileLocator.CodexRefPath;
        return System.IO.File.Exists(path)
            ? $"Source: {path}"
            : $"Missing codexRef.json (looked for {path})";
    }

    Button MakeClose()
    {
        var btn = new Button { Content = "Close", MinWidth = 80 };
        btn.Click += (_, _) => Close();
        return btn;
    }

    sealed class CodexListItem
    {
        public CodexListItem(CodexEntry entry) => Entry = entry;
        public CodexEntry Entry { get; }
        public override string ToString() =>
            $"{Entry.EnglishName}  [{Entry.HudCategory}]";
    }
}

public sealed class CodexBingoWindow : Window
{
    TextBox _filter = null!;
    ListBox _list = null!;
    TextBlock _status = null!;
    IReadOnlyList<CodexEntry> _all = Array.Empty<CodexEntry>();
    HashSet<string> _done = new(StringComparer.Ordinal);

    public CodexBingoWindow()
    {
        Title = "Codex Bingo";
        Width = 720;
        Height = 580;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        _all = CodexRefStore.LoadAll();
        _done = CodexRefStore.LoadBingoProgress();
        _filter = new TextBox { PlaceholderText = "Filter…" };
        _filter.TextChanged += (_, _) => Rebuild();
        _list = new ListBox { MinHeight = 340 };
        _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Opacity = 0.85 };

        var toggle = new Button { Content = "Toggle Selected", MinWidth = 120 };
        toggle.Click += (_, _) => ToggleSelected();
        var save = new Button { Content = "Save Progress", MinWidth = 120, IsDefault = true };
        save.Click += (_, _) =>
        {
            CodexRefStore.SaveBingoProgress(_done);
            _status.Text = $"Saved {_done.Count} completions to {DataFileLocator.CodexBingoProgressPath}";
        };
        var importCanonn = new Button { Content = "Import Canonn Ref", MinWidth = 140 };
        importCanonn.Click += async (_, _) => await ImportCanonnAsync();
        var importJournal = new Button { Content = "Import Journal Codex", MinWidth = 150 };
        importJournal.Click += (_, _) => ImportJournal();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
            Children = { importCanonn, importJournal, toggle, save, close },
        };

        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(16),
            Children =
            {
                buttons.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Bingo from codexRef.json. Import Canonn ref and/or journal CodexEntry events into XDG progress.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _filter,
                        _list,
                    },
                },
            },
        };

        Rebuild();
    }

    async Task ImportCanonnAsync()
    {
        _status.Text = "Downloading Canonn/codexRef…";
        var result = await CodexImportStore.ImportCanonnRefAsync();
        await Dispatcher.UIThread.InvokeAsync(() =>
        {
            _all = CodexRefStore.LoadAll();
            Rebuild();
            _status.Text = result.Status;
        });
    }

    void ImportJournal()
    {
        var result = CodexImportStore.ImportJournalCodexEntries(
            RuntimeStateSnapshot.TryLoad()?.JournalFolder);
        _done = CodexRefStore.LoadBingoProgress();
        _all = CodexRefStore.LoadAll();
        Rebuild();
        _status.Text = result.Status;
    }

    void Rebuild()
    {
        var q = (_filter.Text ?? "").Trim();
        IEnumerable<CodexEntry> rows = _all;
        if (!string.IsNullOrEmpty(q))
        {
            rows = rows.Where(e =>
                e.EnglishName.Contains(q, StringComparison.OrdinalIgnoreCase)
                || e.HudCategory.Contains(q, StringComparison.OrdinalIgnoreCase));
        }

        _list.ItemsSource = rows
            .Take(3000)
            .Select(e => new BingoItem(e, _done.Contains(e.EntryId)))
            .ToList();
        UpdateStatus();
    }

    void ToggleSelected()
    {
        if (_list.SelectedItem is not BingoItem item)
            return;
        if (_done.Contains(item.Entry.EntryId))
            _done.Remove(item.Entry.EntryId);
        else
            _done.Add(item.Entry.EntryId);
        Rebuild();
    }

    void UpdateStatus()
    {
        var total = _all.Count;
        _status.Text = $"{_done.Count} / {total} marked complete · source {DataFileLocator.CodexRefPath}";
    }

    sealed class BingoItem
    {
        public BingoItem(CodexEntry entry, bool done)
        {
            Entry = entry;
            Done = done;
        }

        public CodexEntry Entry { get; }
        public bool Done { get; }
        public override string ToString() =>
            $"{(Done ? "[x]" : "[ ]")} {Entry.EnglishName}  ({Entry.HudCategory})";
    }
}
