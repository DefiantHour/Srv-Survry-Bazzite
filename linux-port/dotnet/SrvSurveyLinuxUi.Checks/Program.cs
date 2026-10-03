using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Checks;

static class Program
{
    static int _failed;
    static int _passed;

    static int Main()
    {
        CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
        CultureInfo.DefaultThreadCurrentUICulture = CultureInfo.InvariantCulture;

        var root = Path.Combine(Path.GetTempPath(), "srvsurvey-ui-checks-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        Environment.SetEnvironmentVariable("XDG_DATA_HOME", Path.Combine(root, "data"));
        Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", Path.Combine(root, "config"));
        Environment.SetEnvironmentVariable("SRVSURVEY_NET_OFFLINE", "1");
        Environment.SetEnvironmentVariable("SRVSURVEY_RCC_OFFLINE", "1");
        Environment.SetEnvironmentVariable("SRVSURVEY_SKIP_PRESENT_START", "1");
        Environment.SetEnvironmentVariable("SRVSURVEY_SETTINGS_SCAN", "0");
        Environment.SetEnvironmentVariable("SRVSURVEY_ALLOW_PRESENT", null);

        try
        {
            CreditFormatChecks();
            BodyValueChecks();
            ColonySiteChecks();
            CatchUpChecks();
            BioRewardChecks();
            BodyPayloadChecks();
            RavenOfflineChecks();
            FirstFootFileChecks();
            FleetCarrierWindowsChecks();
            PresenterLaunchChecks();
        }
        catch (Exception ex)
        {
            Fail("unhandled: " + ex);
        }
        finally
        {
            try { Directory.Delete(root, true); }
            catch { /* temp cleanup is best-effort */ }
        }

        Console.WriteLine();
        Console.WriteLine($"{_passed} passed, {_failed} failed");
        return _failed == 0 ? 0 : 1;
    }

    static void CreditFormatChecks()
    {
        Eq("credits-small", CreditFormat.Credits(900, true), "900");
        Eq("credits-k", CreditFormat.Credits(12_300, true), "12.3 K");
        Eq("credits-m", CreditFormat.Credits(2_500_000, true), "2.5 M");
        Eq("credits-units", CreditFormat.Credits(50), "50 CR");
    }

    static void BodyValueChecks()
    {
        var metal = BodyValue.GetBodyValue("Metal rich body", false, 1, true, false, true);
        Eq("metal-first-scan", metal, 88716);
        var star = BodyValue.GetBodyValue("NS", false, 1.4, true, false, false);
        True("ns-star-positive", star > 20_000);
        Eq("landable-type", BodyValue.BodyTypeFrom(null, "Rocky body", true, "A 1"), "LandableBody");
        Eq("star-type", BodyValue.BodyTypeFrom("K", null, false, "A"), "Star");
        Eq("giant-type", BodyValue.BodyTypeFrom(null, "Sudarsky class I gas giant", false, "A 2"), "Giant");
    }

    static void ColonySiteChecks()
    {
        True("construction", ColonySite.IsConstructionSite(
            "Planetary Construction Site: Alpha",
            new[] { "colonisationcontribution", "commodities" }));
        False("not-construction", ColonySite.IsConstructionSite("Jameson Memorial", new[] { "commodities" }));
        False("name-only", ColonySite.IsConstructionSite("Orbital Construction Site: Beta", Array.Empty<string>()));
    }

    static void CatchUpChecks()
    {
        var journals = Path.Combine(LinuxPaths.DataDirectory, "journals");
        Directory.CreateDirectory(journals);
        var path = Path.Combine(journals, "Journal.260101000000.01.log");
        File.WriteAllLines(path, new[]
        {
            """{"timestamp":"2026-01-01T00:00:00Z","event":"LoadGame","Commander":"Defiant Hour","FID":"F0001","Odyssey":true}""",
            """{"timestamp":"2026-01-01T00:01:00Z","event":"Location","StarSystem":"Sol","SystemAddress":10477373803,"Body":"Earth","Docked":true,"StationName":"Planetary Construction Site: Luna","StationType":"OnFootSettlement","StationServices":["colonisationcontribution"],"MarketID":1}""",
            """{"timestamp":"2026-01-01T00:02:00Z","event":"FSDJump","StarSystem":"Wolf 359","SystemAddress":20,"JumpDist":7.8,"Body":"Wolf 359"}""",
            """{"timestamp":"2026-01-01T00:03:00Z","event":"Scan","ScanType":"Detailed","BodyName":"Wolf 359 1","BodyID":1,"PlanetClass":"Metal rich body","MassEM":1.0,"Landable":true,"WasDiscovered":false,"WasMapped":false,"DistanceFromArrivalLS":12}""",
            """{"timestamp":"2026-01-01T00:04:00Z","event":"SAAScanComplete","BodyName":"Wolf 359 1","ProbesUsed":3,"EfficiencyTarget":5}""",
            """{"timestamp":"2026-01-01T00:05:00Z","event":"FSSBodySignals","BodyName":"Wolf 359 1","Signals":[{"Type":"$SAA_SignalType_Biological;","Count":2}]}""",
            """{"timestamp":"2026-01-01T00:06:00Z","event":"SAASignalsFound","BodyName":"Wolf 359 1","Genuses":[{"Genus_Localised":"Bacterium"}]}""",
            """{"timestamp":"2026-01-01T00:07:00Z","event":"Touchdown","Body":"Wolf 359 1"}""",
            """{"timestamp":"2026-01-01T00:08:00Z","event":"ScanOrganic","ScanType":"Analyse","Species_Localised":"Bacterium Acies","SystemAddress":20,"BodyID":1,"Body":"Wolf 359 1"}""",
            """{"timestamp":"2026-01-01T00:09:00Z","event":"FSSAllBodiesFound","SystemAddress":20}""",
            """{"timestamp":"2026-01-01T00:10:00Z","event":"Docked","StationName":"Fleet Carrier Name","StationType":"FleetCarrier","MarketID":3700000000,"StationServices":["commodities"]}""",
        });

        var rec = CommanderStore.LoadOrCreate("F0001", "Defiant Hour");
        JournalCatchUp.Apply(rec, journals);

        Eq("cmdr", rec.Commander, "Defiant Hour");
        Eq("jumps", rec.CountJumps, 1);
        True("distance", Math.Abs(rec.DistanceTravelled - 7.8) < 0.001);
        True("scans", rec.CountScans >= 1);
        True("dss", rec.CountDss >= 1);
        Eq("landed", rec.CountLanded, 1);
        True("expl", rec.ExplRewards > 0);
        Eq("system", rec.CurrentSystem, "Wolf 359");
        Eq("body-type", rec.BodyScans["Wolf 359 1"].BodyType, "LandableBody");
        Eq("bio-signals", rec.BodyScans["Wolf 359 1"].BioSignals, 2);
        Eq("genus", rec.BodyScans["Wolf 359 1"].Genuses.FirstOrDefault(), "Bacterium");
        True("fss", rec.FssAllBodies);
        True("fc", rec.IsFleetCarrier);
        Eq("market", rec.LastMarketId, 3700000000);
        True("bio-entry", rec.ScannedBioEntryIds.Count == 1);

        var expl = rec.ExplRewards;
        var offset = rec.LastJournalOffset;
        JournalCatchUp.Apply(rec, journals);
        Eq("no-double-expl", rec.ExplRewards, expl);
        Eq("offset-stable", rec.LastJournalOffset, offset);

        var before = rec.BodyScans.Count;
        JournalCatchUp.ApplyLine(rec, """{"event":"Location","StarSystem":"Wolf 359","SystemAddress":20,"Body":"Wolf 359 1"}""");
        Eq("same-system-keeps-scans", rec.BodyScans.Count, before);

        JournalCatchUp.ApplyLine(rec, """{"event":"Location","StarSystem":"Sol","SystemAddress":10477373803,"Body":"Earth"}""");
        Eq("new-system-clears-scans", rec.BodyScans.Count, 0);

        var oldJournal = Path.Combine(journals, "Journal.250101000000.01.log");
        File.WriteAllLines(oldJournal, new[]
        {
            """{"timestamp":"2025-01-01T00:00:00Z","event":"FSDJump","StarSystem":"Old","SystemAddress":1,"JumpDist":99}""",
        });
        var fresh = CommanderStore.LoadOrCreate("F0009", "Fresh Start");
        JournalCatchUp.Apply(fresh, journals);
        Eq("first-run-skips-old-journals", fresh.CountJumps, 1);
        Eq("first-run-current-file", Path.GetFileName(fresh.LastJournalFile), "Journal.260101000000.01.log");

        CommanderStore.ResetExploration(rec);
        Eq("reset-expl", rec.ExplRewards, 0);
        Eq("reset-jumps", rec.CountJumps, 0);
        CommanderStore.ResetBio(rec);
        Eq("reset-bio", rec.OrganicRewards, 0);
        Eq("reset-bio-ids", rec.ScannedBioEntryIds.Count, 0);
    }

    static void BioRewardChecks()
    {
        var rec = new CommanderRecord { CurrentSystemAddress = 20 };
        rec.BodyScans["A 1"] = new BodyScanRecord
        {
            BodyId = 1,
            BioSignals = 2,
            BioAnalyzed = 1,
        };
        rec.BodyScans["A 1"].Genuses.Add("Bacterium");
        rec.ScannedBioEntryIds.Add("20_1_1400102_100000_True");
        rec.BodyFirstFoot["A 1"] = true;
        CommanderStore.RecalcOrganicRewards(rec);
        Eq("organic-first-foot", rec.OrganicRewards, 500000);
        Eq("format-unclaimed", BioRewards.FormatUnclaimed(rec), "500 K, organisms: 1");
        var values = BioRewards.FormatValues(100000, 200000, true, true);
        True("format-values", values.Contains("100 K of 200 K?", StringComparison.Ordinal) && values.Contains("(FF)"));
        True("uncertain", BioRewards.ValuesUncertain(rec, "A 1"));
        Eq("ff-bodies", BioRewards.FirstFootBodies(rec), 1);
    }

    static void BodyPayloadChecks()
    {
        var rec = new CommanderRecord { CurrentSystemAddress = 20 };
        rec.BodyScans["Wolf 359 1"] = new BodyScanRecord
        {
            BodyId = 1,
            PlanetClass = "Metal rich body",
            BodyType = "LandableBody",
            Landable = true,
            DistLs = 12,
            BioSignals = 2,
        };
        var json = SystemBodiesPayload.Build(rec);
        using var doc = JsonDocument.Parse(json);
        True("payload-array", doc.RootElement.ValueKind == JsonValueKind.Array);
        Eq("payload-type", doc.RootElement[0].GetProperty("type").GetString(), "mrb");
        True("payload-landable", doc.RootElement[0].GetProperty("features").EnumerateArray().Any(x => x.GetString() == "landable"));
    }

    static void RavenOfflineChecks()
    {
        True("offline-flag", RavenColonialClient.IsOffline());
        var pub = RavenColonialClient.PublishFcAsync("F0001", 1, "A", "A").GetAwaiter().GetResult();
        True("publish-skipped", pub.Skipped);
        var bodies = RavenColonialClient.UpdateSysBodiesAsync(20, "[]").GetAwaiter().GetResult();
        True("bodies-skipped", bodies.Skipped);
        var primary = RavenColonialClient.SetPrimaryAsync("Defiant Hour", "abc").GetAwaiter().GetResult();
        True("primary-skipped", primary.Skipped);
    }

    static void FleetCarrierWindowsChecks()
    {
        var json = RavenColonialClient.BuildPublishFcJson(3700317696, "MFY-8HZ", "mayfly");
        True("fc-json-has-null-cargo", json.Contains("\"cargo\":null", StringComparison.Ordinal));
        True("fc-json-has-names", json.Contains("\"name\":\"MFY-8HZ\"", StringComparison.Ordinal)
            && json.Contains("\"displayName\":\"mayfly\"", StringComparison.Ordinal));

        var rec = new CommanderRecord();
        JournalCatchUp.ApplyLine(rec, """{"event":"FSSSignalDiscovered","SignalType":"FleetCarrier","SignalName":"mayfly MFY-8HZ"}""");
        Eq("fc-fss-display", FleetCarrierNames.DisplayNameFor(rec, "MFY-8HZ"), "mayfly");
        JournalCatchUp.ApplyLine(rec, """{"event":"ReceiveText","From":"Big Bertha | V0B-B2H"}""");
        Eq("fc-receive-strip-pipe", FleetCarrierNames.DisplayNameFor(rec, "V0B-B2H"), "Big Bertha");

        var projects = new[]
        {
            new RavenProject { BuildId = "abc", SystemAddress = 10, MarketId = 20 },
        };
        Eq("build-id-dock", RavenColonialClient.BuildIdForDock(projects, 10, 20), "abc");
        Eq("build-id-miss", RavenColonialClient.BuildIdForDock(projects, 10, 99), null);
    }

    static void FirstFootFileChecks()
    {
        var rec = CommanderStore.LoadOrCreate("F0002", "Tester");
        CommanderStore.Save(rec);
        rec.BodyFirstFoot["Body A"] = true;
        CommanderStore.Save(rec);
        True("first-foot-write", CmdrBodyFlags.TryGetFirstFoot("Tester", "Body A") == true);
        True("find-by-name", CmdrBodyFlags.FindFile("Tester") != null);
    }

    static void PresenterLaunchChecks()
    {
        Environment.SetEnvironmentVariable("SRVSURVEY_SKIP_PRESENT_START", "1");
        False("skip-present-start", SettingsLauncher.TryStartPresenter());
        Environment.SetEnvironmentVariable("SRVSURVEY_SKIP_PRESENT_START", null);
        Environment.SetEnvironmentVariable("SRVSURVEY_ALLOW_PRESENT", null);
        var livePresenter = SettingsLauncher.FindLivePresenterPid() is > 0;
        var started = SettingsLauncher.TryStartPresenter();
        if (livePresenter)
            True("gated-present-start", started);
        else
            False("gated-present-start", started);
        True(
            "gated-message",
            livePresenter
            || (SettingsLauncher.LastError ?? "").Contains("gated", StringComparison.Ordinal));
        Environment.SetEnvironmentVariable("SRVSURVEY_SKIP_PRESENT_START", "1");
        Environment.SetEnvironmentVariable("SRVSURVEY_SETTINGS_SCAN", "0");
        False("settings-closed", SettingsLauncher.IsSettingsOpen());
        True(
            "settings-lock-config",
            LinuxPaths.SettingsLockPaths.Any(p =>
                p.Contains($"{Path.DirectorySeparatorChar}config{Path.DirectorySeparatorChar}srvsurvey{Path.DirectorySeparatorChar}settings.lock", StringComparison.Ordinal)
                || p.EndsWith($"{Path.DirectorySeparatorChar}srvsurvey{Path.DirectorySeparatorChar}settings.lock", StringComparison.Ordinal)));
        True("settings-pid1-not-settings", !SettingsLauncher.PidLooksLikeSettings(1));
        SettingsLauncher.StopPresenter();
        True("stop-presenter-quit-file", File.Exists(SettingsLauncher.RequestQuitPath));
    }

    static void Eq<T>(string name, T actual, T expected)
    {
        if (Equals(actual, expected))
            Pass(name);
        else
            Fail($"{name}: expected {expected}, got {actual}");
    }

    static void True(string name, bool value)
    {
        if (value)
            Pass(name);
        else
            Fail(name + " was false");
    }

    static void False(string name, bool value) => True(name, !value);

    static void Pass(string name)
    {
        _passed++;
        Console.WriteLine("PASS  " + name);
    }

    static void Fail(string name)
    {
        _failed++;
        Console.WriteLine("FAIL  " + name);
    }
}
