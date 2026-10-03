#!/usr/bin/env python3
"""PlotPriorScans — 1-1 Linux port of SrvSurvey/plotters/PlotPriorScans.cs.

Uses Canonn SystemPoi when available; stubs empty offline (SRVSURVEY_CANONN_OFFLINE).
No full CodexRef reward table — uses Canonn english_name and optional reward map.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from dataclasses import dataclass, field
from pathlib import Path

from body_value import format_credits
from canonn import CodexPoi, SystemPoi, get_system_poi, has_local_bio_signals
from companion import StatusSnapshot
from game_settings import GameSettings
from geo import draw_bearing_to, get_bearing, get_distance, meters_to_string, relative_bearing
from journal import CommanderLocation, SurveyState

ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
ORANGE_DARK = (160, 70, 0, 255)
CYAN = (84, 223, 237, 255)
CYAN_DARK = (20, 80, 90, 255)
STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)

TITLE_PX = 9
BODY_PX = 10
PAD = 8
DEFAULT_WIDTH = 308
HIGHLIGHT_DISTANCE = 150

_HEADER = "Tracking {0} signals from Canonn:"
_FOOTER = "(Locations may not be that close to signals)"
_NO_MORE = "No un-scanned signals meet criteria"


@dataclass
class PriorTracker:
    latitude: float
    longitude: float
    distance: float = 0.0
    bearing: float = 0.0

    def calc(
        self,
        lat: float,
        lon: float,
        radius_m: float,
    ) -> None:
        self.distance = get_distance(lat, lon, self.latitude, self.longitude, radius_m)
        self.bearing = get_bearing(lat, lon, self.latitude, self.longitude)


@dataclass
class PriorSignal:
    entry_id: int
    display_name: str
    reward: int
    credits: str
    trackers: list[PriorTracker] = field(default_factory=list)


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    paths = (
        (
            "/usr/share/fonts/urw-base35/URWGothic-Demi.otf"
            if bold
            else "/usr/share/fonts/urw-base35/URWGothic-Book.otf"
        ),
        (
            "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Bold.otf"
            if bold
            else "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Regular.otf"
        ),
    )
    for path in paths:
        if Path(path).is_file():
            return ImageFont.truetype(path, size * SCALE)
    return ImageFont.load_default()


def _s(n: float) -> int:
    return int(round(n * SCALE))


def _tw(draw, text: str, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return int(b[2] - b[0])


def _background(draw, w: int, h: int) -> None:
    draw.rectangle((0, 0, w - 1, h - 1), fill=BLACK)
    step = _s(3)
    for y in range(0, h, step):
        draw.line((0, y, w - 1, y), fill=STRIPE)
    for y, col in ((_s(3), ORANGE_DIM), (_s(4), ORANGE), (_s(5), ORANGE_DIM)):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    for y, col in (
        (h - _s(5), ORANGE_DIM),
        (h - _s(4), ORANGE),
        (h - _s(3), ORANGE_DIM),
    ):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    draw.rectangle((0, 0, w - 1, h - 1), outline=ORANGE, width=max(1, SCALE // 2))


def _body_short(system: str | None, body: str | None) -> str | None:
    if not body:
        return None
    if system and body.startswith(system):
        return body[len(system) :].strip() or body
    return body


def prior_scans_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    survey: SurveyState,
    location: CommanderLocation,
    poi: SystemPoi | None,
) -> bool:
    """Match PlotPriorScans.allowed (Guardian / Human / Station collisions omitted)."""
    if not game.useExternalData:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    if not game.autoLoadPriorScans:
        return False
    if status is not None and status.docked:
        return False
    short = _body_short(survey.system or location.system, location.body or (status.body_name if status else None))
    if not has_local_bio_signals(poi, short, hide_own=game.hideMyOwnCanonnSignals):
        return False
    # Surface / near-body modes: require lat/long when Status is present
    if status is not None and not status.has_lat_long:
        return False
    return True


def build_prior_signals(
    poi: SystemPoi | None,
    *,
    body_short: str | None,
    status: StatusSnapshot | None,
    game: GameSettings,
    reward_by_entry: dict[int, int] | None = None,
) -> list[PriorSignal]:
    """Group Canonn Biology POI rows into PriorSignal list (closest trackers first)."""
    if poi is None or not body_short:
        return []
    rewards = reward_by_entry or {}
    radius = (
        float(status.planet_radius)
        if status is not None and status.planet_radius
        else 0.0
    )
    here_lat = status.latitude if status is not None else None
    here_lon = status.longitude if status is not None else None

    by_id: dict[int, PriorSignal] = {}
    for row in poi.codex:
        if not _poi_row_usable(row, body_short, game):
            continue
        assert row.entry_id is not None and row.latitude is not None and row.longitude is not None
        reward = int(rewards.get(row.entry_id, 0))
        if game.skipPriorScansLowValue and reward and reward < game.skipPriorScansLowValueAmount:
            continue
        if game.hideMyOwnCanonnSignals and row.scanned:
            continue
        signal = by_id.get(row.entry_id)
        if signal is None:
            name = row.english_name or f"Entry {row.entry_id}"
            signal = PriorSignal(
                entry_id=row.entry_id,
                display_name=name,
                reward=reward,
                credits=format_credits(reward) if reward else "",
            )
            by_id[row.entry_id] = signal
        tracker = PriorTracker(latitude=row.latitude, longitude=row.longitude)
        if here_lat is not None and here_lon is not None and radius > 0:
            tracker.calc(here_lat, here_lon, radius)
        signal.trackers.append(tracker)

    signals = list(by_id.values())
    signals.sort(key=lambda s: s.reward, reverse=True)
    for signal in signals:
        signal.trackers.sort(key=lambda t: t.distance)
        # Drop near-duplicates within highlight distance
        cleaned: list[PriorTracker] = []
        for td in signal.trackers:
            if cleaned and abs(td.distance - cleaned[-1].distance) < HIGHLIGHT_DISTANCE:
                continue
            cleaned.append(td)
        signal.trackers = cleaned
    return signals


def _poi_row_usable(row: CodexPoi, body_short: str, game: GameSettings) -> bool:
    if row.hud_category != "Biology":
        return False
    if row.latitude is None or row.longitude is None or row.entry_id is None:
        return False
    body = (row.body or "").replace(" ", "")
    if body != body_short.replace(" ", ""):
        return False
    if game.hideMyOwnCanonnSignals and row.scanned:
        return False
    return True


def render_prior_scans_bitmap(
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    *,
    game: GameSettings | None = None,
    poi: SystemPoi | None = None,
    force_show: bool = False,
    max_width: int = DEFAULT_WIDTH,
) -> tuple[bytes, int, int] | None:
    """Draw PlotPriorScans. Returns None when not allowed / nothing to show."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    system = survey.system or location.system
    cmdr = location.commander or ""
    if poi is None and system:
        poi = get_system_poi(system, cmdr)
    if not force_show and not prior_scans_allowed(gs, status, survey, location, poi):
        return None

    body_name = location.body or (status.body_name if status else None)
    short = _body_short(system, body_name)
    signals = build_prior_signals(poi, body_short=short, status=status, game=gs)

    font_small = _font(TITLE_PX)
    font_body = _font(BODY_PX)
    width = _s(DEFAULT_WIDTH)
    width = min(width, _s(max_width))

    header = _HEADER.format(len(signals))
    if gs.skipPriorScansLowValue:
        header += f" (> {format_credits(gs.skipPriorScansLowValueAmount)})"

    row_h = _s(16)
    # Estimate height
    height = _s(12) + row_h
    if not signals:
        height += row_h * 2
    else:
        for sig in signals:
            height += row_h
            rows = max(1, (len(sig.trackers) + 2) // 3)
            height += rows * row_h
    height += row_h + _s(14)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    draw.text((_s(PAD), y), header, font=font_small, fill=ORANGE)
    y += row_h + _s(4)

    if not signals:
        draw.text((_s(16), y), _NO_MORE, font=font_body, fill=ORANGE_DIM)
        y += row_h * 2
    else:
        heading = float(status.heading) if status is not None and status.heading is not None else 0.0
        for sig in signals:
            # Title + credits
            title_col = ORANGE
            if sig.credits:
                tw = _tw(draw, sig.credits, font_body)
                draw.text(
                    (width - _s(PAD) - tw, y),
                    sig.credits,
                    font=font_body,
                    fill=title_col,
                )
            draw.text((_s(6), y), sig.display_name, font=font_body, fill=title_col)
            y += row_h
            # Bearing chips
            x = _s(80)
            bearing_w = _s(75)
            for td in sig.trackers:
                if x + bearing_w > width - _s(8):
                    x = _s(80)
                    y += row_h
                deg = relative_bearing(td.bearing, heading)
                close = td.distance < HIGHLIGHT_DISTANCE
                col = CYAN if close else ORANGE
                pen = CYAN if close else ORANGE
                dist_txt = meters_to_string(td.distance) if td.distance else "—"
                draw_bearing_to(
                    draw,
                    x,
                    y + _s(2),
                    _s(5),
                    deg,
                    outline=pen,
                    msg=dist_txt,
                    font=font_small,
                    msg_fill=col,
                )
                x += bearing_w
            y += row_h

    draw.text((_s(PAD), y), _FOOTER, font=font_small, fill=ORANGE_DIM)
    y += row_h + _s(8)

    used = min(height, y + _s(6))
    if used < height:
        img = img.crop((0, 0, width, used))
        height = used
        draw = ImageDraw.Draw(img)
        for yy, col in (
            (height - _s(5), ORANGE_DIM),
            (height - _s(4), ORANGE),
            (height - _s(3), ORANGE_DIM),
        ):
            draw.line((_s(2), yy, width - _s(4), yy), fill=col)
        draw.rectangle(
            (0, 0, width - 1, height - 1),
            outline=ORANGE,
            width=max(1, SCALE // 2),
        )

    if SCALE != 1:
        img = img.resize((width // AA, height // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h
