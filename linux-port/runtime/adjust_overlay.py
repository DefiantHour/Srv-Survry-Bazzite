#!/usr/bin/env python3
"""GTK adjust-overlays dialog — Windows FormAdjustOverlay.

Edits one plotter at a time: horizontal, x, vertical, y, optional opacity.
Accept keeps the user override file. Cancel restores the snapshot taken
when the dialog opened. The spec plotters.json in the repo is not rewritten.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from plot_pos import (
    plotter_anchors,
    plotter_opacity,
    reset_plotter_anchor,
    restore_user_anchors,
    set_plotter_anchor,
    snapshot_user_anchors,
)

_HORIZ = (("Left", "left"), ("Center", "center"), ("Right", "right"), ("Screen", "os"))
_VERT = (("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom"), ("Screen", "os"))


def open_adjust_overlay(parent: Gtk.Window) -> str:
    names = sorted(plotter_anchors())
    if not names:
        return "No plotters found in plotters.json"
    backup = snapshot_user_anchors()
    accepted = {"ok": False}
    changing = {"on": False}

    dialog = Gtk.Dialog(title="Adjust Overlays", transient_for=parent, modal=True)
    dialog.add_button("Reset", Gtk.ResponseType.REJECT)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dialog.add_button("Accept", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_border_width(12)

    combo = Gtk.ComboBoxText()
    for name in names:
        combo.append_text(name)
    box.pack_start(combo, False, False, 0)

    horiz_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    vert_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    box.pack_start(horiz_box, False, False, 0)
    box.pack_start(vert_box, False, False, 0)
    horiz_buttons: dict[str, Gtk.RadioButton] = {}
    vert_buttons: dict[str, Gtk.RadioButton] = {}
    previous_h: Gtk.RadioButton | None = None
    previous_v: Gtk.RadioButton | None = None
    for label, key in _HORIZ:
        button = Gtk.RadioButton.new_with_label_from_widget(previous_h, label)
        previous_h = button
        horiz_buttons[key] = button
        horiz_box.pack_start(button, False, False, 0)
    for label, key in _VERT:
        button = Gtk.RadioButton.new_with_label_from_widget(previous_v, label)
        previous_v = button
        vert_buttons[key] = button
        vert_box.pack_start(button, False, False, 0)

    spins = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    box.pack_start(spins, False, False, 0)
    num_x = Gtk.SpinButton.new_with_range(-4000, 4000, 1)
    num_y = Gtk.SpinButton.new_with_range(-4000, 4000, 1)
    spins.pack_start(Gtk.Label(label="X"), False, False, 0)
    spins.pack_start(num_x, False, False, 0)
    spins.pack_start(Gtk.Label(label="Y"), False, False, 0)
    spins.pack_start(num_y, False, False, 0)

    opacity_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    box.pack_start(opacity_row, False, False, 0)
    check_opacity = Gtk.CheckButton(label="Custom opacity")
    num_opacity = Gtk.SpinButton.new_with_range(0, 100, 1)
    num_opacity.set_sensitive(False)
    opacity_row.pack_start(check_opacity, False, False, 0)
    opacity_row.pack_start(num_opacity, False, False, 0)
    opacity_row.pack_start(Gtk.Label(label="%"), False, False, 0)

    def selected() -> str:
        return combo.get_active_text() or ""

    def load_current() -> None:
        name = selected()
        anchor = plotter_anchors().get(name)
        if anchor is None:
            return
        changing["on"] = True
        horizontal, hx, vertical, hy = anchor
        if horizontal in horiz_buttons:
            horiz_buttons[horizontal].set_active(True)
        if vertical in vert_buttons:
            vert_buttons[vertical].set_active(True)
        num_x.set_value(hx)
        num_y.set_value(hy)
        custom = plotter_opacity(name)
        check_opacity.set_active(custom is not None)
        num_opacity.set_sensitive(custom is not None)
        num_opacity.set_value((custom if custom is not None else 1.0) * 100)
        changing["on"] = False

    def write_current() -> None:
        if changing["on"]:
            return
        name = selected()
        if not name:
            return
        horizontal = next(key for key, button in horiz_buttons.items() if button.get_active())
        vertical = next(key for key, button in vert_buttons.items() if button.get_active())
        opacity = (num_opacity.get_value() / 100.0) if check_opacity.get_active() else None
        set_plotter_anchor(
            name,
            horizontal,
            int(num_x.get_value()),
            vertical,
            int(num_y.get_value()),
            opacity,
        )

    def on_opacity_toggled(_button: Gtk.CheckButton) -> None:
        num_opacity.set_sensitive(check_opacity.get_active())
        write_current()

    combo.connect("changed", lambda _combo: load_current())
    for button in list(horiz_buttons.values()) + list(vert_buttons.values()):
        button.connect("toggled", lambda _button: write_current())
    num_x.connect("value-changed", lambda _spin: write_current())
    num_y.connect("value-changed", lambda _spin: write_current())
    num_opacity.connect("value-changed", lambda _spin: write_current())
    check_opacity.connect("toggled", on_opacity_toggled)

    combo.set_active(0)
    dialog.show_all()
    while True:
        response = dialog.run()
        if response == Gtk.ResponseType.REJECT:
            name = selected()
            if name:
                reset_plotter_anchor(name)
                load_current()
            continue
        accepted["ok"] = response == Gtk.ResponseType.OK
        break
    dialog.destroy()
    if not accepted["ok"]:
        restore_user_anchors(backup)
        return "Adjust overlays cancelled. Positions restored."
    return "Adjust overlays saved."
