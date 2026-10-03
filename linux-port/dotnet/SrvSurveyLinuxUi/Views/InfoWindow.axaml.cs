using Avalonia.Controls;
using Avalonia.Interactivity;

namespace SrvSurveyLinuxUi.Views;

public partial class InfoWindow : Window
{
    public InfoWindow()
    {
        InitializeComponent();
    }

    public InfoWindow(string title, string message) : this()
    {
        Title = title;
        MessageText.Text = message;
    }

    void OnOkClick(object? sender, RoutedEventArgs e) => Close();
}
