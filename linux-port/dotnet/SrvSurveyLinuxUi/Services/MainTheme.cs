using System.Collections.Generic;
using Avalonia.Controls;
using Avalonia.Media;

namespace SrvSurveyLinuxUi.Services;

public enum MainThemeKind
{
    Light,
    Dark,
    Black,
}

/// <summary>
/// Main window palette from Windows Util.applyTheme and BaseForm.applyThemeWithCustomControls.
/// Light and dark use the Windows 10 default SystemColors; black uses GameColors from theme.json.
/// </summary>
public static class MainTheme
{
    static class Sys
    {
        public static readonly Color AppWorkspace = Color.FromRgb(0xAB, 0xAB, 0xAB);
        public static readonly Color Control = Color.FromRgb(0xF0, 0xF0, 0xF0);
        public static readonly Color ControlDark = Color.FromRgb(0xA0, 0xA0, 0xA0);
        public static readonly Color ControlLight = Color.FromRgb(0xE3, 0xE3, 0xE3);
        public static readonly Color ControlLightLight = Color.FromRgb(0xFF, 0xFF, 0xFF);
        public static readonly Color ControlText = Color.FromRgb(0x00, 0x00, 0x00);
        public static readonly Color ScrollBar = Color.FromRgb(0xC8, 0xC8, 0xC8);
        public static readonly Color InactiveCaption = Color.FromRgb(0xBF, 0xCD, 0xDB);
        public static readonly Color ActiveCaption = Color.FromRgb(0x99, 0xB4, 0xD1);
        public static readonly Color GrayText = Color.FromRgb(0x6D, 0x6D, 0x6D);
        public static readonly Color WindowFrame = Color.FromRgb(0x64, 0x64, 0x64);
        public static readonly Color Highlight = Color.FromRgb(0x00, 0x78, 0xD7);
        public static readonly Color HighlightText = Color.FromRgb(0xFF, 0xFF, 0xFF);
        public static readonly Color LinkBlue = Color.FromRgb(0x00, 0x00, 0xFF);
    }

    static class Game
    {
        public static readonly Color Orange = Color.FromRgb(255, 111, 0);
        public static readonly Color OrangeDark = Color.FromRgb(95, 48, 3);
        public static readonly Color OrangeDarker = Color.FromArgb(100, 95, 48, 3);
        public static readonly Color MenuGold = Color.FromArgb(235, 235, 145, 0);
        public static readonly Color Grey = Color.FromRgb(100, 100, 100);
        public static readonly Color Black = Color.FromRgb(0, 0, 0);
        public static readonly Color CyanDark = Color.FromRgb(0, 139, 139);
    }

    public static MainThemeKind Select(bool darkTheme, bool themeMainBlack) =>
        themeMainBlack ? MainThemeKind.Black : darkTheme ? MainThemeKind.Dark : MainThemeKind.Light;

    public static IReadOnlyDictionary<string, Color> Palette(MainThemeKind kind)
    {
        var black = kind == MainThemeKind.Black;
        var dark = kind == MainThemeKind.Dark;
        var formBack = black ? Game.Black : dark ? Sys.AppWorkspace : Sys.Control;
        var fore = black ? Game.Orange : Sys.ControlText;
        var buttonBack = black ? Game.OrangeDarker : dark ? Sys.ControlDark : Sys.ControlLight;

        return new Dictionary<string, Color>
        {
            ["FormBack"] = formBack,
            ["FormFore"] = fore,
            ["GrayText"] = Sys.GrayText,
            // ControlPaint.DrawStringDisabled: LightLight(back) offset by one pixel under Dark(back).
            ["LabelDisabledFore"] = black ? Game.Grey : dark ? Color.FromRgb(0x39, 0x39, 0x39) : Sys.ControlDark,
            ["LabelDisabledShadow"] = black ? Colors.Transparent : dark ? Color.FromRgb(0xD5, 0xD5, 0xD5) : Sys.ControlLightLight,
            ["BoxBack"] = formBack,
            ["BoxFore"] = fore,
            ["BoxBorder"] = Sys.WindowFrame,
            ["GroupLine"] = black ? Game.OrangeDark : dark ? Sys.ControlLight : Sys.ControlDark,
            ["DrawBack"] = buttonBack,
            ["DrawHover"] = black ? Game.OrangeDark : Sys.InactiveCaption,
            ["DrawPressed"] = black ? Game.Orange : Sys.ActiveCaption,
            ["DrawDisabled"] = black ? Game.Grey : Sys.ScrollBar,
            ["DrawFore"] = fore,
            ["DrawForeHover"] = black ? Game.MenuGold : Sys.ControlText,
            ["DrawForePressed"] = black ? Game.Black : Sys.ControlText,
            ["DrawForeDisabled"] = black ? Game.Black : Sys.GrayText,
            ["FlatBack"] = buttonBack,
            ["FlatFore"] = fore,
            ["FlatHover"] = black ? Game.OrangeDark : Sys.InactiveCaption,
            ["FlatPressed"] = black ? Game.MenuGold : Sys.ActiveCaption,
            ["FlatDisabled"] = Sys.WindowFrame,
            ["CheckLine"] = black ? Game.OrangeDark : Sys.ControlText,
            // ControlPaint.LightLight(LineColor), or Dark(LineColor) when the back color is black.
            ["CheckLineDisabled"] = black ? Color.FromRgb(0x30, 0x18, 0x02) : Color.FromRgb(0x7F, 0x7F, 0x7F),
            ["CheckMark"] = black ? Game.Orange : Sys.ControlText,
            ["CheckBack"] = black ? Game.Black : Sys.ControlLightLight,
            ["LinkFore"] = black ? Game.MenuGold : Sys.LinkBlue,
            ["CopyIconFront"] = black ? Game.MenuGold : Game.Black,
            ["CopyIconBack"] = Game.Grey,
            ["NextWindowBack"] = Game.CyanDark,
            // ContextMenuStrips are not themed by applyTheme and keep the system menu colors.
            ["MenuBack"] = Sys.ControlLight,
            ["MenuFore"] = Sys.ControlText,
            ["MenuHover"] = Sys.Highlight,
            ["MenuHoverFore"] = Sys.HighlightText,
            ["MenuDisabledFore"] = Sys.GrayText,
            ["MenuSeparator"] = Sys.ControlDark,
        };
    }

    public static void Apply(IResourceDictionary resources, MainThemeKind kind)
    {
        foreach (var (key, color) in Palette(kind))
        {
            if (resources.TryGetValue(key, out var existing) && existing is SolidColorBrush brush)
                brush.Color = color;
            else
                resources[key] = new SolidColorBrush(color);
        }
    }
}
