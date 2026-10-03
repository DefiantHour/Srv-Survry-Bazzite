using System;
using System.ComponentModel;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Interactivity;
using SrvSurveyLinuxUi.Services;
using SrvSurveyLinuxUi.ViewModels;

namespace SrvSurveyLinuxUi.Views;

public partial class MainWindow : Window
{
    MainViewModel? _vm;

    public MainWindow()
    {
        MainTheme.Apply(Resources, MainThemeKind.Light);
        InitializeComponent();
    }

    protected override void OnDataContextChanged(EventArgs e)
    {
        base.OnDataContextChanged(e);
        if (_vm != null)
            _vm.PropertyChanged -= OnViewModelPropertyChanged;
        _vm = DataContext as MainViewModel;
        if (_vm == null)
            return;
        _vm.PropertyChanged += OnViewModelPropertyChanged;
        MainTheme.Apply(Resources, _vm.ThemeKind);
    }

    void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MainViewModel.ThemeKind) && _vm != null)
            MainTheme.Apply(Resources, _vm.ThemeKind);
    }

    /// <summary>ButtonContextMenuStrip.ShowOnTarget: the menu opens at (0, button.Height).</summary>
    void OnMenuButtonClick(object? sender, RoutedEventArgs e)
    {
        if (sender is not Button button)
            return;
        if (button == BtnColonise && _vm is { BuildProjectsTest: false })
        {
            _vm.EnableColonisationCommand.Execute(null);
            return;
        }
        FlyoutBase.ShowAttachedFlyout(button);
    }

    void OnJourneyMenuOpening(object? sender, EventArgs e) =>
        _vm?.RefreshJourneyMenu();

    protected override void OnClosing(WindowClosingEventArgs e)
    {
        base.OnClosing(e);
        SettingsQuitGate.OnMainWindowClosing(e);
    }

    protected override void OnClosed(EventArgs e)
    {
        base.OnClosed(e);
        SettingsQuitGate.OnMainWindowClosed();
    }
}
