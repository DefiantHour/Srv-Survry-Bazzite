using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>FormPostProcess counts. Does not rebuild Windows system JSON.</summary>
public sealed class PostProcessWindow : Window
{
    readonly TextBox _folder = new() { PlaceholderText = "Journal folder" };
    readonly TextBlock _stats = new() { TextWrapping = TextWrapping.Wrap, FontFamily = new FontFamily("monospace") };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public PostProcessWindow(string? journalFolder = null)
    {
        Title = "Post-Process Journals";
        Width = 640;
        Height = 520;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        _folder.Text = journalFolder ?? "";
        var run = new Button { Content = "Count", MinWidth = 80 };
        run.Click += (_, _) => Run();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        Content = Shell(new StackPanel
        {
            Spacing = 8,
            Children =
            {
                new TextBlock
                {
                    Text = "Counts jumps, distance, approaches, analysed organisms, cargo, docks, touchdowns, and deaths since the date in the file names.",
                    TextWrapping = TextWrapping.Wrap,
                },
                _folder,
                _stats,
            },
        }, run, close);
    }

    void Run()
    {
        var folder = (_folder.Text ?? "").Trim();
        if (!Directory.Exists(folder))
        {
            _status.Text = "Journal folder not found.";
            return;
        }
        var jumps = 0;
        double distance = 0;
        var bodies = 0;
        var organisms = 0;
        var bought = 0;
        var sold = 0;
        var collected = 0;
        var docked = 0;
        var touch = 0;
        var died = 0;
        var files = 0;
        foreach (var path in Directory.GetFiles(folder, "Journal.*.log"))
        {
            files++;
            foreach (var line in File.ReadLines(path))
            {
                if (string.IsNullOrWhiteSpace(line))
                    continue;
                try
                {
                    using var doc = JsonDocument.Parse(line);
                    var ev = doc.RootElement.TryGetProperty("event", out var e) ? e.GetString() : null;
                    switch (ev)
                    {
                        case "FSDJump":
                            jumps++;
                            if (doc.RootElement.TryGetProperty("JumpDist", out var dist) && dist.TryGetDouble(out var ly))
                                distance += ly;
                            break;
                        case "ApproachBody":
                            bodies++;
                            break;
                        case "ScanOrganic":
                            if (doc.RootElement.TryGetProperty("ScanType", out var scan) && scan.GetString() == "Analyse")
                                organisms++;
                            break;
                        case "MarketBuy":
                            bought += Count(doc.RootElement);
                            break;
                        case "MarketSell":
                            sold += Count(doc.RootElement);
                            break;
                        case "CollectCargo":
                            collected++;
                            break;
                        case "Docked":
                            docked++;
                            break;
                        case "Touchdown":
                            touch++;
                            break;
                        case "Died":
                            died++;
                            break;
                    }
                }
                catch
                {
                    // skip broken lines
                }
            }
        }
        _stats.Text =
            $"Files {files}\nJumps {jumps}\nDistance {distance.ToString("N1", CultureInfo.InvariantCulture)} ly\n"
            + $"Bodies approached {bodies}\nOrganisms analysed {organisms}\nCargo bought {bought}\n"
            + $"Cargo sold {sold}\nCargo collected {collected}\nDocked {docked}\nTouchdowns {touch}\nDied {died}";
        _status.Text = "Count finished.";
    }

    static int Count(JsonElement el) =>
        el.TryGetProperty("Count", out var c) && c.TryGetInt32(out var n) ? n : 0;

    DockPanel Shell(Control body, params Button[] buttons)
    {
        var bar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        foreach (var button in buttons)
            bar.Children.Add(button);
        return new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                bar.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                body,
            },
        };
    }
}

/// <summary>
/// Backup and restore VisitedStarsCache.dat. The download POST is not performed here;
/// use the Python star_cache module, which refuses the POST when offline.
/// </summary>
public sealed class StarCacheWindow : Window
{
    readonly TextBox _fid = new() { PlaceholderText = "FID (F123…)" };
    readonly TextBox _root = new() { PlaceholderText = "Elite local data folder" };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public StarCacheWindow()
    {
        Title = "Swap Star Cache";
        Width = 640;
        Height = 320;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var backup = new Button { Content = "Backup", MinWidth = 90 };
        backup.Click += (_, _) => Backup();
        var restore = new Button { Content = "Restore", MinWidth = 90 };
        restore.Click += (_, _) => Restore();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        var bar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
            Children = { backup, restore, close },
        };
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                bar.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Copies VisitedStarsCache.dat to backup-VisitedStarsCache.dat under the FID folder. Downloading a replacement from edgalaxy is skipped while offline.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _fid,
                        _root,
                    },
                },
            },
        };
        _status.Text = "Game should be closed before replacing the cache file.";
    }

    (string Original, string Backup) Paths()
    {
        var fid = (_fid.Text ?? "").Trim();
        var number = fid.StartsWith("F", StringComparison.OrdinalIgnoreCase) ? fid[1..] : fid;
        var root = string.IsNullOrWhiteSpace(_root.Text)
            ? Path.Combine(LinuxPaths.DataDirectory, "star-cache")
            : _root.Text.Trim();
        var folder = Path.Combine(root, number);
        return (Path.Combine(folder, "VisitedStarsCache.dat"), Path.Combine(folder, "backup-VisitedStarsCache.dat"));
    }

    void Backup()
    {
        var (original, backup) = Paths();
        if (File.Exists(backup))
        {
            _status.Text = "Backup already exists.";
            return;
        }
        if (!File.Exists(original))
        {
            _status.Text = "Cache file not found: " + original;
            return;
        }
        Directory.CreateDirectory(Path.GetDirectoryName(backup)!);
        File.Copy(original, backup, overwrite: false);
        _status.Text = "Backed up to " + backup;
    }

    void Restore()
    {
        var (original, backup) = Paths();
        if (!File.Exists(backup))
        {
            _status.Text = "No backup to restore.";
            return;
        }
        Directory.CreateDirectory(Path.GetDirectoryName(original)!);
        File.Move(backup, original, overwrite: true);
        _status.Text = "Restored " + original;
    }
}

public sealed class NewCmdrWindow : Window
{
    readonly ListBox _list = new();
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public NewCmdrWindow()
    {
        Title = "Start Another Commander";
        Width = 520;
        Height = 420;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var start = new Button { Content = "Start", MinWidth = 80 };
        start.Click += (_, _) => Start();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        var bar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
            Children = { start, close },
        };
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                bar.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Starts another copy of this Linux client for the selected commander file. It does not attach to a second Windows Elite process.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _list,
                    },
                },
            },
        };
        var files = Directory.Exists(DataFileLocator.CmdrDirectory)
            ? Directory.GetFiles(DataFileLocator.CmdrDirectory, "*.json")
            : Array.Empty<string>();
        _list.ItemsSource = files.Select(Path.GetFileNameWithoutExtension).ToList();
        _list.Tag = files;
        _status.Text = files.Length == 0 ? "No commander JSON yet." : $"{files.Length} commander file(s).";
    }

    void Start()
    {
        if (_list.Tag is not string[] files || _list.SelectedIndex < 0 || _list.SelectedIndex >= files.Length)
        {
            _status.Text = "Select a commander.";
            return;
        }
        var fid = Path.GetFileNameWithoutExtension(files[_list.SelectedIndex]);
        var exe = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(exe))
        {
            _status.Text = "Could not find this program.";
            return;
        }
        Process.Start(new ProcessStartInfo(exe, "--fid " + fid) { UseShellExecute = false });
        _status.Text = "Started another window for " + fid;
    }
}

/// <summary>Commander name strip. Not a Win32-parented floatie.</summary>
public sealed class MultiFloatieWindow : Window
{
    public MultiFloatieWindow(string commander)
    {
        Title = "Commander";
        Width = 280;
        Height = 48;
        CanResize = false;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        WindowDecorations = Avalonia.Controls.WindowDecorations.None;
        Background = new SolidColorBrush(Color.Parse("#c6f25a"));
        Content = new TextBlock
        {
            Text = " ~ " + (string.IsNullOrWhiteSpace(commander) ? "?" : commander) + " ~ ",
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Foreground = Brushes.Black,
            FontWeight = FontWeight.Bold,
        };
    }
}

public sealed class SiteBuilderWindow : Window
{
    readonly TextBox _name = new() { PlaceholderText = "Building name" };
    readonly TextBox _x = new() { PlaceholderText = "x meters" };
    readonly TextBox _y = new() { PlaceholderText = "y meters" };
    readonly TextBox _radius = new() { PlaceholderText = "circle radius" };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public SiteBuilderWindow()
    {
        Title = "Site Builder";
        Width = 560;
        Height = 420;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var add = new Button { Content = "Add Point", MinWidth = 90 };
        add.Click += (_, _) => AddPoint();
        var end = new Button { Content = "End Polygon", MinWidth = 100 };
        end.Click += (_, _) => EndPolygon();
        var circle = new Button { Content = "Add Circle", MinWidth = 100 };
        circle.Click += (_, _) => AddCircle();
        var save = new Button { Content = "Save", MinWidth = 80 };
        save.Click += (_, _) => Save();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        var bar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
            Children = { add, end, circle, save, close },
        };
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                bar.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Records a building footprint in site-local meters. Points are typed; there is no live shield sampler.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _name,
                        _x,
                        _y,
                        _radius,
                    },
                },
            },
        };
        _status.Text = "No open polygon.";
    }

    readonly List<Dictionary<string, double>> _open = new();
    readonly List<List<Dictionary<string, double>>> _polygons = new();
    readonly List<Dictionary<string, double>> _circles = new();

    void AddPoint()
    {
        if (!double.TryParse(_x.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var x)
            || !double.TryParse(_y.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var y))
        {
            _status.Text = "Enter x and y in meters.";
            return;
        }
        _open.Add(new Dictionary<string, double> { ["x"] = x, ["y"] = y });
        _status.Text = $"{_open.Count} point(s) in the open polygon.";
    }

    void EndPolygon()
    {
        if (_open.Count < 2)
        {
            _status.Text = "A polygon needs at least two points.";
            return;
        }
        _polygons.Add(_open.ToList());
        _open.Clear();
        _status.Text = $"{_polygons.Count} polygon(s) closed.";
    }

    void AddCircle()
    {
        if (!double.TryParse(_x.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var x)
            || !double.TryParse(_y.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var y)
            || !double.TryParse(_radius.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var radius))
        {
            _status.Text = "Enter x, y, and radius.";
            return;
        }
        _circles.Add(new Dictionary<string, double> { ["x"] = x, ["y"] = y, ["radius"] = radius });
        _status.Text = $"{_circles.Count} circle(s).";
    }

    void Save()
    {
        var path = Path.Combine(LinuxPaths.DataDirectory, "site-buildings.json");
        var payload = new Dictionary<string, object>
        {
            ["name"] = string.IsNullOrWhiteSpace(_name.Text) ? "Building" : _name.Text.Trim(),
            ["polygons"] = _polygons,
            ["circles"] = _circles,
        };
        Directory.CreateDirectory(LinuxPaths.DataDirectory);
        File.WriteAllText(path, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
        _status.Text = "Saved " + path;
    }
}

public sealed class ShipOffsetsWindow : Window
{
    readonly TextBox _ship = new() { PlaceholderText = "Ship type, e.g. python" };
    readonly TextBox _x = new() { PlaceholderText = "x meters" };
    readonly TextBox _y = new() { PlaceholderText = "y meters" };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public ShipOffsetsWindow()
    {
        Title = "Ship Center Offsets";
        Width = 560;
        Height = 320;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var save = new Button { Content = "Save Override", MinWidth = 120 };
        save.Click += (_, _) => Save();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        var bar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
            Children = { save, close },
        };
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                bar.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Cockpit-to-center offsets live in the Windows ship table. An override is stored under XDG data, not in the main config.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _ship,
                        _x,
                        _y,
                    },
                },
            },
        };
    }

    void Save()
    {
        var ship = (_ship.Text ?? "").Trim().ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(ship)
            || !double.TryParse(_x.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var x)
            || !double.TryParse(_y.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var y))
        {
            _status.Text = "Enter a ship type and two numbers.";
            return;
        }
        var path = Path.Combine(LinuxPaths.DataDirectory, "ship-offsets.json");
        Dictionary<string, double[]> table = new(StringComparer.OrdinalIgnoreCase);
        if (File.Exists(path))
        {
            try
            {
                var existing = JsonSerializer.Deserialize<Dictionary<string, double[]>>(File.ReadAllText(path));
                if (existing != null)
                    table = existing;
            }
            catch
            {
                table = new Dictionary<string, double[]>(StringComparer.OrdinalIgnoreCase);
            }
        }
        table[ship] = new[] { x, y };
        Directory.CreateDirectory(LinuxPaths.DataDirectory);
        File.WriteAllText(path, JsonSerializer.Serialize(table, new JsonSerializerOptions { WriteIndented = true }));
        _status.Text = "Saved override for " + ship;
    }
}
