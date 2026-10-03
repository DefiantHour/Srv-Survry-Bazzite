using System;
using System.Text.RegularExpressions;

namespace SrvSurveyLinuxUi.Services;

/// <summary>Windows ColonyData.publishFC display-name walk (ReceiveText / FSSSignalDiscovered).</summary>
public static class FleetCarrierNames
{
    static readonly Regex Callsign = new(@"\b[A-Z0-9]{3}-[A-Z0-9]{3}\b", RegexOptions.Compiled);

    public static string DisplayNameFor(CommanderRecord rec, string? callsign)
    {
        if (string.IsNullOrWhiteSpace(callsign))
            return "";
        return rec.FcDisplayNames.TryGetValue(callsign, out var display)
            ? StripPipe(display)
            : "";
    }

    public static bool LearnFromReceiveText(CommanderRecord rec, string? from)
    {
        if (string.IsNullOrWhiteSpace(from))
            return false;
        var callsign = rec.LastStationName;
        if (!string.IsNullOrWhiteSpace(callsign) && from.EndsWith(callsign, StringComparison.OrdinalIgnoreCase))
        {
            Set(rec, callsign, from.Replace(" " + callsign, "", StringComparison.OrdinalIgnoreCase));
            return true;
        }

        var match = Callsign.Match(from);
        if (!match.Success || !from.EndsWith(match.Value, StringComparison.OrdinalIgnoreCase))
            return false;
        Set(rec, match.Value, from.Replace(" " + match.Value, "", StringComparison.OrdinalIgnoreCase));
        return true;
    }

    public static bool LearnFromFss(CommanderRecord rec, string? signalType, string? signalName)
    {
        if (!string.Equals(signalType, "FleetCarrier", StringComparison.OrdinalIgnoreCase)
            || string.IsNullOrWhiteSpace(signalName))
            return false;

        var callsign = rec.LastStationName;
        if (!string.IsNullOrWhiteSpace(callsign) && signalName.EndsWith(callsign, StringComparison.OrdinalIgnoreCase))
        {
            Set(rec, callsign, signalName.Replace(" " + callsign, "", StringComparison.OrdinalIgnoreCase));
            return true;
        }

        var match = Callsign.Match(signalName);
        if (!match.Success)
            return false;
        Set(rec, match.Value, signalName.Replace(" " + match.Value, "", StringComparison.OrdinalIgnoreCase));
        return true;
    }

    static void Set(CommanderRecord rec, string callsign, string display)
    {
        rec.FcDisplayNames[callsign] = StripPipe(display.Trim());
    }

    static string StripPipe(string display) =>
        display.EndsWith(" |", StringComparison.Ordinal) ? display[..^2].Trim() : display;
}
