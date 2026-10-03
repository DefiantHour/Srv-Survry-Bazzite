using System;
using System.Diagnostics;
using System.IO;

namespace SrvSurveyLinuxUi.Services;

/// <summary>Open URLs and folders via xdg-open (Linux desktop).</summary>
public static class ExternalLauncher
{
    public static string? LastError { get; private set; }

    public static bool TryOpenUri(string uri)
    {
        LastError = null;
        if (string.IsNullOrWhiteSpace(uri))
        {
            LastError = "No URL provided";
            return false;
        }

        return TryStartXdgOpen(uri.Trim());
    }

    public static bool TryOpenFolder(string path)
    {
        LastError = null;
        if (string.IsNullOrWhiteSpace(path))
        {
            LastError = "No folder path provided";
            return false;
        }

        try
        {
            Directory.CreateDirectory(path);
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            return false;
        }

        if (!Directory.Exists(path))
        {
            LastError = $"Folder not found: {path}";
            return false;
        }

        return TryStartXdgOpen(path);
    }

    static bool TryStartXdgOpen(string target)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "xdg-open",
                ArgumentList = { target },
                UseShellExecute = false,
            };
            Process.Start(psi);
            return true;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            return false;
        }
    }
}
