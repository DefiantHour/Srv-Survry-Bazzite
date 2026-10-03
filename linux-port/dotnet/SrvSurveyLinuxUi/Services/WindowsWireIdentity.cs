using System;
using System.IO;
using System.Text.RegularExpressions;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// Windows Program.userAgent: SrvSurvey-{FileVersion} from SrvSurvey.csproj.
/// </summary>
public static class WindowsWireIdentity
{
    const string FallbackVersion = "2.0.95.0";

    public static string ReleaseVersion { get; } = ReadFileVersion();

    public static string UserAgent => "SrvSurvey-" + ReleaseVersion;

    static string ReadFileVersion()
    {
        foreach (var path in CandidateCsprojPaths())
        {
            try
            {
                if (!File.Exists(path))
                    continue;
                var text = File.ReadAllText(path);
                var match = Regex.Match(text, @"<FileVersion>\s*([^<]+?)\s*</FileVersion>");
                if (match.Success)
                {
                    var version = match.Groups[1].Value.Trim();
                    if (version.Length > 0)
                        return version;
                }
            }
            catch
            {
                // fall through
            }
        }

        return FallbackVersion;
    }

    static string[] CandidateCsprojPaths()
    {
        var root = LinuxPaths.FindLinuxPortRoot();
        var repo = string.IsNullOrWhiteSpace(root) ? null : Directory.GetParent(root)?.FullName;
        return new[]
        {
            repo == null ? "" : Path.Combine(repo, "SrvSurvey", "SrvSurvey.csproj"),
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "SrvSurvey", "SrvSurvey.csproj"),
        };
    }
}
