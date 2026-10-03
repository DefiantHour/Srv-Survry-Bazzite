#!/usr/bin/env python3
"""Elite screenshot convert + banner embed (Windows Main.processScreenshot).

When ``processScreenshots`` is on, new images in ``screenshotSourceFolder``
are copied into ``screenshotTargetFolder/<system>/`` as PNG. Optional banner
text (body / system / commander / time, plus lat-long when Status has them)
is drawn in ``screenshotBannerColor`` with URW Gothic stand-ins for Century
Gothic. Offline-only — no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from game_settings import GameSettings
from theme import DEFAULT_BANNER, parse_hex

# Windows GameColors.fontScreenshotBannerBig / Small (Century Gothic 14B / 10).
_BANNER_BIG_PX = 14
_BANNER_SMALL_PX = 10

_IMAGE_SUFFIXES = (".png", ".bmp", ".jpg", ".jpeg")

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


@dataclass(frozen=True)
class ScreenshotContext:
    """Location / Status snapshot used when naming and annotating a shot."""

    system: str = "unknown"
    body: str = "unknown"
    commander: str = ""
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    heading: float | None = None
    has_lat_long: bool = False
    # Wall-clock when the shot was taken (file mtime or journal timestamp).
    taken_at: datetime | None = None


def safe_filename(name: str) -> str:
    """Windows Util.safeFilename — replace illegal path characters with '-'."""
    return _ILLEGAL.sub("-", name or "")


def _load_banner_font(size: int, *, bold: bool = False):
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
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for path in paths:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _parse_banner_rgb(game: GameSettings) -> tuple[int, int, int]:
    rgba = parse_hex(getattr(game, "screenshotBannerColor", None), DEFAULT_BANNER)
    return (rgba[0], rgba[1], rgba[2])


def _format_banner_time(taken: datetime, *, local_time: bool) -> str:
    if local_time:
        local = taken.astimezone() if taken.tzinfo else taken
        return local.strftime("%Y-%m-%d %H:%M:%S")
    utc = taken.astimezone(timezone.utc) if taken.tzinfo else taken.replace(tzinfo=timezone.utc)
    return utc.strftime("%Y-%m-%d %H:%M:%SZ")


def build_banner_lines(
    ctx: ScreenshotContext,
    game: GameSettings,
    *,
    extra: str = "",
) -> tuple[str, str]:
    """Return (big_line, small_block) matching Windows addBannerToScreenshot."""
    system = (ctx.system or "unknown").strip() or "unknown"
    body = (ctx.body or "unknown").strip() or "unknown"
    cmdr = (ctx.commander or "").strip()
    taken = ctx.taken_at or datetime.now(timezone.utc)
    stamp = _format_banner_time(taken, local_time=bool(game.screenshotBannerLocalTime))
    txt_big = f"Body: {body}"
    txt = f"System: {system}\nCmdr: {cmdr}  -  {stamp}"
    extras = (extra or "").strip("\n")
    if extras:
        txt = f"{txt}\n{extras}"
    return txt_big, txt


def _lat_long_extra(ctx: ScreenshotContext, *, file_age_seconds: float) -> str:
    """Windows: lat/long/heading only when shot age < 10s and Status has lat/long."""
    if file_age_seconds >= 10 or not ctx.has_lat_long:
        return ""
    lat = ctx.latitude
    lon = ctx.longitude
    heading = ctx.heading
    if lat is None or lon is None:
        return ""
    head = f"{int(heading)}°" if heading is not None else "?"
    line = f"  Lat: {lat}° Long: {lon}°\n  Heading: {head}:"
    if ctx.altitude is not None:
        line += f"  Altitude: {int(ctx.altitude)}m"
    return line


def draw_banner(
    image,
    ctx: ScreenshotContext,
    game: GameSettings,
    *,
    extra: str = "",
) -> None:
    """Paint the black banner box + coloured text onto a Pillow image (in place)."""
    from PIL import ImageDraw

    txt_big, txt = build_banner_lines(ctx, game, extra=extra)
    font_big = _load_banner_font(_BANNER_BIG_PX, bold=True)
    font_small = _load_banner_font(_BANNER_SMALL_PX, bold=False)
    draw = ImageDraw.Draw(image)
    bb_big = draw.multiline_textbbox((0, 0), txt_big, font=font_big)
    bb_small = draw.multiline_textbbox((0, 0), txt, font=font_small)
    w_big = bb_big[2] - bb_big[0]
    h_big = bb_big[3] - bb_big[1]
    w_small = bb_small[2] - bb_small[0]
    h_small = bb_small[3] - bb_small[1]
    y = 10
    box_w = max(w_big, w_small) + 10
    box_h = h_big + h_small + 10
    draw.rectangle((10, y, 10 + box_w, y + box_h), fill=(0, 0, 0, 255))
    colour = _parse_banner_rgb(game)
    draw.multiline_text((15, y + 5), txt_big, font=font_big, fill=colour)
    draw.multiline_text((15, y + 5 + h_big), txt, font=font_small, fill=colour)


def output_filename(ctx: ScreenshotContext, *, high_res: bool = False) -> str:
    """Windows-style ``{body} ({yyyy-MM-dd HHmmss})[.png]`` under the system folder."""
    taken = ctx.taken_at or datetime.now(timezone.utc)
    if taken.tzinfo is not None:
        taken = taken.astimezone(timezone.utc)
    stamp = taken.strftime("%Y-%m-%d %H%M%S")
    body = (ctx.body or "unknown").strip() or "unknown"
    name = safe_filename(f"{body} ({stamp})")
    if high_res:
        name += " (HighRes)"
    return name + ".png"


def process_screenshot(
    source: Path,
    game: GameSettings,
    ctx: ScreenshotContext,
    *,
    target_root: Path | None = None,
) -> Path | None:
    """Convert one screenshot. Returns the written PNG path, or None on skip/fail.

    Never raises — errors are printed and swallowed (offline fail-soft).
    """
    try:
        return _process_screenshot(source, game, ctx, target_root=target_root)
    except Exception as exc:  # noqa: BLE001
        print(f"screenshot: failed {source}: {exc}", flush=True)
        return None


def _process_screenshot(
    source: Path,
    game: GameSettings,
    ctx: ScreenshotContext,
    *,
    target_root: Path | None = None,
) -> Path | None:
    if not game.processScreenshots:
        return None
    src = Path(source)
    if not src.is_file():
        return None
    root = Path(target_root) if target_root is not None else Path(game.screenshotTargetFolder or "")
    if not str(root):
        return None

    from PIL import Image

    taken = ctx.taken_at
    if taken is None:
        try:
            taken = datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc)
        except OSError:
            taken = datetime.now(timezone.utc)
    ctx_use = ScreenshotContext(
        system=ctx.system or "unknown",
        body=ctx.body or "unknown",
        commander=ctx.commander or "",
        latitude=ctx.latitude,
        longitude=ctx.longitude,
        altitude=ctx.altitude,
        heading=ctx.heading,
        has_lat_long=ctx.has_lat_long,
        taken_at=taken,
    )

    with Image.open(src) as opened:
        image = opened.convert("RGBA")

    if game.addBannerToScreenshots:
        age = max(0.0, datetime.now(timezone.utc).timestamp() - taken.timestamp())
        extra = _lat_long_extra(ctx_use, file_age_seconds=age)
        draw_banner(image, ctx_use, game, extra=extra)

    system_folder = safe_filename(ctx_use.system or "unknown") or "unknown"
    out_dir = root / system_folder
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / output_filename(ctx_use)
    # Avoid clobbering an existing convert from the same second.
    if out_path.exists():
        stem = out_path.stem
        n = 2
        while True:
            candidate = out_dir / f"{stem}-{n}.png"
            if not candidate.exists():
                out_path = candidate
                break
            n += 1

    rgb = image.convert("RGB")
    rgb.save(out_path, format="PNG")

    if game.showScreenshot:
        try:
            from plot_floatie import show_message

            banner_bit = "" if game.addBannerToScreenshots else " no"
            show_message(f"Saved '{out_path.name}' with{banner_bit} banner")
        except Exception:  # noqa: BLE001
            pass

    if game.deleteScreenshotOriginal:
        try:
            src.unlink(missing_ok=True)
        except OSError as exc:
            print(f"screenshot: could not delete original {src}: {exc}", flush=True)

    return out_path


def context_from_location_status(
    location,
    status=None,
    *,
    taken_at: datetime | None = None,
) -> ScreenshotContext:
    """Build a ScreenshotContext from journal CommanderLocation + StatusSnapshot."""
    system = getattr(location, "system", None) or "unknown"
    body = getattr(location, "body", None) or getattr(status, "body_name", None) or "unknown"
    commander = getattr(location, "commander", None) or ""
    has_ll = bool(getattr(status, "has_lat_long", False)) if status is not None else False
    return ScreenshotContext(
        system=str(system),
        body=str(body),
        commander=str(commander),
        latitude=getattr(status, "latitude", None) if status is not None else None,
        longitude=getattr(status, "longitude", None) if status is not None else None,
        altitude=getattr(status, "altitude", None) if status is not None else None,
        heading=getattr(status, "heading", None) if status is not None else None,
        has_lat_long=has_ll,
        taken_at=taken_at,
    )


class ScreenshotFolderWatcher:
    """Poll ``screenshotSourceFolder`` for new/changed images (mtime).

    First successful scan of a folder only seeds known paths so existing
    gallery files are not bulk-converted. Subsequent polls process new or
    newer mtimes. Fail-soft: never raises out of ``poll``.
    """

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._seeded_for: str | None = None

    def reset(self) -> None:
        self._seen.clear()
        self._seeded_for = None

    def _list_images(self, folder: Path) -> list[Path]:
        if not folder.is_dir():
            return []
        found: list[Path] = []
        try:
            for path in folder.iterdir():
                if not path.is_file():
                    continue
                if path.suffix.lower() in _IMAGE_SUFFIXES:
                    found.append(path)
        except OSError:
            return []
        return found

    def poll(
        self,
        game: GameSettings,
        ctx: ScreenshotContext,
    ) -> list[Path]:
        """Process newly appeared/updated screenshots. Returns output paths."""
        written: list[Path] = []
        try:
            if not game.processScreenshots:
                return written
            source = Path(game.screenshotSourceFolder or "")
            target = Path(game.screenshotTargetFolder or "")
            if not str(source) or not str(target):
                return written
            key = str(source.resolve()) if source.is_dir() else str(source)
            images = self._list_images(source)
            if self._seeded_for != key:
                self._seen = {}
                for path in images:
                    try:
                        self._seen[str(path)] = path.stat().st_mtime
                    except OSError:
                        continue
                self._seeded_for = key
                return written

            for path in images:
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                prev = self._seen.get(str(path))
                if prev is not None and mtime <= prev:
                    continue
                # Skip files still growing (Elite may write then rename).
                try:
                    size1 = path.stat().st_size
                    size2 = path.stat().st_size
                    if size1 != size2 or size1 <= 0:
                        continue
                except OSError:
                    continue
                taken = datetime.fromtimestamp(mtime, tz=timezone.utc)
                file_ctx = ScreenshotContext(
                    system=ctx.system,
                    body=ctx.body,
                    commander=ctx.commander,
                    latitude=ctx.latitude,
                    longitude=ctx.longitude,
                    altitude=ctx.altitude,
                    heading=ctx.heading,
                    has_lat_long=ctx.has_lat_long,
                    taken_at=taken,
                )
                out = process_screenshot(path, game, file_ctx, target_root=target)
                self._seen[str(path)] = mtime
                if out is not None:
                    written.append(out)
                    print(f"screenshot: wrote {out}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"screenshot poll: {exc}", flush=True)
        return written
