using System;
using System.IO;
using Avalonia.Controls;
using Avalonia.Input.Platform;
using Avalonia.Layout;
using Avalonia.Media;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>ViewLogs. Linux does not keep the Windows in-memory Game.logs buffer.</summary>
public sealed class LogsWindow : Window
{
    readonly TextBox _logs;

    public LogsWindow()
    {
        Title = "SrvSurvey Logs";
        Width = 720;
        Height = 480;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        _logs = new TextBox
        {
            IsReadOnly = true,
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            FontFamily = new FontFamily("monospace"),
            Text = "The Linux window does not keep the Windows Game.logs buffer."
                + Environment.NewLine
                + "No SrvSurvey log file is written by this process."
                + Environment.NewLine
                + "Data: " + LinuxPaths.DataDirectory
                + Environment.NewLine
                + "Config: " + LinuxPaths.ConfigDirectory,
        };

        var reset = new Button { Content = "Reset", MinWidth = 80 };
        reset.Click += (_, _) => _logs.Text = "";
        var copy = new Button { Content = "Copy", MinWidth = 80 };
        copy.Click += async (_, _) =>
        {
            if (Clipboard != null)
                await Clipboard.SetTextAsync(_logs.Text ?? "");
        };
        var folder = new Button { Content = "Open logs folder", MinWidth = 120 };
        folder.Click += (_, _) => ExternalLauncher.TryOpenFolder(LinuxPaths.DataDirectory);
        var close = new Button { Content = "Close", MinWidth = 80, IsCancel = true };
        close.Click += (_, _) => Close();

        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { reset, copy, folder, close },
                }.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 0),
                _logs,
            },
        };
    }
}
