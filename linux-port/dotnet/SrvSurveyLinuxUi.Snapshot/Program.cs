using System;
using System.Collections.Generic;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Headless;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using SrvSurveyLinuxUi;
using SrvSurveyLinuxUi.Services;
using SrvSurveyLinuxUi.ViewModels;
using SrvSurveyLinuxUi.Views;

// Renders the main window with Avalonia's own Skia renderer. No display server is touched.
// --screenshot-data fills the boxes with the values from the user's Windows screenshot and
// forces the dark theme it was taken with, for side-by-side comparison only.
// --theme light|dark|black overrides the theme from ~/.config/srvsurvey/config.
// --compare <png> writes <output>-compare.png with the reference on the left.
// --menus opens each big-button menu and writes <output>-menu-<name>.png from its popup.
var screenshotData = false;
var menus = false;
string? theme = null;
string? compare = null;
var positional = new List<string>();
for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--screenshot-data":
            screenshotData = true;
            break;
        case "--menus":
            menus = true;
            break;
        case "--theme" when i + 1 < args.Length:
            theme = args[++i];
            break;
        case "--compare" when i + 1 < args.Length:
            compare = args[++i];
            break;
        default:
            positional.Add(args[i]);
            break;
    }
}
var output = positional.Count > 0 ? positional[0] : "/tmp/srvsurvey-main-window.png";

AppBuilder.Configure<App>()
    .UseSkia()
    .UseHeadless(new AvaloniaHeadlessPlatformOptions { UseHeadlessDrawing = false })
    .SetupWithoutStarting();

var vm = new MainViewModel();
vm.Dispose();
if (screenshotData)
{
    vm.ThemeKind = MainThemeKind.Dark;
    vm.CommanderText = "TheRealMondo";
    vm.ShowNextWindow = true;
    vm.LocationText = "Flyua Eork XF-L d9-10 2";
    vm.CanCopyLocation = true;
    vm.NearBodyText = "LandableBody";
    vm.VehicleText = "Panthermkii";
    vm.ModeText = "Flying";
    vm.GameLive = true;
    vm.HasCommander = true;
    vm.ExplorationValueText = "5.38 M";
    vm.JumpsText = "537";
    vm.DistanceText = "28,383.5 ly";
    vm.BodiesText = "Scanned: 575, DSS: 1, Landed: 0";
    vm.BioRewardsText = "0, organisms: 0";
    vm.CanResetBio = false;
    vm.SystemBioEnabled = false;
    vm.SystemBioSignalsText = "-";
    vm.SystemBioValuesText = "-";
    vm.BodyBioEnabled = false;
    vm.BodyBioSignalsText = "-";
    vm.BodyBioValuesText = "-";
    vm.FirstFootFallEnabled = false;
    vm.CanCodexShow = false;
    vm.CodexText = "?";
}
if (theme != null)
    vm.ThemeKind = Enum.Parse<MainThemeKind>(theme, ignoreCase: true);

var window = new MainWindow { DataContext = vm };
window.Show();
Dispatcher.UIThread.RunJobs();

var frame = window.CaptureRenderedFrame();
if (frame == null)
{
    Console.Error.WriteLine("No frame was rendered.");
    return 1;
}
frame.Save(output, PngBitmapEncoderOptions.Default);
Console.WriteLine(output);

if (menus)
{
    // Headless popups draw in the window overlay layer, so grow the window until the menus fit.
    window.Width = 720;
    window.Height = 1000;
    Dispatcher.UIThread.RunJobs();
    foreach (var name in new[] { "BtnSearch", "BtnGuardian", "BtnTravel", "BtnColonise" })
    {
        var button = window.FindControl<Button>(name)!;
        if (FlyoutBase.GetAttachedFlyout(button) is not MenuFlyout flyout)
            continue;
        if (name == "BtnTravel")
            vm.RefreshJourneyMenu();
        FlyoutBase.ShowAttachedFlyout(button);
        Dispatcher.UIThread.RunJobs();
        var menuPath = System.IO.Path.ChangeExtension(output, null) + "-menu-" + name[3..].ToLowerInvariant() + ".png";
        window.CaptureRenderedFrame()?.Save(menuPath, PngBitmapEncoderOptions.Default);
        Console.WriteLine(menuPath);
        flyout.Hide();
        Dispatcher.UIThread.RunJobs();
    }
}

if (compare != null)
{
    using var reference = new Bitmap(compare);
    const int gap = 8;
    var width = reference.PixelSize.Width + gap + frame.PixelSize.Width;
    var height = Math.Max(reference.PixelSize.Height, frame.PixelSize.Height);
    using var sheet = new RenderTargetBitmap(new PixelSize(width, height));
    using (var ctx = sheet.CreateDrawingContext())
    {
        ctx.FillRectangle(Brushes.White, new Rect(0, 0, width, height));
        ctx.DrawImage(reference, new Rect(0, 0, reference.PixelSize.Width, reference.PixelSize.Height));
        ctx.DrawImage(frame, new Rect(reference.PixelSize.Width + gap, 0, frame.PixelSize.Width, frame.PixelSize.Height));
    }
    var comparePath = System.IO.Path.ChangeExtension(output, null) + "-compare.png";
    sheet.Save(comparePath, PngBitmapEncoderOptions.Default);
    Console.WriteLine(comparePath);
}
return 0;
