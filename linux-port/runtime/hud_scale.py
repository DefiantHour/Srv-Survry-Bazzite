"""Shared HUD scale.

Windows plotters are drawn at 8–12px, then shown 1:1. On a 1440p ultrawide
that type is too small to read. Plotters supersample by AA and keep
READABILITY in the bitmap that gets mapped, so the text and the box grow
together.
"""

from __future__ import annotations

# Supersample factor. The presented bitmap is the draw buffer divided by this.
AA = 2
# Windows body type is 11px. 5/2 puts that line at 28px, the same size as
# font_size in the user settings, and the card grows by the same factor.
READABILITY = 2.5
SCALE = 5
