#!/usr/bin/env python3
"""Geometry checks for the overlay presenter. Does not open a display."""

import unittest

from presenter import PresenterMode, Rect, layout_overlay, size_change_requires_remap


GAME = Rect(80, 80, 720, 480)
PANEL = Rect(250, 160, 220, 160)


class LayoutOverlayTests(unittest.TestCase):
    def test_session_uses_one_click_through_window_per_panel(self):
        placed = layout_overlay(PresenterMode.SESSION_X11, GAME, [PANEL])
        self.assertEqual(len(placed), 1)
        window = placed[0]
        self.assertEqual(window.window, Rect(80 + 250, 80 + 160, 220, 160))
        self.assertTrue(window.click_through)
        self.assertFalse(window.gamescope_overlay)
        self.assertEqual(len(window.blits), 1)
        blit = window.blits[0]
        self.assertEqual((blit.dst_x, blit.dst_y), (0, 0))
        self.assertEqual((blit.src_x, blit.src_y, blit.width, blit.height), (0, 0, 220, 160))

    def test_session_makes_one_window_per_panel(self):
        second = Rect(10, 10, 40, 30)
        placed = layout_overlay(PresenterMode.SESSION_X11, GAME, [PANEL, second])
        self.assertEqual(len(placed), 2)
        self.assertEqual(placed[1].window, Rect(80 + 10, 80 + 10, 40, 30))
        self.assertTrue(placed[1].click_through)

    def test_gamescope_window_is_only_the_panel(self):
        placed = layout_overlay(PresenterMode.GAMESCOPE, GAME, [PANEL])
        self.assertEqual(len(placed), 1)
        window = placed[0]
        self.assertEqual(window.window, Rect(80 + 250, 80 + 160, 220, 160))
        self.assertTrue(window.click_through)
        self.assertTrue(window.gamescope_overlay)
        blit = window.blits[0]
        self.assertEqual((blit.dst_x, blit.dst_y), (0, 0))
        self.assertEqual((blit.width, blit.height), (220, 160))

    def test_gamescope_makes_one_window_per_panel(self):
        second = Rect(10, 10, 40, 30)
        placed = layout_overlay(PresenterMode.GAMESCOPE, GAME, [PANEL, second])
        self.assertEqual(len(placed), 2)
        self.assertEqual(placed[1].window, Rect(80 + 10, 80 + 10, 40, 30))

    def test_panel_past_the_edge_is_clipped(self):
        hanging = Rect(700, 460, 80, 40)
        placed = layout_overlay(PresenterMode.GAMESCOPE, GAME, [hanging])
        self.assertEqual(placed[0].window, Rect(80 + 700, 80 + 460, 20, 20))
        blit = placed[0].blits[0]
        self.assertEqual((blit.src_x, blit.src_y, blit.width, blit.height), (0, 0, 20, 20))

    def test_panel_fully_outside_the_game_is_dropped(self):
        outside = Rect(800, 10, 20, 20)
        self.assertEqual(layout_overlay(PresenterMode.GAMESCOPE, GAME, [outside]), [])
        self.assertEqual(layout_overlay(PresenterMode.SESSION_X11, GAME, [outside]), [])

    def test_desktop_fallback_has_no_window(self):
        self.assertEqual(layout_overlay(PresenterMode.DESKTOP_FALLBACK, GAME, [PANEL]), [])

    def test_session_and_gamescope_share_panel_geometry(self):
        session = layout_overlay(PresenterMode.SESSION_X11, GAME, [PANEL])
        gamescope = layout_overlay(PresenterMode.GAMESCOPE, GAME, [PANEL])
        self.assertEqual(session[0].window, gamescope[0].window)
        self.assertTrue(session[0].click_through)
        self.assertTrue(gamescope[0].click_through)
        blocked = layout_overlay(
            PresenterMode.GAMESCOPE, GAME, [PANEL], pass_clicks=False,
        )
        self.assertFalse(blocked[0].click_through)

    def test_size_change_requires_a_new_window(self):
        pulse = Rect(1088, 1880, 32, 32)
        sysstatus = Rect(1088, 1826, 170, 50)
        colony = Rect(4262, 488, 250, 205)
        self.assertTrue(size_change_requires_remap(pulse, sysstatus))
        self.assertTrue(size_change_requires_remap(pulse, colony))
        self.assertFalse(size_change_requires_remap(sysstatus, Rect(1100, 1826, 170, 50)))
        self.assertTrue(size_change_requires_remap(None, pulse))


if __name__ == "__main__":
    unittest.main()
