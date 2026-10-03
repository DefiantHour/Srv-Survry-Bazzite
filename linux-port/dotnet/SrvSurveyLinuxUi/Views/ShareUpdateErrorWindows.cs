using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

public sealed class ShareGuardianWindow : Window
{
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public ShareGuardianWindow()
    {
        Title = "Share My Guardian Sites";
        Width = 520;
        Height = 220;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var save = new Button { Content = "Build Share Package", MinWidth = 160 };
        save.Click += async (_, _) => await SaveAsync();
        var discord = new Button { Content = "Discord", MinWidth = 90 };
        discord.Click += (_, _) =>
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "https://discord.gg/9PhBwwDAbV",
                UseShellExecute = true,
            });
        };
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        Content = new StackPanel
        {
            Margin = new Avalonia.Thickness(16),
            Spacing = 12,
            Children =
            {
                new TextBlock
                {
                    Text = "Builds surveys-{commander}-{hash}.zip from guardian sites that have local discoveries, the same package as the Windows share window.",
                    TextWrapping = TextWrapping.Wrap,
                },
                _status,
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { save, discord, close },
                },
            },
        };
    }

    async Task SaveAsync()
    {
        _status.Text = "Building share package…";
        var json = await Task.Run(() => BioPredictCli.RunPython(
            "import json\nfrom share_sites import build_share_package\nprint(json.dumps(build_share_package()))\n",
            20000));
        if (string.IsNullOrWhiteSpace(json) || json[0] != '{')
        {
            _status.Text = "Share package failed.";
            return;
        }
        using var doc = JsonDocument.Parse(json);
        var count = doc.RootElement.TryGetProperty("count", out var c) ? c.GetInt32() : 0;
        var zip = doc.RootElement.TryGetProperty("zip", out var z) ? z.GetString() : "";
        _status.Text = $"{count} site(s) ready: {zip}";
    }
}

public sealed class GithubUpdateWindow : Window
{
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public GithubUpdateWindow()
    {
        Title = "Check for Updates";
        Width = 520;
        Height = 240;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var check = new Button { Content = "Refresh Published Data", MinWidth = 180 };
        check.Click += async (_, _) => await CheckAsync();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        Content = new StackPanel
        {
            Margin = new Avalonia.Thickness(16),
            Spacing = 12,
            Children =
            {
                new TextBlock
                {
                    Text = "Downloads the published SrvSurvey data set (codex, bio criteria, settlements, guardian maps, boxel names, nicknames, GGG) when data.json is newer. The Windows ClickOnce installer is not run.",
                    TextWrapping = TextWrapping.Wrap,
                },
                _status,
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { check, close },
                },
            },
        };
        _status.Text = "Installed file version " + WindowsWireIdentity.ReleaseVersion;
    }

    async Task CheckAsync()
    {
        if (Environment.GetEnvironmentVariable("SRVSURVEY_NET_OFFLINE") is "1" or "true")
        {
            _status.Text = "Offline. Installed " + WindowsWireIdentity.ReleaseVersion;
            return;
        }
        _status.Text = "Refreshing published data…";
        var json = await Task.Run(() => BioPredictCli.RunPython(
            "import json\nfrom pub_data import refresh_published_data\nprint(json.dumps(refresh_published_data()))\n",
            120000));
        if (string.IsNullOrWhiteSpace(json) || json[0] != '{')
        {
            _status.Text = "Published-data refresh failed.";
            return;
        }
        using var doc = JsonDocument.Parse(json);
        var next = doc.RootElement.TryGetProperty("next_build", out var n) && n.ValueKind == JsonValueKind.String
            ? n.GetString()
            : null;
        var actions = doc.RootElement.TryGetProperty("actions", out var a) && a.ValueKind == JsonValueKind.Array
            ? string.Join(", ", a.EnumerateArray().Select(x => x.GetString()))
            : "";
        var reason = doc.RootElement.TryGetProperty("reason", out var r) ? r.GetString() : "";
        _status.Text = string.IsNullOrWhiteSpace(next)
            ? $"Installed {WindowsWireIdentity.ReleaseVersion}. Updated: {(string.IsNullOrWhiteSpace(actions) ? "none" : actions)}. {reason}"
            : $"Installed {WindowsWireIdentity.ReleaseVersion}. Published data offers {next}. The Windows installer is not applied on Bazzite. Updated: {actions}";
    }
}

public sealed class ErrorReportWindow : Window
{
    readonly TextBox _body = new() { AcceptsReturn = true, MinHeight = 180, TextWrapping = TextWrapping.Wrap };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public ErrorReportWindow()
    {
        Title = "Error Report";
        Width = 560;
        Height = 420;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var save = new Button { Content = "Save Locally", MinWidth = 110 };
        save.Click += (_, _) => Save();
        var open = new Button { Content = "Open GitHub Issues", MinWidth = 150 };
        open.Click += (_, _) =>
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "https://github.com/njthomson/SrvSurvey/issues/new",
                UseShellExecute = true,
            });
        };
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
                    Children = { save, open, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "The report stays on this machine. Open GitHub Issues when you want to send it yourself. Do not paste API keys.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _body,
                    },
                },
            },
        };
    }

    void Save()
    {
        var dir = Path.Combine(LinuxPaths.DataDirectory, "error-reports");
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + ".txt");
        File.WriteAllText(path, _body.Text ?? "");
        _status.Text = "Saved " + path;
    }
}
