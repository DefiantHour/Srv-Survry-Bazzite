#!/usr/bin/env python3
"""One-time GNOME screen grant for FSS pixel watch.

``org.gnome.Shell.Screenshot`` is denied on this session. ScreenCast can
keep a restore token after the user allows a monitor once. Later frames
use that token and PipeWire. This module never sends input.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

SOURCE_MONITOR = 1
CURSOR_HIDDEN = 1
PERSIST_UNTIL_REVOKED = 2


def select_source_options(restore_token: str | None) -> dict[str, tuple[str, object]]:
    """Portal SelectSources fields. The token is omitted until one exists."""
    options: dict[str, tuple[str, object]] = {
        "types": ("u", SOURCE_MONITOR),
        "multiple": ("b", False),
        "cursor_mode": ("u", CURSOR_HIDDEN),
        "persist_mode": ("u", PERSIST_UNTIL_REVOKED),
    }
    token = (restore_token or "").strip()
    if token:
        options["restore_token"] = ("s", token)
    return options


def token_path(config_dir: Path | None = None) -> Path:
    if config_dir is not None:
        base = Path(config_dir)
    else:
        raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
        base = Path(raw) if raw else Path.home() / ".config"
        base = base / "srvsurvey"
    return base / "screencast-restore-token"


def read_restore_token(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_restore_token(path: Path, token: str) -> None:
    text = (token or "").strip()
    if not text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def frame_pipeline(fd: int, node_id: int, dest: str) -> list[str]:
    """One PNG from the portal PipeWire node. ``fd`` must stay open."""
    return [
        "gst-launch-1.0",
        "-e",
        "pipewiresrc",
        f"fd={int(fd)}",
        f"target-object={int(node_id)}",
        "num-buffers=1",
        "!",
        "videoconvert",
        "!",
        "pngenc",
        "!",
        "filesink",
        f"location={dest}",
    ]


class ScreenCastGrabber:
    """Background grant. ``capture`` waits only after the session is ready."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started = False
        self.ready = False
        self.reason = "screen cast not started"
        self._fd: int | None = None
        self._node = 0
        self._session = ""
        self._loop = None
        self._proxy = None
        self._gio = None
        self._glib = None
        self._bus = None
        self._sender = ""

    def ensure(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self.reason = "screen cast grant in progress"
            self._thread = threading.Thread(
                target=self._run,
                name="srvsurvey-screencast",
                daemon=True,
            )
            self._thread.start()

    def capture(self, dest: str) -> tuple[bool, str]:
        if not self.ready or self._loop is None or self._glib is None:
            return False, self.reason
        box: dict[str, tuple[bool, str]] = {}
        done = threading.Event()

        def _work() -> bool:
            try:
                box["result"] = self._capture_now(dest)
            except Exception as exc:  # noqa: BLE001
                box["result"] = (False, f"screen cast frame failed: {exc}")
            done.set()
            return False

        self._glib.idle_add(_work)
        if not done.wait(6):
            return False, "screen cast frame timed out"
        return box.get("result", (False, "screen cast frame failed"))

    def _run(self) -> None:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except Exception as exc:  # noqa: BLE001
            self.reason = f"screen cast unavailable: {exc}"
            return
        self._gio = Gio
        self._glib = GLib
        self._loop = GLib.MainLoop()
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._sender = self._bus.get_unique_name()[1:].replace(".", "_")
            self._proxy = Gio.DBusProxy.new_sync(
                self._bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.ScreenCast",
                None,
            )
            GLib.idle_add(self._create_session)
            self._loop.run()
        except Exception as exc:  # noqa: BLE001
            self.reason = f"screen cast failed: {exc}"

    def _request_path(self, token: str) -> str:
        return f"/org/freedesktop/portal/desktop/request/{self._sender}/{token}"

    def _subscribe(self, token: str, done) -> None:
        def _response(_conn, _sender, _path, _iface, _signal, params) -> None:
            response, results = params.unpack()
            done(int(response), results if isinstance(results, dict) else {})

        self._bus.signal_subscribe(
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Request",
            "Response",
            self._request_path(token),
            None,
            self._gio.DBusSignalFlags.NONE,
            _response,
        )

    def _create_session(self) -> bool:
        token = "srvsurveycast"
        self._subscribe(token, self._on_session)
        options = {
            "handle_token": self._glib.Variant("s", token),
            "session_handle_token": self._glib.Variant("s", "srvsurveycastsession"),
        }
        self._proxy.call(
            "CreateSession",
            self._glib.Variant("(a{sv})", (options,)),
            self._gio.DBusCallFlags.NONE,
            30000,
            None,
            None,
            None,
        )
        print(
            "FSS screen cast requested. Confirm the GNOME share dialog if it is shown.",
            flush=True,
        )
        return False

    def _on_session(self, response: int, results: dict) -> None:
        handle = results.get("session_handle") if response == 0 else None
        if not isinstance(handle, str) or not handle:
            self.reason = "screen cast session was not created"
            self._quit()
            return
        self._session = handle
        self._select_sources()

    def _select_sources(self) -> None:
        token = "srvsurveysources"
        self._subscribe(token, self._on_sources)
        stored = read_restore_token(token_path(self._config_dir))
        raw = select_source_options(stored or None)
        options = {
            "handle_token": self._glib.Variant("s", token),
        }
        for key, (kind, value) in raw.items():
            options[key] = self._glib.Variant(kind, value)
        self._proxy.call(
            "SelectSources",
            self._glib.Variant("(oa{sv})", (self._session, options)),
            self._gio.DBusCallFlags.NONE,
            30000,
            None,
            None,
            None,
        )

    def _on_sources(self, response: int, _results: dict) -> None:
        if response != 0:
            self.reason = "screen cast source selection was cancelled" if response == 1 else f"screen cast sources {response}"
            self._quit()
            return
        self._start()

    def _start(self) -> None:
        token = "srvsurveystart"
        self._subscribe(token, self._on_start)
        options = {"handle_token": self._glib.Variant("s", token)}
        self._proxy.call(
            "Start",
            self._glib.Variant("(osa{sv})", (self._session, "", options)),
            self._gio.DBusCallFlags.NONE,
            120000,
            None,
            None,
            None,
        )

    def _on_start(self, response: int, results: dict) -> None:
        if response == 1:
            self.reason = "screen cast cancelled"
            self._quit()
            return
        if response != 0:
            self.reason = f"screen cast start {response}"
            self._quit()
            return
        streams = results.get("streams") or []
        if streams:
            node = streams[0][0] if isinstance(streams[0], (list, tuple)) else 0
            try:
                self._node = int(node)
            except (TypeError, ValueError):
                self._node = 0
        restored = results.get("restore_token")
        if isinstance(restored, str) and restored.strip():
            write_restore_token(token_path(self._config_dir), restored)
        self.ready = True
        self.reason = "screen cast ready"
        print("FSS screen cast ready.", flush=True)

    def _quit(self) -> None:
        if self._loop is not None:
            self._loop.quit()

    def _capture_now(self, dest: str) -> tuple[bool, str]:
        if self._fd is None:
            result, fd_list = self._proxy.call_with_unix_fd_list_sync(
                "OpenPipeWireRemote",
                self._glib.Variant("(oa{sv})", (self._session, {})),
                self._gio.DBusCallFlags.NONE,
                10000,
                None,
                None,
            )
            index = int(result.unpack()[0])
            borrowed = fd_list.get(index)
            self._fd = os.dup(borrowed)
        cmd = frame_pipeline(self._fd, self._node, dest)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=5,
            check=False,
            pass_fds=(self._fd,),
        )
        if proc.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) == 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[-160:]
            return False, f"screen cast frame failed: {err or proc.returncode}"
        return True, "screencast"


_shared: ScreenCastGrabber | None = None
_shared_lock = threading.Lock()


def shared_grabber() -> ScreenCastGrabber:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = ScreenCastGrabber()
        return _shared
