using System;
using System.IO;

namespace SrvSurveyLinuxUi.Services;

/// <summary>Resolve bundled JSON (repo or XDG copies) used by Main feature windows.</summary>
public static class DataFileLocator
{
    public static string CodexRefPath =>
        FirstExisting(
            Path.Combine(LinuxPaths.DataDirectory, "codexRef.json"),
            Path.Combine(WorkspaceRoot ?? "", "docs", "codexRef.json"))
        ?? Path.Combine(LinuxPaths.DataDirectory, "codexRef.json");

    public static string AllBeaconsPath =>
        FirstExisting(
            Path.Combine(LinuxPaths.DataDirectory, "allBeacons.json"),
            Path.Combine(WorkspaceRoot ?? "", "SrvSurvey", "allBeacons.json"))
        ?? Path.Combine(LinuxPaths.DataDirectory, "allBeacons.json");

    public static string AllStructuresPath =>
        FirstExisting(
            Path.Combine(LinuxPaths.DataDirectory, "allStructures.json"),
            Path.Combine(WorkspaceRoot ?? "", "SrvSurvey", "allStructures.json"))
        ?? Path.Combine(LinuxPaths.DataDirectory, "allStructures.json");

    public static string GuardianTemplatesPath =>
        FirstExisting(
            Path.Combine(LinuxPaths.DataDirectory, "guardianSiteTemplates.json"),
            Path.Combine(WorkspaceRoot ?? "", "SrvSurvey", "guardianSiteTemplates.json"))
        ?? Path.Combine(LinuxPaths.DataDirectory, "guardianSiteTemplates.json");

    public static string AllRuinsPath =>
        FirstExisting(
            Path.Combine(LinuxPaths.DataDirectory, "allRuins.json"),
            Path.Combine(WorkspaceRoot ?? "", "SrvSurvey", "allRuins.json"))
        ?? Path.Combine(LinuxPaths.DataDirectory, "allRuins.json");

    public static string CmdrDirectory
    {
        get
        {
            var dir = Path.Combine(LinuxPaths.DataDirectory, "cmdr");
            Directory.CreateDirectory(dir);
            return dir;
        }
    }

    public static string JourneyDirectory
    {
        get
        {
            var dir = Path.Combine(LinuxPaths.DataDirectory, "journey");
            Directory.CreateDirectory(dir);
            return dir;
        }
    }

    public static string ProjectNotesPath
    {
        get
        {
            var path = Path.Combine(LinuxPaths.DataDirectory, "project-notes.json");
            return path;
        }
    }

    public static string CodexBingoProgressPath =>
        Path.Combine(LinuxPaths.DataDirectory, "codex-bingo-progress.json");

    public static string SpanshCacheDirectory
    {
        get
        {
            var dir = Path.Combine(LinuxPaths.DataDirectory, "spansh-cache");
            Directory.CreateDirectory(dir);
            return dir;
        }
    }

    /// <summary>Presenter/RavenColonial writes linked FC cargo snapshot here for Avalonia.</summary>
    public static string FcCargoSnapshotPath =>
        Path.Combine(LinuxPaths.DataDirectory, "fc-cargo.json");

    public static string SystemNotesDirectory
    {
        get
        {
            var dir = Path.Combine(LinuxPaths.DataDirectory, "system-notes");
            Directory.CreateDirectory(dir);
            return dir;
        }
    }

    public static string? FindNavRoutePath(string? journalFolder)
    {
        if (!string.IsNullOrWhiteSpace(journalFolder))
        {
            var candidate = Path.Combine(journalFolder, "NavRoute.json");
            if (File.Exists(candidate))
                return candidate;
        }

        var runtime = RuntimeStateSnapshot.TryLoad();
        if (!string.IsNullOrWhiteSpace(runtime?.JournalFolder))
        {
            var candidate = Path.Combine(runtime.JournalFolder, "NavRoute.json");
            if (File.Exists(candidate))
                return candidate;
        }

        return null;
    }

    public static string? WorkspaceRoot
    {
        get
        {
            var port = LinuxPaths.FindLinuxPortRoot();
            if (port == null)
                return null;
            var parent = Directory.GetParent(port);
            return parent?.FullName;
        }
    }

    static string? FirstExisting(params string[] paths)
    {
        foreach (var path in paths)
        {
            if (string.IsNullOrWhiteSpace(path))
                continue;
            try
            {
                if (File.Exists(path))
                    return path;
            }
            catch
            {
                // ignore
            }
        }

        return null;
    }
}
