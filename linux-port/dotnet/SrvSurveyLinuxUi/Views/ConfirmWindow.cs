using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace SrvSurveyLinuxUi.Views;

public sealed class ConfirmWindow : Window
{
    public bool Confirmed { get; private set; }

    public ConfirmWindow(string title, string message)
    {
        Title = title;
        Width = 420;
        Height = 180;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        CanResize = false;

        var yes = new Button { Content = "Yes", MinWidth = 80, IsDefault = true };
        yes.Click += (_, _) =>
        {
            Confirmed = true;
            Close();
        };
        var no = new Button { Content = "No", MinWidth = 80, IsCancel = true };
        no.Click += (_, _) => Close();

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
            Children = { yes, no },
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

    public static async Task<bool> AskAsync(Window? owner, string title, string message)
    {
        var dlg = new ConfirmWindow(title, message);
        if (owner != null)
            await dlg.ShowDialog(owner);
        else
            dlg.Show();
        return dlg.Confirmed;
    }
}
