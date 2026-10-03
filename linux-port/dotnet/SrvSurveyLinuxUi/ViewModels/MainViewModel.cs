using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Input.Platform;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using SrvSurveyLinuxUi.Services;
using SrvSurveyLinuxUi.Views;

namespace SrvSurveyLinuxUi.ViewModels;

public partial class MainViewModel : ViewModelBase, IDisposable
{
    const string RavenColonialUrl = "https://ravencolonial.com";
    const string ColonisationWikiUrl =
        "https://github.com/njthomson/SrvSurvey/wiki/Colonization";
    const string ProjectWikiUrl = "https://github.com/njthomson/SrvSurvey/wiki";
    const string RamTahGuideUrl = "https://canonn.science/codex/ram-tahs-mission/";
    const string DiscordUrl = "https://discord.gg/GJjTFa9fsz";
    const string CanonnSignalsBase =
        "https://canonn-science.github.io/canonn-signals/?system=";

    readonly AppConfigStore _config = new();
    readonly DispatcherTimer _timer;
    string? _journalFolder;
    string? _journalFile;
    string? _systemName;
    string? _commanderName;
    string? _bodyName;
    int _hostPid;
    bool _suppressHideWrite;
    bool _suppressFoot;
    JournalSummary _journalCache = new();
    DateTime _journalMtimeUtc = DateTime.MinValue;
    long _journalLength = -1;
    CommanderRecord? _cmdr;
    string _catchUpStamp = "";
    IReadOnlyList<RavenProject> _projects = Array.Empty<RavenProject>();
    string? _primaryBuildId;
    string? _localBuildId;
    string _rccCacheKey = "";
    DateTime _rccCacheUtc = DateTime.MinValue;
    bool _rccBusy;

    public MainViewModel()
    {
        _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
        _timer.Tick += (_, _) => Refresh();
        Refresh();
        _timer.Start();
    }

    [ObservableProperty] private string _windowTitle = "Srv Survey";
    [ObservableProperty] private string _commanderText = "";
    [ObservableProperty] private string _locationText = "";
    [ObservableProperty] private string _nearBodyText = "";
    [ObservableProperty] private string _vehicleText = "";
    [ObservableProperty] private string _modeText = "Game is not active";
    [ObservableProperty] private string _explorationValueText = "-";
    [ObservableProperty] private string _jumpsText = "-";
    [ObservableProperty] private string _distanceText = "-";
    [ObservableProperty] private string _bodiesText = "-";
    [ObservableProperty] private string _bioRewardsText = "-";
    [ObservableProperty] private string _systemBioSignalsText = "-";
    [ObservableProperty] private string _systemBioValuesText = "-";
    [ObservableProperty] private string _bodyBioSignalsText = "-";
    [ObservableProperty] private string _bodyBioValuesText = "-";
    [ObservableProperty] private string _presentStatusText = "Present: unknown";
    [ObservableProperty] private string _overlayStatusText = "Overlay: —";
    [ObservableProperty] private string _journalStatusText = "Journal: not found";
    [ObservableProperty] private string _statusLineText = "";
    [ObservableProperty] private bool _tempHideOverlays;
    [ObservableProperty] private bool _canCopyLocation;
    [ObservableProperty] private bool _presenterRunning;
    [ObservableProperty] private bool _bioSectionEnabled;
    [ObservableProperty] private bool _hideNonColonisationOverlays;
    [ObservableProperty] private bool _firstFootFall;
    [ObservableProperty] private bool _firstFootFallEnabled;
    [ObservableProperty] private string _guardianDetectedText = "Detected:  0";
    [ObservableProperty] private string _guardianSitesText = "";
    [ObservableProperty] private string _guardianSiteLine = "";
    [ObservableProperty] private bool _guardianSiteActive;
    [ObservableProperty] private bool _systemBioEnabled;
    [ObservableProperty] private bool _bodyBioEnabled;
    [ObservableProperty] private string _targetDisplayText = "<none>";
    [ObservableProperty] private string _targetStateText = "Inactive";

    [ObservableProperty] private MainThemeKind _themeKind;
    [ObservableProperty] private bool _gameLive;
    [ObservableProperty] private bool _hasCommander;
    [ObservableProperty] private bool _showNextWindow;
    [ObservableProperty] private bool _showQuestComms;
    [ObservableProperty] private bool _canCodexShow;
    [ObservableProperty] private bool _canResetBio;
    [ObservableProperty] private string _codexText = "?";
    [ObservableProperty] private bool _buildProjectsTest;
    [ObservableProperty] private bool _canRefreshColonise;
    [ObservableProperty] private bool _showLocalProject;
    [ObservableProperty] private bool _showSetPrimary;
    [ObservableProperty] private bool _showColoniseLine1;
    [ObservableProperty] private bool _showNewProject;
    [ObservableProperty] private bool _showPublishFleetCarrier;
    [ObservableProperty] private string _publishFleetCarrierText = "Publish Fleet Carrier";
    [ObservableProperty] private string _setPrimaryText = "Set primary";
    [ObservableProperty] private bool _showUpdateSystemBodies;
    [ObservableProperty] private bool _showUpdateStations;
    [ObservableProperty] private bool _showColoniseUpdateHeader;
    [ObservableProperty] private bool _showJourneyBegin = true;
    [ObservableProperty] private bool _showJourneyActive;
    [ObservableProperty] private bool _showPastJourneys;

    string _codexProgressKey = "";

    public void Dispose()
    {
        _timer.Stop();
        SettingsLauncher.StopPresenter();
    }

    public void EnsurePresenterStarted()
    {
        TryKeepPresenter();
    }

    void TryKeepPresenter()
    {
        var allow = _config.AllowPresent
            || string.Equals(
                Environment.GetEnvironmentVariable("SRVSURVEY_ALLOW_PRESENT"),
                "1",
                StringComparison.Ordinal);
        if (!allow)
            return;
        if (SettingsLauncher.FindLivePresenterPid() is > 0)
            return;
        if (SettingsLauncher.TryStartPresenter())
        {
            StatusLineText = "Started overlay presenter";
            return;
        }

        if (!string.IsNullOrWhiteSpace(SettingsLauncher.LastError))
            StatusLineText = SettingsLauncher.LastError;
    }

    public void Refresh()
    {
        try
        {
            _config.Reload();
            ThemeKind = MainTheme.Select(_config.DarkTheme, _config.ThemeMainBlack);
            ShowQuestComms = _config.EnableQuests;
            BuildProjectsTest = _config.BuildProjectsTest;
            var runtime = RuntimeStateSnapshot.TryLoad();
            ResolveJournal(runtime);
            var journal = ReadJournalCached();
            var status = !string.IsNullOrWhiteSpace(_journalFolder)
                ? EliteStatusReader.TryRead(_journalFolder)
                : null;

            ApplyCommanderBlock(runtime, journal, status);
            EnsureCommander(journal);
            MaybeCatchUp();
            ApplyExplorationBlock();
            ApplyBioBlock(journal, status);
            ApplyCodexBlock();
            ApplyGuardianBlock();
            ApplyTargetBlock();
            ApplyPresentBlock(RuntimeStateSnapshot.TryLoad() ?? runtime);
            ApplyColoniseMenu();
            MaybeRefreshColony();
            HideNonColonisationOverlays = _config.BuildProjectsSuppressOtherOverlays;
            JournalStatusText = string.IsNullOrWhiteSpace(_journalFolder)
                ? "Journal: not found"
                : $"Journal: {_journalFolder}";
        }
        catch (Exception ex)
        {
            StatusLineText = ex.Message;
        }
    }

    JournalSummary ReadJournalCached()
    {
        if (string.IsNullOrWhiteSpace(_journalFile) || !File.Exists(_journalFile))
        {
            _journalCache = new JournalSummary();
            _journalMtimeUtc = DateTime.MinValue;
            _journalLength = -1;
            return _journalCache;
        }

        var info = new FileInfo(_journalFile);
        if (info.LastWriteTimeUtc == _journalMtimeUtc && info.Length == _journalLength)
            return _journalCache;

        _journalCache = JournalSummaryReader.Read(_journalFile);
        _journalMtimeUtc = info.LastWriteTimeUtc;
        _journalLength = info.Length;
        return _journalCache;
    }

    void ResolveJournal(RuntimeStateSnapshot? runtime)
    {
        _journalFolder = null;
        _journalFile = null;
        if (runtime != null)
        {
            if (!string.IsNullOrWhiteSpace(runtime.JournalFolder) && DirectoryExists(runtime.JournalFolder))
                _journalFolder = runtime.JournalFolder;
            if (!string.IsNullOrWhiteSpace(runtime.JournalFile) && FileExists(runtime.JournalFile))
                _journalFile = runtime.JournalFile;
        }

        if (_journalFolder == null)
            return;

        if (_journalFile == null)
            _journalFile = JournalSummaryReader.FindLatestJournal(_journalFolder);
    }

    void ApplyCommanderBlock(
        RuntimeStateSnapshot? runtime,
        JournalSummary journal,
        EliteStatusSummary? status)
    {
        var commander = FirstNonEmpty(runtime?.Commander, journal.Commander);
        var system = FirstNonEmpty(runtime?.System, journal.System);
        var body = FirstNonEmpty(status?.BodyName, runtime?.Body, journal.Body);

        _commanderName = commander;
        _systemName = system;
        _bodyName = body;
        LocationText = FirstNonEmpty(body, system) ?? "";
        CanCopyLocation = !string.IsNullOrWhiteSpace(LocationText);
        WindowTitle = journal.Odyssey == false ? "Srv Survey LEGACY MODE" : "Srv Survey";
        GameLive = status is { StatusFileExists: true };
        HasCommander = !string.IsNullOrWhiteSpace(commander)
            || !string.IsNullOrWhiteSpace(_config.PreferredCommander);

        if (status is { StatusFileExists: true })
        {
            var modeTag = journal.Odyssey == false ? "legacy" : "live";
            CommanderText = string.IsNullOrWhiteSpace(commander)
                ? "— ?"
                : string.IsNullOrWhiteSpace(journal.Fid)
                    ? commander!
                    : $"{commander} (FID:{journal.Fid}, mode:{modeTag})";
            VehicleText = status.InMainShip
                ? FirstNonEmpty(journal.ShipName, "MainShip") ?? ""
                : FirstNonEmpty(status.VehicleLabel, runtime?.Vehicle) ?? "";
            var mode = status.ModeLabel;
            if (mode == "Docked" && !string.IsNullOrWhiteSpace(journal.StationName))
                mode += ": " + journal.StationName;
            ModeText = mode;
            NearBodyText = status.FsdJumping
                ? "Witch space"
                : BodyTypeLabel(body);
        }
        else
        {
            CommanderText = !string.IsNullOrWhiteSpace(_config.PreferredCommander)
                ? _config.PreferredCommander + " (only)"
                : (commander ?? "") + " ?";
            VehicleText = "";
            NearBodyText = "";
            ModeText = "Game is not active";
        }
    }

    void EnsureCommander(JournalSummary journal)
    {
        var fid = FirstNonEmpty(journal.Fid, _cmdr?.Fid);
        var name = FirstNonEmpty(journal.Commander, _commanderName, _config.PreferredCommander);
        if (string.IsNullOrWhiteSpace(fid) && string.IsNullOrWhiteSpace(name))
        {
            _cmdr = null;
            return;
        }

        if (_cmdr != null
            && (string.IsNullOrWhiteSpace(fid) || string.Equals(_cmdr.Fid, fid, StringComparison.OrdinalIgnoreCase))
            && (string.IsNullOrWhiteSpace(name) || string.Equals(_cmdr.Commander, name, StringComparison.OrdinalIgnoreCase)))
            return;

        _cmdr = CommanderStore.LoadOrCreate(fid, name);
        _catchUpStamp = "";
        if (!File.Exists(_cmdr.Path))
            CommanderStore.Save(_cmdr);
    }

    void MaybeCatchUp()
    {
        if (_cmdr == null || string.IsNullOrWhiteSpace(_journalFolder))
            return;
        var stamp = $"{_journalFile}|{_journalLength}|{_journalMtimeUtc.Ticks}";
        if (stamp == _catchUpStamp)
            return;
        JournalCatchUp.Apply(_cmdr, _journalFolder);
        _catchUpStamp = stamp;
        if (!string.IsNullOrWhiteSpace(_cmdr.LastCatchUpError))
            StatusLineText = _cmdr.LastCatchUpError;
    }

    string BodyTypeLabel(string? body)
    {
        if (string.IsNullOrWhiteSpace(body))
            return "Deep space";
        return _cmdr?.BodyTypeFor(body)
            ?? _cmdr?.CurrentBodyType
            ?? "Near body";
    }

    /// <summary>
    /// Windows reads explRewards, countJumps, distanceTravelled and the scan counts from the
    /// commander file, accumulated since the last Reset.
    /// </summary>
    void ApplyExplorationBlock()
    {
        if (_cmdr == null)
        {
            ExplorationValueText = "-";
            JumpsText = "-";
            DistanceText = "-";
            BodiesText = "-";
            return;
        }

        ExplorationValueText = CreditFormat.Credits(_cmdr.ExplRewards, true);
        JumpsText = _cmdr.CountJumps.ToString("N0");
        DistanceText = _cmdr.DistanceTravelled.ToString("N1") + " ly";
        BodiesText = $"Scanned: {_cmdr.CountScans}, DSS: {_cmdr.CountDss}, Landed: {_cmdr.CountLanded}";
    }

    void ApplyBioBlock(JournalSummary journal, EliteStatusSummary? status)
    {
        var gameLive = status is { StatusFileExists: true };
        BioSectionEnabled = gameLive;
        var systemSignals = _cmdr != null
            ? BioRewards.SystemSignals(_cmdr)
            : (scanned: journal.SystemBioAnalyzed, total: journal.SystemBioTotal);
        if (systemSignals.total == 0 && journal.SystemBioTotal > 0)
            systemSignals = (scanned: journal.SystemBioAnalyzed, total: journal.SystemBioTotal);
        var bodySignals = _cmdr != null
            ? BioRewards.BodySignals(_cmdr, _bodyName)
            : (scanned: journal.BodyBioAnalyzed, total: journal.BodyBioTotal);
        if (bodySignals.total == 0 && journal.BodyBioTotal > 0)
            bodySignals = (scanned: journal.BodyBioAnalyzed, total: journal.BodyBioTotal);

        SystemBioEnabled = gameLive && systemSignals.total > 0;
        BodyBioEnabled = gameLive && bodySignals.total > 0;
        CanCodexShow = SystemBioEnabled;
        CanResetBio = gameLive && _cmdr != null && _cmdr.OrganicRewards > 0;
        BioRewardsText = _cmdr != null
            ? BioRewards.FormatUnclaimed(_cmdr)
            : "-";

        if (!gameLive)
        {
            SystemBioSignalsText = "-";
            SystemBioValuesText = "-";
            BodyBioSignalsText = "-";
            BodyBioValuesText = "-";
            SetFirstFoot(false, false);
            return;
        }

        if (systemSignals.total > 0)
        {
            SystemBioSignalsText = $"{systemSignals.scanned} of {systemSignals.total}";
            if (_cmdr != null)
            {
                var refs = CodexRefStore.LoadAll();
                SystemBioValuesText = BioRewards.FormatValues(
                    BioRewards.ActualForSystem(_cmdr),
                    BioRewards.EstimateForSystem(_cmdr, refs),
                    BioRewards.ValuesUncertain(_cmdr),
                    false,
                    BioRewards.FirstFootBodies(_cmdr));
            }
            else
                SystemBioValuesText = "— of —?";
        }
        else
        {
            SystemBioSignalsText = "-";
            SystemBioValuesText = "-";
        }

        if (bodySignals.total > 0)
        {
            BodyBioSignalsText = $"{bodySignals.scanned} of {bodySignals.total}";
            if (_cmdr != null)
            {
                var refs = CodexRefStore.LoadAll();
                var firstFoot = !string.IsNullOrWhiteSpace(_bodyName)
                    && _cmdr.BodyFirstFoot.TryGetValue(_bodyName, out var ff)
                    && ff;
                BodyBioValuesText = BioRewards.FormatValues(
                    BioRewards.ActualForBody(_cmdr, _bodyName),
                    BioRewards.EstimateForBody(_cmdr, _bodyName, refs),
                    BioRewards.ValuesUncertain(_cmdr, _bodyName),
                    firstFoot);
            }
            else
                BodyBioValuesText = "— of —?";
        }
        else
        {
            BodyBioSignalsText = "-";
            BodyBioValuesText = "-";
        }

        var known = _cmdr != null && !string.IsNullOrWhiteSpace(_bodyName)
            && _cmdr.BodyFirstFoot.TryGetValue(_bodyName, out var stored)
            ? stored
            : CmdrBodyFlags.TryGetFirstFoot(_commanderName, _bodyName);
        var canFoot = !string.IsNullOrWhiteSpace(_bodyName)
            && (_cmdr != null || CmdrBodyFlags.FindFile(_commanderName) != null);
        SetFirstFoot(known == true, canFoot);
    }

    void SetFirstFoot(bool value, bool enabled)
    {
        _suppressFoot = true;
        FirstFootFall = value;
        FirstFootFallEnabled = enabled && !string.IsNullOrWhiteSpace(_bodyName);
        _suppressFoot = false;
    }

    void ApplyGuardianBlock()
    {
        if (string.IsNullOrWhiteSpace(_systemName))
        {
            GuardianDetectedText = "Detected:  0";
            GuardianSitesText = "";
            GuardianSiteLine = "";
            GuardianSiteActive = false;
            return;
        }

        var inSystem = GuardianCatalogue.Load()
            .Where(row => string.Equals(row.SystemName, _systemName, StringComparison.OrdinalIgnoreCase))
            .ToList();
        var here = inSystem
            .Take(12)
            .Select(row => $"{row.Id}  {row.BodyName}  {row.SiteType} {row.IndexText}".Trim())
            .ToList();
        var count = inSystem.Count;
        GuardianDetectedText = "Detected:  " + count.ToString(CultureInfo.InvariantCulture);
        GuardianSiteLine = here.FirstOrDefault() ?? "";
        GuardianSiteActive = GameLive
            && !string.IsNullOrWhiteSpace(_bodyName)
            && inSystem.Any(row => string.Equals(row.BodyName, _bodyName, StringComparison.OrdinalIgnoreCase)
                && row.SiteHeading is not null and not -1);
        if (count > here.Count)
            here.Add($"+{count - here.Count} more in All Guardian Sites");
        GuardianSitesText = string.Join(Environment.NewLine, here);
    }

    /// <summary>
    /// CommanderCodex.completionProgress: discoveries that are bio (EntryID 1400102 and up) or a
    /// green gas giant, over the number of codexRef entries.
    /// </summary>
    void ApplyCodexBlock()
    {
        var progressPath = DataFileLocator.CodexBingoProgressPath;
        var refPath = DataFileLocator.CodexRefPath;
        var key = $"{StampOf(progressPath)}|{StampOf(refPath)}";
        if (key == _codexProgressKey)
            return;
        _codexProgressKey = key;

        var refCount = CodexRefStore.LoadAll().Count;
        if (refCount == 0)
        {
            CodexText = "?";
            return;
        }

        var valid = CodexRefStore.LoadBingoProgress()
            .Count(id => long.TryParse(id, NumberStyles.None, CultureInfo.InvariantCulture, out var entryId)
                && (entryId >= 1400102 || GreenGasGiantEntryIds.Contains(entryId)));
        var progress = (double)valid / refCount;
        CodexText = progress > 0
            ? Math.Floor(progress * 100).ToString(CultureInfo.InvariantCulture) + "%"
            : "?";
    }

    static readonly long[] GreenGasGiantEntryIds =
        { 1200102, 1200302, 1200402, 1200502, 1200602, 1200702, 1200802, 1200902 };

    static string StampOf(string path)
    {
        try
        {
            var info = new FileInfo(path);
            return info.Exists ? $"{info.LastWriteTimeUtc.Ticks}:{info.Length}" : "none";
        }
        catch
        {
            return "none";
        }
    }

    /// <summary>Main.updateColonizationMenuItems.</summary>
    void ApplyColoniseMenu()
    {
        CanRefreshColonise = GameLive;
        var address = _cmdr?.LastDockedSystemAddress ?? 0;
        if (address == 0)
            address = _cmdr?.CurrentSystemAddress ?? 0;
        _localBuildId = RavenColonialClient.BuildIdForDock(
            _projects,
            address,
            _cmdr?.LastMarketId ?? 0);
        var construction = _cmdr?.IsConstructionSite == true;
        ShowLocalProject = !string.IsNullOrWhiteSpace(_localBuildId);
        ShowSetPrimary = ShowLocalProject;
        SetPrimaryText = !string.IsNullOrWhiteSpace(_localBuildId)
            && string.Equals(_localBuildId, _primaryBuildId, StringComparison.OrdinalIgnoreCase)
            ? "Clear primary"
            : "Set primary";
        ShowColoniseLine1 = HasCommander || ShowLocalProject;
        ShowNewProject = construction && string.IsNullOrWhiteSpace(_localBuildId);
        ShowPublishFleetCarrier = _cmdr?.IsFleetCarrier == true;
        PublishFleetCarrierText = ShowPublishFleetCarrier && !string.IsNullOrWhiteSpace(_cmdr?.LastStationName)
            ? "Publish FC: " + _cmdr!.LastStationName
            : "Publish Fleet Carrier";
        ShowUpdateSystemBodies = _cmdr?.FssAllBodies == true;
        ShowUpdateStations = GameLive && (_cmdr?.CurrentSystemAddress ?? 0) > 0;
        ShowColoniseUpdateHeader = ShowPublishFleetCarrier || ShowUpdateSystemBodies || ShowUpdateStations;
    }

    void MaybeRefreshColony(bool force = false)
    {
        if (string.IsNullOrWhiteSpace(_commanderName) || RavenColonialClient.IsOffline())
            return;
        var key = $"{_commanderName}|{_cmdr?.LastMarketId}|{_cmdr?.CurrentSystemAddress}";
        if (!force
            && key == _rccCacheKey
            && (DateTime.UtcNow - _rccCacheUtc).TotalSeconds < 30)
            return;
        _rccCacheKey = key;
        if (_rccBusy)
            return;
        _ = RefreshColonyAsync();
    }

    async Task RefreshColonyAsync()
    {
        if (_rccBusy)
            return;
        _rccBusy = true;
        try
        {
            var cmdr = _commanderName;
            var projects = await RavenColonialClient.GetActiveProjectsAsync(cmdr);
            var primary = await RavenColonialClient.GetPrimaryAsync(cmdr);
            await Dispatcher.UIThread.InvokeAsync(() =>
            {
                _projects = projects;
                _primaryBuildId = primary;
                _rccCacheUtc = DateTime.UtcNow;
                ApplyColoniseMenu();
            });
        }
        catch (Exception ex)
        {
            StatusLineText = ex.Message;
        }
        finally
        {
            _rccBusy = false;
        }
    }

    /// <summary>Main.menuJourney_Opening.</summary>
    public void RefreshJourneyMenu()
    {
        if (!HasCommander)
            return;
        var journeys = JourneyStore.ListAll()
            .Where(j => string.IsNullOrWhiteSpace(_commanderName)
                || string.IsNullOrWhiteSpace(j.Commander)
                || string.Equals(j.Commander, _commanderName, StringComparison.OrdinalIgnoreCase))
            .ToList();
        var active = journeys.Any(j => j.EndTime == null);
        ShowJourneyBegin = !active;
        ShowJourneyActive = active;
        ShowPastJourneys = journeys.Count > 0;
    }

    void ApplyTargetBlock()
    {
        if (_config.TargetLatLongActive)
        {
            TargetDisplayText = _config.TargetLat.ToString("+0.######;-0.######;0", CultureInfo.InvariantCulture)
                + ", "
                + _config.TargetLong.ToString("+0.######;-0.######;0", CultureInfo.InvariantCulture);
            TargetStateText = "Active";
        }
        else
        {
            TargetDisplayText = "<none>";
            TargetStateText = "Inactive";
        }
    }

    partial void OnFirstFootFallChanged(bool value)
    {
        if (_suppressFoot || !FirstFootFallEnabled)
            return;
        if (_cmdr != null && !string.IsNullOrWhiteSpace(_bodyName))
        {
            _cmdr.BodyFirstFoot[_bodyName] = value;
            CommanderStore.Save(_cmdr);
            return;
        }

        if (!CmdrBodyFlags.TrySetFirstFoot(_commanderName, _bodyName, value))
            StatusLineText = "First Footfall was not saved. There is no commander file for this body.";
    }

    void ApplyPresentBlock(RuntimeStateSnapshot? runtime)
    {
        _hostPid = SettingsLauncher.FindLivePresenterPid() ?? 0;
        PresenterRunning = _hostPid > 0;

        var allow = _config.AllowPresent
            || string.Equals(
                Environment.GetEnvironmentVariable("SRVSURVEY_ALLOW_PRESENT"),
                "1",
                StringComparison.Ordinal);

        PresentStatusText = allow
            ? (PresenterRunning ? $"Present: active (pid {_hostPid})" : "Present: allowed (host idle)")
            : "Present: gated (allow_present=false)";

        var visible = runtime?.OverlayVisible ?? _config.OverlayVisible;
        OverlayStatusText = PresenterRunning
            ? (visible ? "Overlay: shown" : "Overlay: hidden")
            : (_config.OverlayVisible ? "Overlay: will show on present" : "Overlay: start hidden");

        _suppressHideWrite = true;
        TempHideOverlays = !_config.OverlayVisible;
        _suppressHideWrite = false;
    }

    partial void OnTempHideOverlaysChanged(bool value)
    {
        if (_suppressHideWrite)
            return;
        try
        {
            var wantVisible = !value;
            _config.SetOverlayVisible(wantVisible);
            if (PresenterRunning)
            {
                var runtime = RuntimeStateSnapshot.TryLoad();
                var currentlyVisible = runtime?.OverlayVisible ?? true;
                if (currentlyVisible != wantVisible)
                    SettingsLauncher.TrySignalOverlayToggle(_hostPid);
            }
            else if (wantVisible)
            {
                SettingsLauncher.TryStartPresenter();
            }
            StatusLineText = wantVisible
                ? "Overlays set to show"
                : "Overlays set to hide";
            ApplyPresentBlock(RuntimeStateSnapshot.TryLoad());
        }
        catch (Exception ex)
        {
            StatusLineText = ex.Message;
        }
    }

    [RelayCommand]
    async Task CopyLocationAsync()
    {
        if (string.IsNullOrWhiteSpace(LocationText))
            return;
        var clipboard = Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop
            ? desktop.MainWindow?.Clipboard
            : null;
        if (clipboard == null)
        {
            StatusLineText = "Clipboard unavailable";
            return;
        }
        await clipboard.SetTextAsync(LocationText);
        StatusLineText = "Copied location";
    }

    [RelayCommand]
    void OpenSettings()
    {
        if (SettingsLauncher.TryOpenGtkSettings())
        {
            StatusLineText = "Opened GTK settings";
            return;
        }
        StatusLineText = SettingsLauncher.LastError ?? "Could not open settings";
    }

    [RelayCommand]
    void ToggleOverlay()
    {
        if (!PresenterRunning)
        {
            TempHideOverlays = !TempHideOverlays;
            return;
        }

        if (SettingsLauncher.TrySignalOverlayToggle(_hostPid))
        {
            StatusLineText = "Sent SIGUSR1 toggle to presenter";
            Dispatcher.UIThread.Post(Refresh, DispatcherPriority.Background);
            return;
        }

        StatusLineText = SettingsLauncher.LastError ?? "Toggle failed";
    }

    [RelayCommand]
    void Quit()
    {
        if (SettingsLauncher.IsSettingsOpen())
        {
            StatusLineText = "Close Settings first, then quit.";
            SettingsQuitGate.ShowNotice();
            return;
        }
        SettingsQuitGate.RequestQuit();
    }

    [RelayCommand]
    void SphericalSearch()
    {
        WindowHost.Show(new SphereLimitWindow());
        StatusLineText = "Opened spherical search limit";
    }

    [RelayCommand]
    void BoxelSearch()
    {
        WindowHost.Show(new BoxelSearchWindow());
        StatusLineText = "Opened boxel search";
    }

    [RelayCommand]
    void NearestBodies()
    {
        WindowHost.Show(new NearestBodiesWindow(_systemName));
        StatusLineText = "Opened Spansh nearest-body search";
    }

    [RelayCommand]
    void NearestSystems()
    {
        WindowHost.Show(new NearestSystemsWindow());
        StatusLineText = "Opened Canonn nearest-system search";
    }

    [RelayCommand]
    void RuinMap()
    {
        WindowHost.Show(new RuinMapWindow());
        StatusLineText = "Opened guardian ruin map";
    }

    [RelayCommand]
    void RuinBrowser()
    {
        WindowHost.Show(new RuinBrowserWindow());
        StatusLineText = "Opened guardian ruin browser";
    }

    [RelayCommand]
    void EditGuardianMap()
    {
        WindowHost.Show(new GuardianMapEditorWindow());
        StatusLineText = "Opened guardian map editor";
    }

    [RelayCommand]
    void ShareGuardianSites()
    {
        WindowHost.Show(new ShareGuardianWindow());
        StatusLineText = "Opened share guardian sites";
    }

    [RelayCommand]
    void CheckForUpdates()
    {
        WindowHost.Show(new GithubUpdateWindow());
        StatusLineText = "Opened update check";
    }

    [RelayCommand]
    void ErrorReport()
    {
        WindowHost.Show(new ErrorReportWindow());
        StatusLineText = "Opened error report";
    }

    [RelayCommand]
    void OpenCanonnSignals()
    {
        var system = FirstNonEmpty(_systemName, LocationText);
        if (string.IsNullOrWhiteSpace(system))
        {
            StatusLineText = "No system name to open in Canonn Signals";
            return;
        }

        var url = CanonnSignalsBase + Uri.EscapeDataString(system);
        OpenUri(url, "Opened Canonn Signals");
    }

    [RelayCommand]
    void GuardianSites()
    {
        WindowHost.Show(new GuardianSitesGridWindow(_systemName));
        StatusLineText = "Opened Guardian sites";
    }

    [RelayCommand]
    void SurveyMaps()
    {
        WindowHost.Show(new GuardianMapsWindow());
        StatusLineText = "Opened Guardian maps";
    }

    [RelayCommand]
    void RamTahMission()
    {
        WindowHost.Show(new RamTahWindow(_commanderName));
        StatusLineText = "Opened Ram Tah missions";
    }

    [RelayCommand]
    void ShowGuardianMap()
    {
        var mode = TrySetGuardianMode("map");
        WindowHost.Show(new GuardianMapsWindow());
        StatusLineText = mode == null
            ? "Opened Guardian maps. No commander file to store map mode."
            : $"Opened Guardian maps. Guardian mode={mode}.";
    }

    [RelayCommand]
    void AerialAssist()
    {
        var mode = TrySetGuardianMode("aerial");
        StatusLineText = mode == null
            ? "Aerial assist was not saved. No commander file exists yet."
            : $"Aerial assist mode={mode}. This window does not draw the overlay.";
    }

    string? TrySetGuardianMode(string mode)
    {
        if (CmdrDecodeStore.ListCmdrFiles().Count == 0)
            return null;
        return GuardianModeStore.SetMode(mode, _commanderName);
    }

    [RelayCommand]
    void HideTarget()
    {
        _config.Reload();
        _config.SetGroundTarget(_config.TargetLat, _config.TargetLong, false);
        ApplyTargetBlock();
        StatusLineText = "Ground target hidden";
    }

    [RelayCommand]
    async Task CopyTargetAsync()
    {
        var text = TargetStateText == "Active" ? TargetDisplayText : LocationText;
        if (string.IsNullOrWhiteSpace(text) || text == "<none>")
            return;
        var clipboard = Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop
            ? desktop.MainWindow?.Clipboard
            : null;
        if (clipboard == null)
        {
            StatusLineText = "Clipboard unavailable";
            return;
        }
        await clipboard.SetTextAsync(text);
        StatusLineText = "Copied";
    }

    [RelayCommand]
    void OpenLogs()
    {
        WindowHost.Show(new LogsWindow());
        StatusLineText = "Opened logs";
    }

    [RelayCommand]
    void OpenDiscord() =>
        OpenUri(DiscordUrl, "Opened Discord");

    [RelayCommand]
    async Task ResetBio()
    {
        if (_cmdr == null)
            return;
        if (!await ConfirmAsync(
            "Clear unclaimed rewards",
            "Are you sure you want to reset unclaimed exobiology rewards?"))
            return;
        CommanderStore.ResetBio(_cmdr);
        ApplyBioBlock(ReadJournalCached(), !string.IsNullOrWhiteSpace(_journalFolder)
            ? EliteStatusReader.TryRead(_journalFolder)
            : null);
        StatusLineText = "Cleared unclaimed bio rewards";
    }

    [RelayCommand]
    void OpenRamTahGuide() =>
        OpenUri(RamTahGuideUrl, "Opened Ram Tah guide");

    [RelayCommand]
    void CodexBingo()
    {
        WindowHost.Show(new CodexBingoWindow());
        StatusLineText = "Opened Codex bingo";
    }

    [RelayCommand]
    void CodexShow()
    {
        WindowHost.Show(new CodexShowWindow());
        StatusLineText = "Opened Codex species list";
    }

    [RelayCommand]
    void Predictions()
    {
        WindowHost.Show(new PredictionsWindow(_journalFolder));
        StatusLineText = "Opened bio predictions (BioCriteria + journal signals)";
    }

    [RelayCommand]
    async Task RefreshColonise()
    {
        await RefreshColonyAsync();
        StatusLineText = $"{_projects.Count} active project(s)";
    }

    [RelayCommand]
    void MyProjects()
    {
        WindowHost.Show(new MyProjectsWindow());
        StatusLineText = "Opened my projects";
    }

    [RelayCommand]
    void UpdateStationsSites()
    {
        WindowHost.Show(new RavenSitesWindow(_systemName));
        StatusLineText = "Opened Update Stations / Sites (FormRavenUpdater path)";
    }

    [RelayCommand]
    void ScanStationsSites()
    {
        WindowHost.Show(new RavenScanWindow(_systemName));
        StatusLineText = "Opened station scan review";
    }

    [RelayCommand]
    void LocalProject()
    {
        if (!string.IsNullOrWhiteSpace(_localBuildId))
        {
            OpenUri($"{RavenColonialUrl}/#build={Uri.EscapeDataString(_localBuildId)}", "Opened current project");
            return;
        }

        WindowHost.Show(new LocalProjectWindow());
        StatusLineText = "Opened local project";
    }

    [RelayCommand]
    void NewProject()
    {
        WindowHost.Show(new NewProjectWindow(_systemName));
        StatusLineText = "Opened new project";
    }

    [RelayCommand]
    void SetApiKey()
    {
        OpenSettings();
        StatusLineText = "Set the Raven Colonial api-key under Settings > External Data. It is kept in the XDG secrets file.";
    }

    [RelayCommand]
    async Task SetPrimary()
    {
        if (string.IsNullOrWhiteSpace(_commanderName) || string.IsNullOrWhiteSpace(_localBuildId))
        {
            StatusLineText = "Dock at a tracked construction site to set primary.";
            return;
        }

        var clear = string.Equals(_localBuildId, _primaryBuildId, StringComparison.OrdinalIgnoreCase);
        var result = await RavenColonialClient.SetPrimaryAsync(_commanderName, clear ? null : _localBuildId);
        if (result.Ok || result.DryRun)
        {
            _primaryBuildId = clear ? null : _localBuildId;
            ApplyColoniseMenu();
        }

        StatusLineText = result.Status;
        await ShowInfoAsync("Set Primary", result.Status);
    }

    [RelayCommand]
    async Task PublishFleetCarrier()
    {
        if (_cmdr == null || !_cmdr.IsFleetCarrier || _cmdr.LastMarketId <= 0)
        {
            StatusLineText = "Dock at a Fleet Carrier to publish it.";
            return;
        }

        var fid = FirstNonEmpty(_cmdr.Fid, _journalCache.Fid) ?? "";
        var name = _cmdr.LastStationName ?? "";
        var display = FleetCarrierNames.DisplayNameFor(_cmdr, name);
        var result = await RavenColonialClient.PublishFcAsync(fid, _cmdr.LastMarketId, name, display);
        StatusLineText = result.Status;
        await ShowInfoAsync(
            "Publish Fleet Carrier",
            result.Ok || result.DryRun
                ? $"Fleet Carrier {(string.IsNullOrWhiteSpace(display) ? name : display + " - " + name)} has been published and linked to your Commander.\n\nPlease refresh any relevant web pages."
                : result.Status);
    }

    [RelayCommand]
    async Task UpdateSystemBodies()
    {
        if (_cmdr == null || !_cmdr.FssAllBodies || _cmdr.CurrentSystemAddress <= 0)
        {
            StatusLineText = "Finish the FSS scan before updating system bodies.";
            return;
        }

        var payload = SystemBodiesPayload.Build(_cmdr);
        var result = await RavenColonialClient.UpdateSysBodiesAsync(_cmdr.CurrentSystemAddress, payload);
        StatusLineText = result.Status;
        await ShowInfoAsync(
            "Update System Bodies",
            result.Ok || result.DryRun
                ? "System bodies have been updated.\n\nPlease refresh any relevant web pages."
                : result.Status);
    }

    [RelayCommand]
    Task EnableColonisation() =>
        ShowInfoAsync(
            "SrvSurvey",
            "Colonization features will track cargo supplied to construction sites that will be uploaded to"
            + Environment.NewLine + RavenColonialUrl + Environment.NewLine + Environment.NewLine
            + "Turn this on in Settings > External Data, then restart SrvSurvey.");

    [RelayCommand]
    async Task ResetExploration()
    {
        if (_cmdr == null)
            return;
        if (!await ConfirmAsync(
            "SrvSurvey",
            "Are you sure you want to reset estimated exploration values and statistics?"))
            return;
        CommanderStore.ResetExploration(_cmdr);
        ApplyExplorationBlock();
        StatusLineText = "Reset exploration trip counter";
    }

    [RelayCommand]
    void NextWindow()
    {
        WindowHost.Show(new NewCmdrWindow());
        StatusLineText = "Opened start another commander";
    }

    [RelayCommand]
    void OpenRavenColonial()
    {
        var address = _cmdr?.CurrentSystemAddress ?? 0;
        var url = address > 0
            ? $"{RavenColonialUrl}/#sys={address.ToString(CultureInfo.InvariantCulture)}"
            : RavenColonialUrl;
        OpenUri(url, "Opened Raven Colonial");
    }

    [RelayCommand]
    void OpenColonisationWiki() =>
        OpenUri(ColonisationWikiUrl, "Opened colonization wiki");

    [RelayCommand]
    void ToggleHideNonColonisationOverlays()
    {
        try
        {
            var next = !_config.BuildProjectsSuppressOtherOverlays;
            _config.SetBuildProjectsSuppressOtherOverlays(next);
            HideNonColonisationOverlays = next;
            StatusLineText = next
                ? "Hide non-colonization overlays: on (gs.buildProjectsSuppressOtherOverlays)"
                : "Hide non-colonization overlays: off";
        }
        catch (Exception ex)
        {
            StatusLineText = ex.Message;
        }
    }

    [RelayCommand]
    void TargetLatLong()
    {
        WindowHost.Show(new GroundTargetWindow(_journalFolder));
        StatusLineText = "Opened ground target";
    }

    [RelayCommand]
    void JourneyBegin()
    {
        WindowHost.Show(new JourneyBeginWindow(_commanderName, _systemName));
        StatusLineText = "Opened start journey";
    }

    [RelayCommand]
    void JourneyNotes()
    {
        WindowHost.Show(new SystemNotesWindow(_systemName));
        StatusLineText = "Opened system notes";
    }

    [RelayCommand]
    void JourneyReview()
    {
        WindowHost.Show(new JourneyViewerWindow());
        StatusLineText = "Opened journey viewer";
    }

    [RelayCommand]
    void PastJourneys()
    {
        WindowHost.Show(new JourneyListWindow());
        StatusLineText = "Opened past journeys";
    }

    [RelayCommand]
    void FollowRoute()
    {
        WindowHost.Show(new RouteWindow(_journalFolder));
        StatusLineText = "Opened route summary";
    }
    [RelayCommand]
    void OpenJournalFolder()
    {
        if (string.IsNullOrWhiteSpace(_journalFolder))
        {
            StatusLineText = "Journal folder not found";
            return;
        }

        if (ExternalLauncher.TryOpenFolder(_journalFolder))
        {
            StatusLineText = "Opened journal folder";
            return;
        }

        StatusLineText = ExternalLauncher.LastError ?? "Could not open journal folder";
    }

    [RelayCommand]
    void OpenConfigFolder()
    {
        if (ExternalLauncher.TryOpenFolder(LinuxPaths.ConfigDirectory))
        {
            StatusLineText = "Opened config folder";
            return;
        }

        StatusLineText = ExternalLauncher.LastError ?? "Could not open config folder";
    }

    [RelayCommand]
    void OpenProjectWiki() =>
        OpenUri(ProjectWikiUrl, "Opened project wiki");

    [RelayCommand]
    Task ShowAboutAsync()
    {
        var lines = new[]
        {
            "SrvSurvey Linux (Avalonia Main)",
            "",
            $"Commander: {CommanderText}",
            $"Location: {(string.IsNullOrWhiteSpace(LocationText) ? "—" : LocationText)}",
            $"Mode: {ModeText}",
            PresentStatusText,
            OverlayStatusText,
            JournalStatusText,
            "",
            $"Config: {LinuxPaths.ConfigDirectory}",
            $"Data: {LinuxPaths.DataDirectory}",
        };
        return ShowInfoAsync("About / Status", string.Join(Environment.NewLine, lines));
    }

    [RelayCommand]
    void QuestComms()
    {
        WindowHost.Show(new PlayCommsWindow());
        StatusLineText = "Opened quest comms";
    }

    [RelayCommand]
    void QuestCatalog()
    {
        WindowHost.Show(new PlayCommsCatalogWindow());
        StatusLineText = "Opened quest catalog";
    }

    [RelayCommand]
    void QuestDev()
    {
        WindowHost.Show(new PlayDevWindow());
        StatusLineText = "Opened quest dev";
    }

    [RelayCommand]
    void QuestJournal()
    {
        WindowHost.Show(new PlayJournalWindow());
        StatusLineText = "Opened quest journal replay";
    }

    [RelayCommand]
    void PostProcessJournals()
    {
        WindowHost.Show(new PostProcessWindow(_journalFolder));
        StatusLineText = "Opened journal post-process";
    }

    [RelayCommand]
    void SwapStarCache()
    {
        WindowHost.Show(new StarCacheWindow());
        StatusLineText = "Opened star cache swap";
    }

    [RelayCommand]
    void StartNewCmdr()
    {
        WindowHost.Show(new NewCmdrWindow());
        StatusLineText = "Opened start another commander";
    }

    [RelayCommand]
    void MultiFloatie()
    {
        WindowHost.Show(new MultiFloatieWindow(_commanderName ?? ""));
        StatusLineText = "Opened commander strip";
    }

    [RelayCommand]
    void SiteBuilder()
    {
        WindowHost.Show(new SiteBuilderWindow());
        StatusLineText = "Opened site builder";
    }

    [RelayCommand]
    void ShipOffsets()
    {
        WindowHost.Show(new ShipOffsetsWindow());
        StatusLineText = "Opened ship center offsets";
    }

    void OpenUri(string url, string okStatus)
    {
        if (ExternalLauncher.TryOpenUri(url))
        {
            StatusLineText = okStatus;
            return;
        }

        StatusLineText = ExternalLauncher.LastError ?? "Could not open URL";
    }

    async Task<bool> ConfirmAsync(string title, string message)
    {
        if (Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop
            && desktop.MainWindow != null)
            return await ConfirmWindow.AskAsync(desktop.MainWindow, title, message);
        return false;
    }

    async Task ShowInfoAsync(string title, string message)
    {
        if (Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop
            && desktop.MainWindow != null)
        {
            var dlg = new InfoWindow(title, message);
            await dlg.ShowDialog(desktop.MainWindow);
            return;
        }

        StatusLineText = title;
    }

    static string? FirstNonEmpty(params string?[] values)
    {
        foreach (var value in values)
        {
            if (!string.IsNullOrWhiteSpace(value))
                return value;
        }
        return null;
    }

    static bool DirectoryExists(string path)
    {
        try { return Directory.Exists(path); }
        catch { return false; }
    }

    static bool FileExists(string path)
    {
        try { return File.Exists(path); }
        catch { return false; }
    }
}
