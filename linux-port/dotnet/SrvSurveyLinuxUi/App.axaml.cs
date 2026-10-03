using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using SrvSurveyLinuxUi.Services;
using SrvSurveyLinuxUi.ViewModels;
using SrvSurveyLinuxUi.Views;

namespace SrvSurveyLinuxUi;

public partial class App : Application
{
    MainViewModel? _vm;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            _vm = new MainViewModel();
            desktop.MainWindow = new MainWindow
            {
                DataContext = _vm,
            };
            SettingsQuitGate.Install(desktop);
            _vm.EnsurePresenterStarted();
            desktop.Exit += (_, _) => _vm.Dispose();
        }

        base.OnFrameworkInitializationCompleted();
    }

    public void EnsureMainWindow()
    {
        if (ApplicationLifetime is not IClassicDesktopStyleApplicationLifetime desktop)
            return;
        if (_vm == null)
            return;
        if (desktop.MainWindow is { IsVisible: true })
        {
            desktop.MainWindow.Activate();
            return;
        }

        desktop.MainWindow = new MainWindow
        {
            DataContext = _vm,
        };
        desktop.MainWindow.Show();
    }
}
