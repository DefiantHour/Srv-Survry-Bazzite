using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Threading;
using SrvSurveyLinuxUi.ViewModels;
using SrvSurveyLinuxUi.Views;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// Windows FormSettings is ShowDialog on Main. Linux Settings is a separate
/// GTK process, so shutdown must be blocked until that process exits.
/// </summary>
public static class SettingsQuitGate
{
    const string NoticeTitle = "Close Settings First";
    const string NoticeBody =
        "Settings is still open. Close the Settings window before quitting Srv Survey.";

    static bool _shuttingDown;
    static bool _noticeOpen;

    public static void Install(IClassicDesktopStyleApplicationLifetime desktop)
    {
        desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;
        desktop.ShutdownRequested += OnShutdownRequested;
    }

    static void OnShutdownRequested(object? sender, ShutdownRequestedEventArgs e)
    {
        if (!SettingsLauncher.IsSettingsOpen())
            return;
        e.Cancel = true;
        _shuttingDown = false;
        ShowNotice();
        EnsureMainWindowVisible();
    }

    public static void OnMainWindowClosing(WindowClosingEventArgs e)
    {
        if (SettingsLauncher.IsSettingsOpen())
        {
            e.Cancel = true;
            ShowNotice();
            return;
        }

        if (_shuttingDown)
            return;

        e.Cancel = true;
        RequestQuit();
    }

    public static void OnMainWindowClosed()
    {
        if (_shuttingDown)
            return;
        if (SettingsLauncher.IsSettingsOpen())
        {
            Dispatcher.UIThread.Post(() =>
            {
                EnsureMainWindowVisible();
                ShowNotice();
            });
            return;
        }

        RequestQuit();
    }

    public static void RequestQuit()
    {
        if (SettingsLauncher.IsSettingsOpen())
        {
            ShowNotice();
            return;
        }

        _shuttingDown = true;
        SettingsLauncher.StopPresenter();
        if (Application.Current?.ApplicationLifetime is not IClassicDesktopStyleApplicationLifetime desktop)
            return;

        if (!desktop.TryShutdown())
        {
            if (SettingsLauncher.IsSettingsOpen())
            {
                _shuttingDown = false;
                ShowNotice();
                EnsureMainWindowVisible();
                return;
            }

            desktop.Shutdown();
        }
    }

    public static void ShowNotice()
    {
        Dispatcher.UIThread.Post(() =>
        {
            if (WindowHost.MainWindow?.DataContext is MainViewModel vm)
                vm.StatusLineText = NoticeBody;

            if (_noticeOpen)
            {
                EnsureMainWindowVisible();
                return;
            }

            _noticeOpen = true;
            var dlg = new NoticeWindow(NoticeTitle, NoticeBody);
            dlg.Closed += (_, _) => _noticeOpen = false;
            var owner = WindowHost.MainWindow;
            if (owner != null)
                _ = dlg.ShowDialog(owner);
            else
                dlg.Show();
        });
    }

    static void EnsureMainWindowVisible()
    {
        Dispatcher.UIThread.Post(() =>
        {
            if (Application.Current is App app)
                app.EnsureMainWindow();
        });
    }
}
