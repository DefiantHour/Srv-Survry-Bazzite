using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace SrvSurveyLinuxUi.Views;

public sealed class NoticeWindow : Window
{
    public NoticeWindow(string title, string message)
    {
        Title = title;
        Width = 420;
        Height = 180;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        CanResize = false;
        ShowInTaskbar = false;

        var ok = new Button { Content = "OK", MinWidth = 80, IsDefault = true, IsCancel = true };
        ok.Click += (_, _) => Close();

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
            Children = { ok },
        };
        DockPanel.SetDock(buttons, Dock.Bottom);

        var panel = new DockPanel { Margin = new Avalonia.Thickness(16) };
        panel.Children.Add(buttons);
        panel.Children.Add(new TextBlock
        {
            Text = message,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Avalonia.Thickness(0, 0, 0, 12),
        });
        Content = panel;
    }
}
