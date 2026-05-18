from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from robot_pet import (  # noqa: E402
    ASSETS,
    CLICK_FRAMES,
    DRAG_FRAMES,
    DROP_FRAMES,
    IDLE_FRAMES,
    SETTINGS,
    SLEEP_FRAMES,
    RobotPet,
    project_path,
)


STATE_FRAMES = {
    "idle": ("idle", IDLE_FRAMES),
    "happy": ("happy", CLICK_FRAMES),
    "sleep": ("sleep", SLEEP_FRAMES),
    "drag": ("drag", DRAG_FRAMES),
    "drop": ("idle", DROP_FRAMES),
}


def build_preview_bot() -> RobotPet:
    with (ASSETS / "metadata.json").open("r", encoding="utf-8") as file:
        metadata = json.load(file)

    bot = object.__new__(RobotPet)
    bot.master_base = Image.open(project_path(metadata.get("robot_master_refined", "assets/robot.png"))).convert("RGBA")
    bot.master_screen_bbox = tuple(metadata.get("master_screen_bbox", metadata["screen_bbox"]))
    bot.pet_height = 160
    if SETTINGS.exists():
        try:
            bot.pet_height = int(json.loads(SETTINGS.read_text(encoding="utf-8")).get("pet_height", bot.pet_height))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    bot.base, bot.screen_bbox = RobotPet.scaled_robot(bot, bot.pet_height)
    bot.sleeping = False
    bot.dragging = False
    bot.click_until = 0.0
    bot.drop_until = 0.0
    bot.blink_until = 0.0
    bot.next_blink_at = 999999.0
    bot.media_indicator = ""
    bot.media_indicator_until = 0.0
    bot.hover_media_action = ""
    bot.playing_hint = True
    bot.album_title = ""
    bot.album_cover_image = None
    bot.album_popup_until = 0.0
    bot.album_cover_wait_until = 0.0
    bot.alarm_ringing = False
    bot.ringing_alarm = None
    bot.alarms = []
    bot.alarm_next_sound_at = 0.0
    bot.alarm_flash_until = 0.0
    return bot


def fixed_stage(bot: RobotPet, frame: Image.Image, bob: int, label: str | None = None) -> Image.Image:
    stage = Image.new("RGBA", (bot.base.width + 54, bot.base.height + 42), (255, 255, 255, 0))
    x = (stage.width - frame.width) // 2
    y = (stage.height - frame.height) // 2 + bob
    stage.alpha_composite(frame, (x, y))
    if label:
        draw = ImageDraw.Draw(stage)
        draw.text((4, 4), label, fill=(24, 34, 38, 255))
    return stage


def state_frame(bot: RobotPet, state: str, index: int) -> Image.Image:
    expression, frames = STATE_FRAMES[state]
    spec = frames[index % len(frames)]
    image = RobotPet.draw_expression(bot, bot.base, expression, 0.0)
    frame, bob = RobotPet.transform_frame(bot, image, spec)
    return fixed_stage(bot, frame, bob)


def save_state_frames(bot: RobotPet) -> list[Image.Image]:
    out_dir = ASSETS / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    sequence: list[Image.Image] = []
    for state, (_expression, frames) in STATE_FRAMES.items():
        for index in range(len(frames)):
            frame = state_frame(bot, state, index)
            frame.save(out_dir / f"{state}_{index:02d}.png")
            sequence.append(fixed_stage(bot, frame, 0, state if index == 0 else None))
    return sequence


def save_sheet(frames: list[Image.Image]) -> Path:
    screenshots = ROOT / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    columns = 8
    gap = 8
    cell_w = max(frame.width for frame in frames)
    cell_h = max(frame.height for frame in frames)
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * cell_w + (columns + 1) * gap, rows * cell_h + (rows + 1) * gap), (255, 255, 255, 255))
    for index, frame in enumerate(frames):
        col = index % columns
        row = index // columns
        x = gap + col * (cell_w + gap) + (cell_w - frame.width) // 2
        y = gap + row * (cell_h + gap) + (cell_h - frame.height) // 2
        sheet.alpha_composite(frame, (x, y))
    out = screenshots / "animation-frames-sheet.png"
    sheet.convert("RGB").save(out)
    return out


def save_gif(frames: list[Image.Image]) -> Path:
    out = ASSETS / "animation-preview.gif"
    gif_frames = []
    for frame in frames:
        background = Image.new("RGBA", frame.size, (255, 255, 255, 255))
        background.alpha_composite(frame)
        gif_frames.append(background.convert("P", palette=Image.Palette.ADAPTIVE))
    gif_frames[0].save(out, save_all=True, append_images=gif_frames[1:], duration=110, loop=0, disposal=2)
    return out


def main() -> None:
    bot = build_preview_bot()
    frames = save_state_frames(bot)
    sheet = save_sheet(frames)
    gif = save_gif(frames)
    print(sheet)
    print(gif)


if __name__ == "__main__":
    main()
