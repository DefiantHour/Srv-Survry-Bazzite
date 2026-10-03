using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using SrvSurveyLinuxUi.Services;

namespace SrvSurveyLinuxUi.Views;

/// <summary>
/// PlayState host. Side load and journal replay call runtime/quests.py, which executes chapter Lua.
/// </summary>
public static class QuestPlayStore
{
    static readonly Regex OnFunc = new(@"function\s+on_([A-Za-z0-9_]+)\s*\(", RegexOptions.Compiled);

    public static string StatePath => Path.Combine(LinuxPaths.DataDirectory, "play-state.json");

    public static JsonObject? Load()
    {
        if (!File.Exists(StatePath))
            return null;
        try
        {
            return JsonNode.Parse(File.ReadAllText(StatePath)) as JsonObject;
        }
        catch
        {
            return null;
        }
    }

    public static void Save(JsonObject state)
    {
        Directory.CreateDirectory(LinuxPaths.DataDirectory);
        File.WriteAllText(StatePath, state.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
    }

    public static bool MarkMessageRead(JsonObject state, string msgId)
    {
        return RunHost(
            state,
            "from quests import mark_message_read\nok = mark_message_read(state, "
            + JsonSerializer.Serialize(msgId)
            + ")\n");
    }

    public static bool ReplyMessage(JsonObject state, string msgId, string actionId)
    {
        return RunHost(
            state,
            "from quests import reply_message\nok = reply_message(state, "
            + JsonSerializer.Serialize(msgId)
            + ", "
            + JsonSerializer.Serialize(actionId)
            + ")\n");
    }

    static bool RunHost(JsonObject state, string call)
    {
        var script =
            "import json\n"
            + "state = json.loads("
            + JsonSerializer.Serialize(state.ToJsonString())
            + ")\n"
            + call
            + "print(json.dumps({\"ok\": bool(ok), \"state\": state}))\n";
        try
        {
            var text = BioPredictCli.RunPythonText(script, 60000);
            if (string.IsNullOrWhiteSpace(text) || text[0] != '{')
                return false;
            var parsed = JsonNode.Parse(text) as JsonObject;
            if (parsed?["state"] is JsonObject next)
            {
                state.Clear();
                foreach (var pair in next)
                    state[pair.Key] = pair.Value?.DeepClone();
            }
            return parsed?["ok"]?.GetValue<bool>() == true;
        }
        catch (Exception ex) when (ex is InvalidOperationException or TimeoutException or DirectoryNotFoundException)
        {
            return false;
        }
    }

    public static JsonObject SideLoad(string folder)
    {
        var script =
            "import json\nfrom quests import side_load_quest\n"
            + "print(json.dumps(side_load_quest("
            + JsonSerializer.Serialize(folder)
            + ", data_dir="
            + JsonSerializer.Serialize(LinuxPaths.DataDirectory)
            + ")))\n";
        var text = BioPredictCli.RunPythonText(script, 60000);
        if (string.IsNullOrWhiteSpace(text) || text[0] != '{')
            throw new InvalidDataException(string.IsNullOrWhiteSpace(text) ? "quest side load returned no JSON" : text);
        return JsonNode.Parse(text) as JsonObject
               ?? throw new InvalidDataException("quest side load returned no object");
    }

    public static JsonObject SideLoadIndexed(string folder)
    {
        var questPath = Path.Combine(folder, "quest.json");
        if (!File.Exists(questPath))
            throw new FileNotFoundException("quest.json not found", questPath);
        var raw = JsonNode.Parse(File.ReadAllText(questPath)) as JsonObject
                  ?? throw new InvalidDataException("quest.json must be an object");
        var publisher = raw["publisher"]?.GetValue<string>() ?? "";
        var id = raw["id"]?.GetValue<string>() ?? "";
        if (publisher.Contains('|') || id.Contains('|'))
            throw new InvalidDataException("Quest publisher or ID cannot contain '|' characters");
        var first = raw["firstChapter"]?.GetValue<string>() ?? "";
        var chapters = new JsonObject();
        if (raw["chapters"] is JsonObject embedded)
        {
            foreach (var pair in embedded)
            {
                var source = "";
                if (pair.Value is JsonValue value && value.TryGetValue<string>(out var text))
                    source = text;
                chapters[pair.Key] = source;
            }
        }
        foreach (var lua in Directory.GetFiles(folder, "*.lua"))
            chapters[Path.GetFileNameWithoutExtension(lua)] = File.ReadAllText(lua);
        if (string.IsNullOrWhiteSpace(first) || chapters[first] == null)
            throw new InvalidDataException($"First chapter script not found: {first}.lua");

        var messages = new JsonArray();
        foreach (var md in Directory.GetFiles(folder, "*.md").OrderBy(p => p, StringComparer.Ordinal))
        {
            var msgId = Path.GetFileNameWithoutExtension(md);
            messages.Add(ParseMessage(File.ReadAllText(md), msgId));
        }

        var objectives = new JsonObject();
        if (raw["objectives"] is JsonObject defs)
        {
            foreach (var pair in defs)
            {
                objectives[pair.Key] = new JsonObject
                {
                    ["id"] = pair.Key,
                    ["text"] = pair.Value?.ToString() ?? pair.Key,
                    ["state"] = "hidden",
                    ["current"] = 0,
                    ["total"] = 0,
                };
            }
        }

        var chapterRows = new JsonArray();
        foreach (var pair in chapters)
        {
            var source = pair.Value?.GetValue<string>() ?? "";
            var handlers = new JsonArray();
            foreach (Match match in OnFunc.Matches(source))
                handlers.Add(match.Groups[1].Value);
            chapterRows.Add(new JsonObject
            {
                ["id"] = pair.Key,
                ["source"] = source,
                ["handlers"] = handlers,
                ["start_time"] = null,
                ["end_time"] = null,
                ["active"] = false,
                ["vars"] = new JsonObject(),
            });
        }

        var state = new JsonObject
        {
            ["publisher"] = publisher,
            ["id"] = id,
            ["ver"] = raw["ver"]?.GetValue<double>() ?? 0,
            ["title"] = raw["title"]?.GetValue<string>() ?? id,
            ["firstChapter"] = first,
            ["dev"] = true,
            ["watchFolder"] = folder,
            ["luaExecuted"] = false,
            ["objectives"] = objectives,
            ["messages"] = messages,
            ["chapters"] = chapterRows,
            ["keptLasts"] = new JsonObject(),
            ["pendingHandlers"] = new JsonArray(),
            ["note"] = "Index-only fallback. SideLoad runs chapter Lua through the quest host.",
        };
        ActivateFirst(state);
        Save(state);
        return state;
    }

    public static void ActivateFirst(JsonObject state)
    {
        var first = state["firstChapter"]?.GetValue<string>();
        if (string.IsNullOrWhiteSpace(first) || state["chapters"] is not JsonArray chapters)
            return;
        foreach (var node in chapters)
        {
            if (node is not JsonObject chapter || chapter["id"]?.GetValue<string>() != first)
                continue;
            if (chapter["active"]?.GetValue<bool>() == true)
                return;
            chapter["active"] = true;
            chapter["start_time"] = DateTimeOffset.UtcNow.ToString("o");
            chapter["end_time"] = null;
            return;
        }
    }

    public static List<string> ApplyJournal(JsonObject state, JsonObject entry)
    {
        var script =
            "import json\nfrom quests import apply_script_journal\n"
            + "state = json.loads("
            + JsonSerializer.Serialize(state.ToJsonString())
            + ")\n"
            + "entry = json.loads("
            + JsonSerializer.Serialize(entry.ToJsonString())
            + ")\n"
            + "fired = apply_script_journal(state, entry)\n"
            + "print(json.dumps({\"fired\": fired, \"state\": state}))\n";
        try
        {
            var text = BioPredictCli.RunPythonText(script, 60000);
            if (!string.IsNullOrWhiteSpace(text) && text[0] == '{')
            {
                var parsed = JsonNode.Parse(text) as JsonObject;
                if (parsed?["state"] is JsonObject next)
                {
                    state.Clear();
                    foreach (var pair in next)
                        state[pair.Key] = pair.Value?.DeepClone();
                }
                var fired = new List<string>();
                if (parsed?["fired"] is JsonArray names)
                {
                    foreach (var name in names)
                    {
                        var value = name?.GetValue<string>();
                        if (!string.IsNullOrWhiteSpace(value))
                            fired.Add(value);
                    }
                }
                return fired;
            }
        }
        catch (Exception ex) when (ex is InvalidOperationException or TimeoutException or DirectoryNotFoundException)
        {
            // Fall through to the index-only path when the quest host cannot start.
        }
        return ApplyJournalIndexed(state, entry);
    }

    public static List<string> ApplyJournalIndexed(JsonObject state, JsonObject entry)
    {
        var eventName = entry["event"]?.GetValue<string>() ?? "";
        var fired = new List<string>();
        if (string.IsNullOrWhiteSpace(eventName))
            return fired;
        var kept = state["keptLasts"] as JsonObject ?? new JsonObject();
        state["keptLasts"] = kept;
        if (kept[eventName] != null || eventName is "Docked" or "FSDJump")
            kept[eventName] = entry.DeepClone();
        if (state["chapters"] is not JsonArray chapters)
            return fired;
        foreach (var node in chapters)
        {
            if (node is not JsonObject chapter || chapter["active"]?.GetValue<bool>() != true)
                continue;
            if (chapter["handlers"] is not JsonArray handlers)
                continue;
            foreach (var handler in handlers)
            {
                if (handler?.GetValue<string>() == eventName)
                    fired.Add($"{chapter["id"]?.GetValue<string>()}.on_{eventName}");
            }
        }
        var pending = state["pendingHandlers"] as JsonArray ?? new JsonArray();
        foreach (var name in fired)
            pending.Add(name);
        state["pendingHandlers"] = pending;
        return fired;
    }

    static JsonObject ParseMessage(string text, string id)
    {
        var msg = new JsonObject
        {
            ["id"] = id,
            ["from"] = "",
            ["subject"] = "",
            ["body"] = "",
            ["read"] = false,
            ["actions"] = new JsonObject(),
        };
        var body = new List<string>();
        var firstBlank = true;
        foreach (var line in text.Replace("\r\n", "\n").Split('\n'))
        {
            if (line.StartsWith("from:", StringComparison.OrdinalIgnoreCase))
                msg["from"] = line["from:".Length..].Trim();
            else if (line.StartsWith("subject:", StringComparison.OrdinalIgnoreCase))
                msg["subject"] = line["subject:".Length..].Trim();
            else if (line.StartsWith("action:", StringComparison.OrdinalIgnoreCase))
            {
                var parts = line["action:".Length..].Split(':', 2, StringSplitOptions.TrimEntries);
                if (parts.Length == 2 && msg["actions"] is JsonObject actions)
                    actions[parts[0]] = parts[1];
            }
            else if (line == "" && firstBlank)
                firstBlank = false;
            else
                body.Add(line);
        }
        msg["body"] = string.Join('\n', body).Trim();
        return msg;
    }
}

public sealed class PlayCommsWindow : Window
{
    readonly ListBox _list = new();
    readonly TextBlock _body = new() { TextWrapping = TextWrapping.Wrap };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };
    readonly ComboBox _actions;
    readonly List<JsonObject> _messages = new();
    JsonObject? _state;

    public PlayCommsWindow()
    {
        Title = "Quest Comms";
        Width = 720;
        Height = 520;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var mark = new Button { Content = "Mark Read", MinWidth = 100 };
        mark.Click += (_, _) => MarkRead();
        _actions = new ComboBox { MinWidth = 160, PlaceholderText = "Reply" };
        var reply = new Button { Content = "Reply", MinWidth = 80 };
        reply.Click += (_, _) => Reply();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { _actions, reply, mark, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                _body.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 0),
                _list,
            },
        };
        _list.SelectionChanged += (_, _) => ShowSelected();
        Reload();
    }

    void Reload()
    {
        _state = QuestPlayStore.Load();
        _messages.Clear();
        var labels = new List<string>();
        if (_state?["messages"] is not JsonArray messages)
        {
            _list.ItemsSource = labels;
            _status.Text = "No play-state yet. Load a quest folder from Quest Dev.";
            return;
        }
        foreach (var node in messages)
        {
            if (node is not JsonObject msg)
                continue;
            _messages.Add(msg);
            var read = msg["read"]?.GetValue<bool>() == true ? "" : "● ";
            var subject = msg["subject"]?.GetValue<string>() ?? msg["id"]?.GetValue<string>() ?? "Message";
            labels.Add($"{read}{subject}");
        }
        _list.ItemsSource = labels;
        _status.Text = _state["note"]?.GetValue<string>() ?? $"{labels.Count} message(s).";
    }

    void ShowSelected()
    {
        if (_list.SelectedIndex < 0 || _list.SelectedIndex >= _messages.Count)
            return;
        var msg = _messages[_list.SelectedIndex];
        _body.Text = msg["body"]?.GetValue<string>() ?? "";
        var labels = new List<string>();
        if (msg["actions"] is JsonObject actions)
        {
            foreach (var pair in actions)
            {
                var label = pair.Value?.ToString() ?? pair.Key;
                labels.Add(pair.Key + ": " + label.Trim('"'));
            }
        }
        _actions.ItemsSource = labels;
        _actions.SelectedIndex = labels.Count > 0 ? 0 : -1;
    }

    void MarkRead()
    {
        if (_state == null || _list.SelectedIndex < 0 || _list.SelectedIndex >= _messages.Count)
            return;
        var id = _messages[_list.SelectedIndex]["id"]?.GetValue<string>() ?? "";
        if (string.IsNullOrWhiteSpace(id))
            return;
        if (!QuestPlayStore.MarkMessageRead(_state, id))
            _messages[_list.SelectedIndex]["read"] = true;
        QuestPlayStore.Save(_state);
        Reload();
    }

    void Reply()
    {
        if (_state == null || _list.SelectedIndex < 0 || _list.SelectedIndex >= _messages.Count)
            return;
        var chosen = _actions.SelectedItem as string ?? "";
        var split = chosen.Split(':', 2);
        var actionId = split[0].Trim();
        if (string.IsNullOrWhiteSpace(actionId))
            return;
        var id = _messages[_list.SelectedIndex]["id"]?.GetValue<string>() ?? "";
        if (!QuestPlayStore.ReplyMessage(_state, id, actionId))
        {
            _status.Text = "Reply was not run. Load the quest in Quest Dev so the chapter is active.";
            return;
        }
        QuestPlayStore.Save(_state);
        _status.Text = "Replied " + actionId;
        Reload();
    }
}

public sealed class PlayCommsCatalogWindow : Window
{
    readonly TextBox _fid = new() { PlaceholderText = "Commander FID (F…)" };
    readonly TextBlock _body = new() { TextWrapping = TextWrapping.Wrap };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public PlayCommsCatalogWindow()
    {
        Title = "Quest Catalog";
        Width = 640;
        Height = 480;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var refresh = new Button { Content = "Published Quests", MinWidth = 140 };
        refresh.Click += async (_, _) => await LoadPublishedAsync();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { refresh, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock { Text = "Local quest", FontWeight = FontWeight.SemiBold },
                        _body,
                        _fid,
                    },
                },
            },
        };
        var local = QuestPlayStore.Load();
        _body.Text = local == null
            ? "No side-loaded quest."
            : $"{local["title"]?.GetValue<string>()} ({local["publisher"]}|{local["id"]})";
        _status.Text = "Published quests are a GET. Offline and dry-run skip the network.";
    }

    async Task LoadPublishedAsync()
    {
        var (ok, status, json) = await RavenColonialClient.GetPublishedQuestsAsync(_fid.Text ?? "");
        _status.Text = status;
        if (!ok || string.IsNullOrWhiteSpace(json))
            return;
        try
        {
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
                return;
            var lines = new List<string>();
            foreach (var row in doc.RootElement.EnumerateArray())
            {
                var title = row.TryGetProperty("title", out var t) ? t.GetString() : null;
                var id = row.TryGetProperty("id", out var i) ? i.GetString() : null;
                lines.Add($"{title ?? id}");
            }
            _body.Text = lines.Count == 0 ? "No published quests." : string.Join("\n", lines);
        }
        catch (Exception ex)
        {
            _status.Text = "Could not read published quests: " + ex.Message;
        }
    }
}

public sealed class PlayDevWindow : Window
{
    readonly TextBox _folder = new() { PlaceholderText = "Folder containing quest.json" };
    readonly ComboBox _view = new();
    readonly TextBox _json = new() { AcceptsReturn = true, MinHeight = 220 };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };
    JsonObject? _state;

    public PlayDevWindow()
    {
        Title = "Quest Dev";
        Width = 760;
        Height = 560;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var browse = new Button { Content = "Browse", MinWidth = 80 };
        browse.Click += async (_, _) => await BrowseAsync();
        var load = new Button { Content = "Load Folder", MinWidth = 110 };
        load.Click += (_, _) => LoadFolder();
        var start = new Button { Content = "Start Chapter", MinWidth = 110 };
        start.Click += (_, _) => SetChapter(true);
        var stop = new Button { Content = "Stop Chapter", MinWidth = 110 };
        stop.Click += (_, _) => SetChapter(false);
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        _view.SelectionChanged += (_, _) => ShowView();
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { start, stop, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new StackPanel
                        {
                            Orientation = Orientation.Horizontal,
                            Spacing = 8,
                            Children = { _folder, browse, load },
                        },
                        _view,
                        _json,
                    },
                },
            },
        };
        _state = QuestPlayStore.Load();
        if (_state != null)
            FillViews();
        _status.Text = "Loads quest.json through the quest host. Chapter Lua runs.";
    }

    async Task BrowseAsync()
    {
        var top = TopLevel.GetTopLevel(this);
        if (top == null)
            return;
        var folders = await top.StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            AllowMultiple = false,
            Title = "Quest folder",
        });
        var folder = folders.Count > 0 ? folders[0].TryGetLocalPath() : null;
        if (!string.IsNullOrWhiteSpace(folder))
            _folder.Text = folder;
    }

    void LoadFolder()
    {
        try
        {
            _state = QuestPlayStore.SideLoad((_folder.Text ?? "").Trim());
            FillViews();
            var ran = _state["luaExecuted"]?.GetValue<bool>() == true ? "Lua executed." : "Lua was not executed.";
            _status.Text = $"Loaded {_state["title"]?.GetValue<string>()}. First chapter started. {ran}";
        }
        catch (Exception ex)
        {
            _status.Text = ex.Message;
        }
    }

    void FillViews()
    {
        var labels = new List<string> { "Objectives", "Messages" };
        if (_state?["chapters"] is JsonArray chapters)
        {
            foreach (var node in chapters)
            {
                if (node is JsonObject chapter)
                    labels.Add("Chapter: " + chapter["id"]?.GetValue<string>());
            }
        }
        _view.ItemsSource = labels;
        if (labels.Count > 0)
            _view.SelectedIndex = 0;
    }

    void ShowView()
    {
        if (_state == null || _view.SelectedItem is not string view)
            return;
        if (view == "Objectives")
            _json.Text = _state["objectives"]?.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) ?? "{}";
        else if (view == "Messages")
            _json.Text = _state["messages"]?.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) ?? "[]";
        else if (view.StartsWith("Chapter: ", StringComparison.Ordinal) && _state["chapters"] is JsonArray chapters)
        {
            var id = view["Chapter: ".Length..];
            foreach (var node in chapters)
            {
                if (node is JsonObject chapter && chapter["id"]?.GetValue<string>() == id)
                    _json.Text = chapter.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
            }
        }
    }

    void SetChapter(bool start)
    {
        if (_state?["chapters"] is not JsonArray chapters || _view.SelectedItem is not string view)
            return;
        if (!view.StartsWith("Chapter: ", StringComparison.Ordinal))
            return;
        var id = view["Chapter: ".Length..];
        foreach (var node in chapters)
        {
            if (node is not JsonObject chapter || chapter["id"]?.GetValue<string>() != id)
                continue;
            chapter["active"] = start;
            if (start)
            {
                chapter["start_time"] = DateTimeOffset.UtcNow.ToString("o");
                chapter["end_time"] = null;
            }
            else
            {
                chapter["end_time"] = DateTimeOffset.UtcNow.ToString("o");
            }
            QuestPlayStore.Save(_state);
            ShowView();
            _status.Text = start ? $"Started {id}." : $"Stopped {id}.";
        }
    }
}

public sealed class PlayJournalWindow : Window
{
    readonly TextBox _path = new() { PlaceholderText = "Journal log path" };
    readonly TextBox _fields = new() { PlaceholderText = "Match fields, comma separated" };
    readonly TextBox _fragment = new() { AcceptsReturn = true, IsReadOnly = true, MinHeight = 120 };
    readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap };

    public PlayJournalWindow()
    {
        Title = "Quest Journal Replay";
        Width = 680;
        Height = 360;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var run = new Button { Content = "Replay", MinWidth = 90 };
        run.Click += (_, _) => Replay();
        var draft = new Button { Content = "Draft Handler", MinWidth = 120 };
        draft.Click += (_, _) => Draft();
        var close = new Button { Content = "Close", MinWidth = 80 };
        close.Click += (_, _) => Close();
        Content = new DockPanel
        {
            Margin = new Avalonia.Thickness(12),
            Children =
            {
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 8,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Children = { draft, run, close },
                }.WithDock(Dock.Bottom),
                _status.WithDock(Dock.Bottom).WithMargin(0, 8, 0, 8),
                new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = "Replays the journal through the quest host, which runs chapter Lua. Pick an event to draft an on_ handler.",
                            TextWrapping = TextWrapping.Wrap,
                        },
                        _path,
                        _fields,
                        _fragment,
                    },
                },
            },
        };
    }

    void Replay()
    {
        var state = QuestPlayStore.Load();
        if (state == null)
        {
            _status.Text = "Load a quest in Quest Dev first.";
            return;
        }
        var file = (_path.Text ?? "").Trim();
        if (!File.Exists(file))
        {
            _status.Text = "Journal file not found.";
            return;
        }
        var fired = new List<string>();
        foreach (var line in File.ReadLines(file))
        {
            if (string.IsNullOrWhiteSpace(line))
                continue;
            try
            {
                if (JsonNode.Parse(line) is not JsonObject entry)
                    continue;
                fired.AddRange(QuestPlayStore.ApplyJournal(state, entry));
            }
            catch
            {
                // skip broken lines, same as the journal reader
            }
        }
        QuestPlayStore.Save(state);
        Draft();
        var sample = fired.Count == 0 ? "none" : string.Join(", ", fired.Distinct().Take(8));
        _status.Text = $"Replay stored kept events. Handlers run: {sample}.";
    }

    void Draft()
    {
        var file = (_path.Text ?? "").Trim();
        if (!File.Exists(file))
        {
            _status.Text = "Journal file not found.";
            return;
        }
        JsonObject? entry = null;
        foreach (var line in File.ReadLines(file))
        {
            if (string.IsNullOrWhiteSpace(line))
                continue;
            try
            {
                if (JsonNode.Parse(line) is JsonObject row && row["event"] != null)
                    entry = row;
            }
            catch
            {
                // skip broken lines
            }
        }
        if (entry == null)
        {
            _status.Text = "No journal event in that file.";
            return;
        }
        var names = (_fields.Text ?? "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var script =
            "import json\nfrom quests import journal_handler_fragment\nprint(journal_handler_fragment(json.loads("
            + JsonSerializer.Serialize(entry.ToJsonString())
            + "), json.loads("
            + JsonSerializer.Serialize(JsonSerializer.Serialize(names))
            + ")))\n";
        try
        {
            _fragment.Text = BioPredictCli.RunPythonText(script, 20000);
        }
        catch (Exception ex) when (ex is InvalidOperationException or TimeoutException or DirectoryNotFoundException)
        {
            _status.Text = ex.Message;
        }
    }
}
