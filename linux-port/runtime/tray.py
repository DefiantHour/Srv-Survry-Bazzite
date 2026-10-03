#!/usr/bin/env python3
"""Optional StatusNotifier / AppIndicator tray for SrvSurvey Linux.

GNOME often needs an extension for tray icons. If the libraries are missing
or the session rejects the item, this module is a no-op.
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class TrayController:
    """Best-effort tray with Show/Hide + Settings + Quit."""

    def __init__(
        self,
        *,
        on_toggle: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self.on_toggle = on_toggle
        self.on_settings = on_settings
        self.on_quit = on_quit
        self._ok = False
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return self._ok

    def start(self) -> bool:
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk  # noqa: F401
        except Exception:
            return False

        indicator = None
        try:
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3 as appindicator

            indicator = appindicator.Indicator.new(
                "srvsurvey-linux",
                "applications-games",
                appindicator.IndicatorCategory.APPLICATION_STATUS,
            )
            indicator.set_status(appindicator.IndicatorStatus.ACTIVE)
        except Exception:
            try:
                from gi.repository import Gtk

                # Deprecated but still present on some desktops.
                status = Gtk.StatusIcon.new_from_icon_name("applications-games")
                status.set_tooltip_text("SrvSurvey Linux")
                menu = self._build_menu(Gtk)

                def _popup(_icon, button, activate_time):
                    menu.popup(None, None, None, None, button, activate_time)

                status.connect("popup-menu", _popup)
                status.connect("activate", lambda *_: self._safe(self.on_toggle))
                indicator = status
            except Exception:
                return False

        if indicator is None:
            return False

        from gi.repository import Gtk

        if hasattr(indicator, "set_menu"):
            indicator.set_menu(self._build_menu(Gtk))

        self._ok = True

        def _run() -> None:
            Gtk.main()

        self._thread = threading.Thread(target=_run, name="srvsurvey-tray", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self._ok:
            return
        try:
            from gi.repository import Gtk

            Gtk.main_quit()
        except Exception:
            pass

    def _build_menu(self, Gtk):  # type: ignore[no-untyped-def]
        menu = Gtk.Menu()
        toggle = Gtk.MenuItem(label="Toggle Overlay")
        toggle.connect("activate", lambda *_: self._safe(self.on_toggle))
        menu.append(toggle)
        settings = Gtk.MenuItem(label="Settings")
        settings.connect("activate", lambda *_: self._safe(self.on_settings))
        menu.append(settings)
        quit_item = Gtk.MenuItem(label="Quit Present")
        quit_item.connect("activate", lambda *_: self._safe(self.on_quit))
        menu.append(quit_item)
        menu.show_all()
        return menu

    @staticmethod
    def _safe(callback: Callable[[], None] | None) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception:
            pass
