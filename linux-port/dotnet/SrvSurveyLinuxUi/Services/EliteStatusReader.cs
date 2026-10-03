using System;
using System.IO;
using System.Text.Json;

namespace SrvSurveyLinuxUi.Services;

/// <summary>Subset of companion.StatusSnapshot for Main status lines.</summary>
public sealed class EliteStatusSummary
{
    public int Flags { get; init; }
    public int Flags2 { get; init; }
    public string? BodyName { get; init; }
    public int? GuiFocus { get; init; }
    public string? LegalState { get; init; }
    public double? Latitude { get; init; }
    public double? Longitude { get; init; }

    public bool Docked => (Flags & 0x1) != 0;
    public bool Landed => (Flags & 0x2) != 0;
    public bool Supercruise => (Flags & 0x10) != 0;
    public bool InMainShip => (Flags & 0x0100_0000) != 0;
    public bool InFighter => (Flags & 0x0200_0000) != 0;
    public bool InSrv => (Flags & 0x0400_0000) != 0;
    public bool OnFoot => (Flags2 & 0x1) != 0;
    public bool InTaxi => (Flags2 & 0x2) != 0;
    public bool GlideMode => (Flags2 & 0x1000) != 0;
    public bool FsdJumping => (Flags & 0x4000_0000) != 0;

    public string VehicleLabel
    {
        get
        {
            if (OnFoot) return "OnFoot";
            if (InSrv) return "SRV";
            if (InFighter) return "Fighter";
            if (InTaxi) return "Taxi";
            if (InMainShip) return "MainShip";
            return "";
        }
    }

    public string ModeLabel
    {
        get
        {
            if (GuiFocus is 6) return "GalaxyMap";
            if (GuiFocus is 7 or 8) return "SystemMap";
            if (GuiFocus is 9) return "FSS";
            if (GuiFocus is 10) return "SAA";
            if (OnFoot) return "OnFoot";
            if (InSrv) return "SRV";
            if (InFighter) return "Fighter";
            if (Docked) return "Docked";
            if (Landed) return "Landed";
            if (GlideMode) return "GlideMode";
            if (Supercruise) return "SuperCruising";
            if (FsdJumping) return "FSDJumping";
            if (InMainShip) return "Flying";
            return StatusFileExists ? "Unknown" : "Game is not active";
        }
    }

    public bool StatusFileExists { get; init; }

    public string NearBodyLabel
    {
        get
        {
            if (FsdJumping) return "Witch space";
            if (!string.IsNullOrWhiteSpace(BodyName)) return "Near body";
            return "Deep space";
        }
    }
}

public static class EliteStatusReader
{
    public static EliteStatusSummary? TryRead(string journalFolder)
    {
        var path = Path.Combine(journalFolder, "Status.json");
        if (!File.Exists(path))
            return new EliteStatusSummary { StatusFileExists = false };

        try
        {
            var text = File.ReadAllText(path);
            using var doc = JsonDocument.Parse(text);
            var root = doc.RootElement;
            string? body = null;
            if (root.TryGetProperty("BodyName", out var bodyEl) && bodyEl.ValueKind == JsonValueKind.String)
                body = bodyEl.GetString();
            int? gui = null;
            if (root.TryGetProperty("GuiFocus", out var guiEl) && guiEl.TryGetInt32(out var g))
                gui = g;
            string? legal = null;
            if (root.TryGetProperty("LegalState", out var legalEl) && legalEl.ValueKind == JsonValueKind.String)
                legal = legalEl.GetString();

            double? lat = null;
            double? lng = null;
            if (root.TryGetProperty("Latitude", out var latEl) && latEl.TryGetDouble(out var latV))
                lat = latV;
            if (root.TryGetProperty("Longitude", out var lngEl) && lngEl.TryGetDouble(out var lngV))
                lng = lngV;

            return new EliteStatusSummary
            {
                Flags = root.TryGetProperty("Flags", out var f) && f.TryGetInt32(out var flags) ? flags : 0,
                Flags2 = root.TryGetProperty("Flags2", out var f2) && f2.TryGetInt32(out var flags2) ? flags2 : 0,
                BodyName = body,
                GuiFocus = gui,
                LegalState = legal,
                Latitude = lat,
                Longitude = lng,
                StatusFileExists = true,
            };
        }
        catch
        {
            return new EliteStatusSummary { StatusFileExists = false };
        }
    }
}
