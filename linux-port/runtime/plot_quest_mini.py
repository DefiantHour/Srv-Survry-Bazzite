#!/usr/bin/env python3
"""PlotQuestMini — active quests from journal / XDG quests.json."""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from quests import ActiveQuest, QuestList, default_quests_path, load_quests

ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)

TITLE_PX = 9
BODY_PX = 8
PAD = 8
DEFAULT_WIDTH = 200
_MAX_QUEST_ROWS = 4


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


# Re-export for callers / tests that imported from plot_quest_mini.
__all__ = [
    "default_quests_path",
    "load_local_quests",
    "quest_mini_allowed",
    "render_quest_mini_bitmap",
]


def load_local_quests(
    path: Path | None = None,
) -> list[dict[str, str]]:
    """Load ``[{title, objective}, …]`` rows from XDG quests.json."""
    return load_quests(path).active_rows()


def quest_mini_allowed(
    game: GameSettings,
    *,
    force_show: bool = False,
    active_quest_count: int = 0,
) -> bool:
    """Match PlotQuestMini.allowed."""
    if force_show:
        return True
    if not game.enableQuests:
        return False
    return active_quest_count > 0


def render_quest_mini_bitmap(
    status: StatusSnapshot | None = None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
    active_quest_count: int = 0,
    quests: list[dict[str, str]] | QuestList | list[ActiveQuest] | None = None,
) -> tuple[bytes, int, int] | None:
    """Show active quest titles/objectives when enableQuests is on."""
    from PIL import Image, ImageDraw

    del status  # mode gating deferred (Windows allows many flight modes)
    gs = game if game is not None else GameSettings()

    rows: list[dict[str, str]]
    if quests is None:
        rows = load_local_quests()
    elif isinstance(quests, QuestList):
        rows = quests.active_rows()
    elif quests and isinstance(quests[0], ActiveQuest):
        rows = [q.as_row() for q in quests]  # type: ignore[union-attr]
    else:
        rows = list(quests)  # type: ignore[arg-type]

    count = active_quest_count if active_quest_count > 0 else len(rows)
    if not quest_mini_allowed(
        gs, force_show=force_show, active_quest_count=count
    ):
        return None

    lines: list[tuple[str, tuple[int, int, int, int], bool]] = [
        ("Quests", ORANGE, True),
    ]
    if rows:
        for row in rows[:_MAX_QUEST_ROWS]:
            title = row.get("title") or "Quest"
            lines.append((title, CYAN, False))
            objective = row.get("objective") or ""
            if objective:
                lines.append((f"  {objective}", ORANGE_DIM, False))
        if len(rows) > _MAX_QUEST_ROWS:
            extra = len(rows) - _MAX_QUEST_ROWS
            lines.append((f"+{extra} more", ORANGE_DIM, False))
    else:
        lines.append(("No active quests", ORANGE_DIM, False))
        lines.append(("Accept a mission in-game", ORANGE_DIM, False))

    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    width = max(
        _s(DEFAULT_WIDTH),
        max(
            _tw(probe, t, font_title if bold else font_body)
            for t, _, bold in lines
        )
        + _s(PAD * 2),
    )
    row_h = _s(14)
    height = _s(10) + len(lines) * row_h + _s(10)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width - 1, height - 1), fill=BLACK)
    step = _s(3)
    for y in range(0, height, step):
        draw.line((0, y, width - 1, y), fill=STRIPE)
    for y, col in ((_s(3), ORANGE_DIM), (_s(4), ORANGE), (_s(5), ORANGE_DIM)):
        draw.line((_s(2), y, width - _s(4), y), fill=col)
    for y, col in (
        (height - _s(5), ORANGE_DIM),
        (height - _s(4), ORANGE),
        (height - _s(3), ORANGE_DIM),
    ):
        draw.line((_s(2), y, width - _s(4), y), fill=col)
    draw.rectangle((0, 0, width - 1, height - 1), outline=ORANGE, width=max(1, SCALE // 2))

    y = _s(8)
    for text, col, bold in lines:
        font = font_title if bold else font_body
        draw.text((_s(PAD), y), text, font=font, fill=col)
        y += row_h

    if SCALE != 1:
        img = img.resize((width // AA, height // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h
