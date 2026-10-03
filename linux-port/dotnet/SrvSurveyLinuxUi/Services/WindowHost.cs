using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;

namespace SrvSurveyLinuxUi.Services;

public static class WindowHost
{
    public static Window? MainWindow =>
        Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop
            ? desktop.MainWindow
            : null;

    public static void Show(Window window)
    {
        var owner = MainWindow;
        if (owner != null)
            window.Show(owner);
        else
            window.Show();
    }

    public static async System.Threading.Tasks.Task ShowDialogAsync(Window window)
    {
        var owner = MainWindow;
        if (owner != null)
            await window.ShowDialog(owner);
        else
            window.Show();
    }
}
