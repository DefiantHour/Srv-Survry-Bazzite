using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

/// <summary>
/// Invoke Python <c>bio_predict</c> BioCriteria engine for Avalonia Predictions.
/// </summary>
public static class BioPredictCli
{
    public sealed class PredictionRow
    {
        public string Name { get; init; } = "";
        public string Genus { get; init; } = "";
        public string Species { get; init; } = "";
        public string Variant { get; init; } = "";
        public long Reward { get; init; }
        public string Note { get; init; } = "";
    }

    public static IReadOnlyList<PredictionRow> PredictForJournal(string? journalFolder)
    {
        if (string.IsNullOrWhiteSpace(journalFolder))
            return Array.Empty<PredictionRow>();

        var json = RunPython(
            "from bio_predict import predictions_json_for_journal\n"
            + $"print(predictions_json_for_journal({JsonSerializer.Serialize(journalFolder)}))\n");
        if (string.IsNullOrWhiteSpace(json) || json[0] != '[')
            return Array.Empty<PredictionRow>();

        try
        {
            using var doc = JsonDocument.Parse(json);
            var list = new List<PredictionRow>();
            foreach (var el in doc.RootElement.EnumerateArray())
            {
                list.Add(new PredictionRow
                {
                    Name = GetString(el, "name") ?? "",
                    Genus = GetString(el, "genus") ?? "",
                    Species = GetString(el, "species") ?? "",
                    Variant = GetString(el, "variant") ?? "",
                    Reward = GetLong(el, "reward"),
                    Note = GetString(el, "note") ?? "",
                });
            }

            return list;
        }
        catch
        {
            return Array.Empty<PredictionRow>();
        }
    }

    public static string RunPython(string script, int timeoutMs = 20000)
    {
        try
        {
            return RunPythonText(script, timeoutMs);
        }
        catch
        {
            return "[]";
        }
    }

    public static string RunPythonText(string script, int timeoutMs = 20000)
    {
        var runtime = LinuxPaths.FindLinuxPortRoot();
        var runtimeDir = runtime != null
            ? Path.Combine(runtime, "runtime")
            : Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "runtime");
        if (!Directory.Exists(runtimeDir))
            throw new DirectoryNotFoundException(runtimeDir);

        var psi = new ProcessStartInfo
        {
            FileName = "python3",
            WorkingDirectory = runtimeDir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.ArgumentList.Add("-c");
        psi.ArgumentList.Add(script);
        psi.Environment["PYTHONPATH"] = runtimeDir;
        using var proc = Process.Start(psi) ?? throw new InvalidOperationException("python3 did not start");
        var stdoutTask = proc.StandardOutput.ReadToEndAsync();
        var stderrTask = proc.StandardError.ReadToEndAsync();
        if (!proc.WaitForExit(timeoutMs))
        {
            try
            {
                proc.Kill(entireProcessTree: true);
            }
            catch
            {
                // the caller still gets the timeout
            }
            throw new TimeoutException("python3 timed out");
        }
        var stdout = stdoutTask.GetAwaiter().GetResult();
        var stderr = stderrTask.GetAwaiter().GetResult();
        if (proc.ExitCode != 0)
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(stderr) ? stdout : stderr.Trim());
        return (stdout ?? "").Trim();
    }

    static string? GetString(JsonElement el, string name) =>
        el.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String
            ? p.GetString()
            : null;

    static long GetLong(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p))
            return 0;
        if (p.ValueKind == JsonValueKind.Number && p.TryGetInt64(out var n))
            return n;
        return 0;
    }
}
