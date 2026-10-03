#!/usr/bin/env python3
"""GNOME GlobalShortcuts — Bazzite replacement for a Windows hotkey grab.

Mutter delivers keys to the focused game before an X11 grab can see them.
``org.freedesktop.portal.GlobalShortcuts`` asks once, then the shell reports
the chord while Elite has focus. The on-screen chip stays in place either way.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

Callback = Callable[[], None]


def gtk_trigger(text: str) -> str:
    """Windows ``ALT F2`` or Linux ``Alt+F2`` to a GTK accelerator."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw.endswith("+"):
        raw = raw[:-1].strip() + " plus"
    elif raw.endswith("-"):
        raw = raw[:-1].strip() + " minus"
    raw = raw.replace("plus", " plus ").replace("minus", " minus ")
    tokens = [part for part in raw.replace("+", " ").replace("-", " ").split() if part]
    if not tokens:
        return ""
    mod_map = {
        "alt": "Alt",
        "ctrl": "Control",
        "control": "Control",
        "shift": "Shift",
        "super": "Super",
    }
    key_map = {
        "plus": "plus",
        "minus": "minus",
        "backspace": "BackSpace",
        "pause": "Pause",
    }
    mods: list[str] = []
    key = ""
    for token in tokens:
        name = mod_map.get(token.lower())
        if name is not None and not key:
            mods.append(f"<{name}>")
            continue
        key = key_map.get(token.lower(), token)
    if not key:
        return ""
    return "".join(mods) + key


def shortcut_id(label: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in (label or "chord"))
    return "chord-" + slug.strip("-")


class GlobalShortcutBridge:
    """One portal session. ``start`` returns False when the bus call fails."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop = None
        self._callbacks: dict[str, Callback] = {}
        self._session = ""
        self._last_fire: dict[str, float] = {}
        self._ready = threading.Event()
        self._ok = False

    def start(self, bindings: list[tuple[str, str, str, Callback]]) -> bool:
        """bindings: shortcut id, description, GTK trigger, callback."""
        usable = [row for row in bindings if row[0] and row[2] and row[3] is not None]
        if not usable:
            return False
        self._callbacks = {row[0]: row[3] for row in usable}
        self._specs = usable
        self._thread = threading.Thread(
            target=self._run,
            name="srvsurvey-global-shortcuts",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=8)
        return self._ok

    def stop(self) -> None:
        loop = self._loop
        if loop is not None:
            try:
                from gi.repository import GLib

                GLib.idle_add(loop.quit)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except Exception as exc:
            print(f"global shortcuts unavailable: {exc}", flush=True)
            self._ready.set()
            return
        self._gio = Gio
        self._glib = GLib
        self._loop = GLib.MainLoop()
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            sender = self._bus.get_unique_name()[1:].replace(".", "_")
            self._sender = sender
            self._proxy = Gio.DBusProxy.new_sync(
                self._bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.GlobalShortcuts",
                None,
            )
            self._bus.signal_subscribe(
                "org.freedesktop.portal.Desktop",
                "org.freedesktop.portal.GlobalShortcuts",
                "Activated",
                "/org/freedesktop/portal/desktop",
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_activated,
            )
            GLib.idle_add(self._create_session)
            self._loop.run()
        except Exception as exc:
            print(f"global shortcuts failed: {exc}", flush=True)
            self._ready.set()

    def _request_path(self, token: str) -> str:
        return f"/org/freedesktop/portal/desktop/request/{self._sender}/{token}"

    def _subscribe_response(self, token: str, done: Callable[[int, dict], None]) -> None:
        path = self._request_path(token)

        def _response(_conn, _sender, _path, _iface, _signal, params) -> None:
            response, results = params.unpack()
            done(int(response), results if isinstance(results, dict) else {})

        self._bus.signal_subscribe(
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Request",
            "Response",
            path,
            None,
            self._gio.DBusSignalFlags.NONE,
            _response,
        )

    def _create_session(self) -> bool:
        token = "srvsurveycreate"
        session_token = "srvsurveykeys"
        self._subscribe_response(token, self._on_session)
        options = {
            "handle_token": self._glib.Variant("s", token),
            "session_handle_token": self._glib.Variant("s", session_token),
        }
        try:
            self._proxy.call(
                "CreateSession",
                self._glib.Variant("(a{sv})", (options,)),
                self._gio.DBusCallFlags.NONE,
                30000,
                None,
                None,
                None,
            )
        except Exception as exc:
            print(f"global shortcuts session failed: {exc}", flush=True)
            self._ready.set()
            if self._loop is not None:
                self._loop.quit()
        return False

    def _on_session(self, response: int, results: dict) -> None:
        handle = results.get("session_handle") if response == 0 else None
        if not isinstance(handle, str) or not handle:
            print("global shortcuts session was not created", flush=True)
            self._ready.set()
            if self._loop is not None:
                self._loop.quit()
            return
        self._session = handle
        self._bind()

    def _bind(self) -> None:
        token = "srvsurveybind"
        shortcuts = []
        for sid, description, trigger, _callback in self._specs:
            shortcuts.append(
                (
                    sid,
                    {
                        "description": self._glib.Variant("s", description),
                        "preferred_trigger": self._glib.Variant("s", trigger),
                    },
                )
            )
        self._subscribe_response(token, self._on_bound)
        options = {"handle_token": self._glib.Variant("s", token)}
        try:
            self._proxy.call(
                "BindShortcuts",
                self._glib.Variant(
                    "(oa(sa{sv})sa{sv})",
                    (self._session, shortcuts, "", options),
                ),
                self._gio.DBusCallFlags.NONE,
                30000,
                None,
                None,
                None,
            )
        except Exception as exc:
            print(f"global shortcuts bind failed: {exc}", flush=True)
            self._ready.set()
            return
        self._ok = True
        self._ready.set()
        print(
            "global shortcuts requested. Confirm the GNOME binding dialog if it is shown.",
            flush=True,
        )

    def _on_bound(self, response: int, _results: dict) -> None:
        if response == 0:
            self._ok = True
            print(
                "global shortcuts armed. Confirm the GNOME binding dialog if it is shown.",
                flush=True,
            )
        elif response == 1:
            print("global shortcuts cancelled. The on-screen chip still toggles the overlay.", flush=True)
        else:
            print(f"global shortcuts bind response {response}", flush=True)
        self._ready.set()

    def _on_activated(self, _conn, _sender, _path, _iface, _signal, params) -> None:
        try:
            session, shortcut_id, _timestamp, _options = params.unpack()
        except (ValueError, TypeError):
            return
        if self._session and session != self._session:
            return
        now = time.monotonic()
        if now - self._last_fire.get(shortcut_id, 0.0) < 0.35:
            return
        self._last_fire[shortcut_id] = now
        callback = self._callbacks.get(shortcut_id)
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            print(f"global shortcut {shortcut_id} failed: {exc}", flush=True)
