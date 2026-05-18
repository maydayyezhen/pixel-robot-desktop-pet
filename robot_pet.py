from __future__ import annotations

import json
import math
import random
import time
import tkinter as tk
import ctypes
import os
import sys
import asyncio
import threading
import uuid
import zlib
from io import BytesIO
from datetime import datetime, timedelta
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from tkinter import Menu, messagebox, simpledialog

from PIL import Image, ImageDraw, ImageFont, ImageTk
from fontTools.ttLib import TTFont

try:
    import winsound
except ImportError:  # pragma: no cover - Windows-only enhancement.
    winsound = None


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
SFX = ASSETS / "sfx"
SETTINGS = ROOT / "settings.json"
TRANSPARENT_COLOR = "#ff00ff"
STARTUP_SCRIPT_NAME = "Pixel Robot Pet.vbs"
ALARM_MENU_TIME_FORMAT = "%m-%d %H:%M"
SIZE_OPTIONS = [
    ("超小 140px", 140),
    ("小 160px", 160),
    ("中 190px", 190),
    ("大 230px", 230),
]
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 260
TRACK_FONT_PATH = Path(r"C:\Windows\Fonts\msgothic.ttc")
CHINESE_TRACK_FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")
FALLBACK_TRACK_FONT_PATH = Path(r"C:\Windows\Fonts\simsun.ttc")


def project_path(value: str | os.PathLike[str], base: Path = ROOT) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def hard_alpha(image: Image.Image, threshold: int = 112) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            pixels[x, y] = (r, g, b, 255 if a >= threshold else 0)
    return rgba


@lru_cache(maxsize=8)
def font_codepoints(font_path: str) -> frozenset[int]:
    font = TTFont(font_path, fontNumber=0, lazy=True)
    try:
        codepoints: set[int] = set()
        for table in font["cmap"].tables:
            codepoints.update(table.cmap.keys())
        return frozenset(codepoints)
    finally:
        font.close()


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: str
    size: int


@dataclass(frozen=True)
class FrameSpec:
    bob: int = 0
    x_scale: float = 1.0
    y_scale: float = 1.0
    rotate: float = 0.0


@dataclass(frozen=True)
class MediaSnapshot:
    title: str = ""
    artist: str = ""
    album_title: str = ""
    cover_bytes: bytes | None = None
    is_playing: bool | None = None
    source: str = ""


@dataclass(frozen=True)
class AlarmItem:
    id: str
    at: float
    label: str


IDLE_FRAMES = [
    FrameSpec(0, 1.00, 1.00),
    FrameSpec(-1, 1.00, 1.00),
    FrameSpec(-3, 1.01, 0.99),
    FrameSpec(-2, 1.00, 1.00),
    FrameSpec(0, 1.00, 1.00),
    FrameSpec(1, 0.995, 1.005),
    FrameSpec(2, 0.99, 1.01),
    FrameSpec(1, 0.995, 1.005),
]
SLEEP_FRAMES = [
    FrameSpec(0, 1.00, 1.00),
    FrameSpec(0, 1.00, 1.00),
    FrameSpec(1, 1.00, 1.005),
    FrameSpec(2, 0.995, 1.01),
    FrameSpec(1, 1.00, 1.005),
    FrameSpec(0, 1.00, 1.00),
]
CLICK_FRAMES = [
    FrameSpec(0, 1.00, 1.00),
    FrameSpec(-2, 1.07, 0.93),
    FrameSpec(-3, 1.10, 0.89),
    FrameSpec(-2, 1.04, 0.97),
    FrameSpec(1, 0.98, 1.04),
    FrameSpec(0, 1.00, 1.00),
]
DROP_FRAMES = [
    FrameSpec(-2, 0.98, 1.06),
    FrameSpec(8, 1.09, 0.90),
    FrameSpec(4, 1.05, 0.96),
    FrameSpec(-3, 0.96, 1.07),
    FrameSpec(0, 1.00, 1.00),
]
DRAG_FRAMES = [
    FrameSpec(0, 0.94, 1.08, -3.5),
    FrameSpec(0, 0.94, 1.08, -1.5),
    FrameSpec(0, 0.94, 1.08, 2.5),
    FrameSpec(0, 0.94, 1.08, 3.5),
    FrameSpec(0, 0.94, 1.08, 1.5),
    FrameSpec(0, 0.94, 1.08, -2.5),
]
ALARM_FRAMES = [
    FrameSpec(-3, 1.06, 0.94, -7.0),
    FrameSpec(3, 0.95, 1.06, 7.0),
    FrameSpec(-2, 1.04, 0.96, 5.5),
    FrameSpec(2, 0.96, 1.04, -5.5),
    FrameSpec(0, 1.08, 0.92, 0.0),
    FrameSpec(1, 0.96, 1.04, 6.5),
]


class RobotPet:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Pixel Robot Pet")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSPARENT_COLOR)

        with (ASSETS / "metadata.json").open("r", encoding="utf-8") as file:
            metadata = json.load(file)

        master_path = project_path(metadata.get("robot_master_refined", "assets/robot.png"))
        self.master_base = Image.open(master_path).convert("RGBA")
        self.master_screen_bbox = tuple(metadata.get("master_screen_bbox", metadata["screen_bbox"]))
        self.pet_height = self.load_saved_height(default=int(metadata["robot_size"][1]))
        self.sound_enabled = self.load_sound_enabled(default=True)
        self.music_clicks_enabled = self.load_music_clicks_enabled(default=True)
        self.show_track_info = self.load_show_track_info(default=True)
        self.playing_hint = self.load_playing_hint(default=True)
        self.alarms = self.load_alarms()
        self.ringing_alarm: AlarmItem | None = None
        self.track_title = ""
        self.track_artist = ""
        self.album_title = ""
        self.album_cover_image: Image.Image | None = None
        self.album_popup_until = 0.0
        self.alarm_ringing = False
        self.alarm_next_sound_at = 0.0
        self.alarm_flash_until = 0.0
        self.base, self.screen_bbox = self.scaled_robot(self.pet_height)
        self.window_width, self.window_height = self.window_size()
        self.canvas = tk.Canvas(
            self.root,
            width=self.window_width,
            height=self.window_height,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack()

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        start_x = max(20, screen_width - self.window_width - 80)
        start_y = max(20, screen_height - self.window_height - 120)
        self.root.geometry(f"{self.window_width}x{self.window_height}+{start_x}+{start_y}")

        self.image_id = self.canvas.create_image(
            self.window_width // 2,
            self.window_height // 2,
            anchor="center",
        )
        self.photo: ImageTk.PhotoImage | None = None
        self.track_photo: ImageTk.PhotoImage | None = None
        self.track_text_item: int | None = None
        self.track_text_key: tuple[object, ...] | None = None
        self.frame_photo_cache: dict[tuple[object, ...], ImageTk.PhotoImage] = {}
        self.particles: list[Particle] = []
        self.dragging = False
        self.drag_start_root = (0, 0)
        self.drag_start_pointer = (0, 0)
        self.drag_distance = 0
        self.sleeping = False
        self.always_on_top = True
        self.click_until = 0.0
        self.drop_until = 0.0
        self.next_blink_at = time.monotonic() + random.uniform(1.2, 3.2)
        self.blink_until = 0.0
        self.last_click_effect_at = 0.0
        self.media_indicator = ""
        self.media_indicator_until = 0.0
        self.hover_media_action = ""
        self.current_cursor = ""
        self.album_cover_wait_until = 0.0
        self.album_cover_key: tuple[int, int] | None = None
        self.next_track_poll_at = 0.0
        self.last_particle_tick_at = time.monotonic()
        self.media_poll_thread: threading.Thread | None = None
        self.media_poll_lock = threading.Lock()
        self.pending_media_snapshot: MediaSnapshot | None = None
        self.size_var = tk.IntVar(value=self.pet_height)
        self.sound_var = tk.BooleanVar(value=self.sound_enabled)
        self.music_clicks_var = tk.BooleanVar(value=self.music_clicks_enabled)
        self.track_info_var = tk.BooleanVar(value=self.show_track_info)
        self.topmost_var = tk.BooleanVar(value=self.always_on_top)
        self.startup_var = tk.BooleanVar(value=self.startup_enabled())

        self.menu = Menu(self.root, tearoff=False)
        self.menu.add_command(label="睡觉 / 唤醒", command=self.toggle_sleep)

        self.music_menu = Menu(self.menu, tearoff=False)
        self.music_menu.add_command(label="播放 / 暂停", command=lambda: self.media_action("play_pause"))
        self.music_menu.add_command(label="上一首", command=lambda: self.media_action("prev"))
        self.music_menu.add_command(label="下一首", command=lambda: self.media_action("next"))
        self.music_menu.add_separator()
        self.music_menu.add_checkbutton(
            label="点击控歌",
            variable=self.music_clicks_var,
            command=self.toggle_music_clicks,
        )
        self.music_menu.add_checkbutton(
            label="显示歌名",
            variable=self.track_info_var,
            command=self.toggle_track_info,
        )
        self.menu.add_cascade(label="音乐控制", menu=self.music_menu)

        self.alarm_menu = Menu(self.menu, tearoff=False)
        self.alarm_menu.add_command(label="查看 / 管理...", command=self.show_alarm_manager)
        self.alarm_menu.add_separator()
        self.alarm_menu.add_command(label="自定义时间...", command=self.set_custom_alarm)
        self.alarm_menu.add_separator()
        self.alarm_menu.add_command(label="10 分钟后", command=lambda: self.set_alarm_after_minutes(10))
        self.alarm_menu.add_command(label="30 分钟后", command=lambda: self.set_alarm_after_minutes(30))
        self.alarm_menu.add_command(label="明天 08:30", command=self.set_alarm_tomorrow_morning)
        self.alarm_menu.add_separator()
        self.alarm_menu.add_command(label="稍后 5 分钟", command=lambda: self.snooze_alarm(5))
        self.alarm_menu.add_command(label="关闭闹钟", command=self.clear_alarm)
        self.menu.add_cascade(label="闹钟", menu=self.alarm_menu)

        self.size_menu = Menu(self.menu, tearoff=False)
        for label, height in SIZE_OPTIONS:
            self.size_menu.add_radiobutton(
                label=label,
                variable=self.size_var,
                value=height,
                command=lambda selected_height=height: self.set_pet_size(selected_height),
            )
        self.menu.add_cascade(label="大小", menu=self.size_menu)
        self.menu.add_checkbutton(label="音效", variable=self.sound_var, command=self.toggle_sound)
        self.menu.add_checkbutton(label="置顶开关", variable=self.topmost_var, command=self.toggle_topmost)
        self.menu.add_checkbutton(label="开机自启动", variable=self.startup_var, command=self.toggle_startup)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.root.destroy)

        self.canvas.bind("<Enter>", self.update_cursor)
        self.canvas.bind("<Leave>", self.clear_cursor)
        self.canvas.bind("<Motion>", self.update_cursor)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.show_menu)

    def load_saved_height(self, default: int) -> int:
        if not SETTINGS.exists():
            return default
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            saved = int(data.get("pet_height", default))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return default
        valid_sizes = {height for _, height in SIZE_OPTIONS}
        return saved if saved in valid_sizes else default

    def load_sound_enabled(self, default: bool) -> bool:
        if not SETTINGS.exists():
            return default
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            return bool(data.get("sound_enabled", default))
        except (OSError, TypeError, json.JSONDecodeError):
            return default

    def load_music_clicks_enabled(self, default: bool) -> bool:
        if not SETTINGS.exists():
            return default
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            return bool(data.get("music_clicks_enabled", default))
        except (OSError, TypeError, json.JSONDecodeError):
            return default

    def load_show_track_info(self, default: bool) -> bool:
        if not SETTINGS.exists():
            return default
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            return bool(data.get("show_track_info", default))
        except (OSError, TypeError, json.JSONDecodeError):
            return default

    def load_playing_hint(self, default: bool) -> bool:
        if not SETTINGS.exists():
            return default
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            return bool(data.get("playing_hint", default))
        except (OSError, TypeError, json.JSONDecodeError):
            return default

    def load_alarms(self) -> list[AlarmItem]:
        if not SETTINGS.exists():
            return []
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            raw_alarms = data.get("alarms")
            alarms: list[AlarmItem] = []
            if isinstance(raw_alarms, list):
                for item in raw_alarms:
                    if not isinstance(item, dict):
                        continue
                    alarm_at = float(item.get("at", 0))
                    if alarm_at <= 0:
                        continue
                    label = str(item.get("label", "") or "")
                    alarm_id = str(item.get("id", "") or f"alarm-{alarm_at:.3f}")
                    alarms.append(AlarmItem(alarm_id, alarm_at, label))
                return sorted(alarms, key=lambda alarm: alarm.at)

            alarm_at = data.get("alarm_at")
            if alarm_at is not None:
                timestamp = float(alarm_at)
                label = str(data.get("alarm_label", "") or "")
                return [AlarmItem(f"alarm-{timestamp:.3f}", timestamp, label)]
            return []
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []

    def next_alarm(self) -> AlarmItem | None:
        return min(self.alarms, key=lambda alarm: alarm.at, default=None)

    def save_settings(self) -> None:
        next_alarm = self.next_alarm()
        SETTINGS.write_text(
            json.dumps(
                {
                    "pet_height": self.pet_height,
                    "sound_enabled": self.sound_enabled,
                    "music_clicks_enabled": self.music_clicks_enabled,
                    "show_track_info": self.show_track_info,
                    "playing_hint": self.playing_hint,
                    "alarms": [
                        {"id": alarm.id, "at": alarm.at, "label": alarm.label}
                        for alarm in sorted(self.alarms, key=lambda item: item.at)
                    ],
                    "alarm_at": next_alarm.at if next_alarm else None,
                    "alarm_label": next_alarm.label if next_alarm else "",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def play_sound(self, name: str) -> None:
        if not self.sound_enabled or winsound is None:
            return
        path = SFX / f"{name}.wav"
        if not path.exists():
            return
        flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        winsound.PlaySound(str(path), flags)

    def startup_script_path(self) -> Path:
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / STARTUP_SCRIPT_NAME

    def pythonw_path(self) -> Path:
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            return executable
        candidate = executable.with_name("pythonw.exe")
        return candidate if candidate.exists() else executable

    def startup_vbs(self) -> str:
        def quoted(path: Path) -> str:
            return str(path).replace('"', '""')

        command = f'""{quoted(self.pythonw_path())}"" ""{quoted(ROOT / "robot_pet.py")}""'
        return (
            'Set shell = CreateObject("WScript.Shell")\n'
            f'shell.CurrentDirectory = "{quoted(ROOT)}"\n'
            f'shell.Run "{command}", 0, False\n'
        )

    def startup_enabled(self) -> bool:
        return self.startup_script_path().exists()

    def set_startup_enabled(self, enabled: bool) -> bool:
        path = self.startup_script_path()
        try:
            if enabled:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self.startup_vbs(), encoding="utf-8")
            elif path.exists():
                path.unlink()
        except OSError:
            return False
        return True

    def toggle_startup(self) -> None:
        enabled = bool(self.startup_var.get())
        if not self.set_startup_enabled(enabled):
            self.startup_var.set(self.startup_enabled())
            return
        self.play_sound("toggle")

    def toggle_sound(self) -> None:
        self.sound_enabled = bool(self.sound_var.get())
        self.save_settings()
        if self.sound_enabled:
            self.play_sound("toggle")

    def toggle_music_clicks(self) -> None:
        self.music_clicks_enabled = bool(self.music_clicks_var.get())
        if not self.music_clicks_enabled:
            self.hover_media_action = ""
        self.save_settings()
        self.play_sound("toggle")

    def toggle_track_info(self) -> None:
        self.show_track_info = bool(self.track_info_var.get())
        current_x = self.root.winfo_x()
        current_y = self.root.winfo_y()
        self.window_width, self.window_height = self.window_size()
        self.canvas.config(width=self.window_width, height=self.window_height)
        self.root.geometry(f"{self.window_width}x{self.window_height}+{current_x}+{current_y}")
        self.canvas.coords(self.image_id, *self.pet_center())
        self.canvas.delete("track_text")
        self.canvas.delete("equalizer")
        self.track_text_item = None
        self.track_text_key = None
        self.save_settings()
        self.refresh_music_info()
        self.play_sound("toggle")

    def alarm_visual_active(self) -> bool:
        return self.alarm_ringing

    def alarm_display_label(self) -> str:
        alarm = self.ringing_alarm or self.next_alarm()
        if alarm is None:
            return ""
        return alarm.label or datetime.fromtimestamp(alarm.at).strftime(ALARM_MENU_TIME_FORMAT)

    def set_alarm(self, alarm_time: datetime, label: str) -> None:
        alarm_label = label.strip() or alarm_time.strftime(ALARM_MENU_TIME_FORMAT)
        alarm = AlarmItem(f"alarm-{uuid.uuid4().hex}", alarm_time.timestamp(), alarm_label)
        self.alarms.append(alarm)
        self.alarms.sort(key=lambda item: item.at)
        self.alarm_ringing = False
        self.ringing_alarm = None
        self.alarm_next_sound_at = 0.0
        self.alarm_flash_until = time.monotonic() + 0.6
        self.save_settings()
        self.resize_window_for_content()
        self.spawn_sparks(*self.pet_center(), count=10)
        self.play_sound("toggle")

    def set_alarm_after_minutes(self, minutes: int) -> None:
        self.set_alarm(datetime.now() + timedelta(minutes=minutes), f"{minutes} 分钟后")

    def set_alarm_tomorrow_morning(self) -> None:
        tomorrow = datetime.now().date() + timedelta(days=1)
        self.set_alarm(datetime.combine(tomorrow, datetime.min.time()).replace(hour=8, minute=30), "明天 08:30")

    def parse_alarm_input(self, text: str, now: datetime | None = None) -> datetime:
        current = now or datetime.now()
        clean = " ".join(text.replace("：", ":").replace("T", " ").split())
        if not clean:
            raise ValueError("请输入时间")

        if clean.count(":") == 1 and all(part.isdigit() for part in clean.split(":")):
            hour_text, minute_text = clean.split(":")
            hour = int(hour_text)
            minute = int(minute_text)
            if hour > 23 or minute > 59:
                raise ValueError("时间应为 00:00 到 23:59")
            alarm_time = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if alarm_time <= current:
                alarm_time += timedelta(days=1)
            return alarm_time

        full_formats = ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M")
        for fmt in full_formats:
            try:
                alarm_time = datetime.strptime(clean, fmt)
            except ValueError:
                continue
            if alarm_time <= current:
                raise ValueError("这个时间已经过去了")
            return alarm_time

        partial_formats = ("%m-%d %H:%M", "%m/%d %H:%M")
        for fmt in partial_formats:
            try:
                partial = datetime.strptime(clean, fmt)
            except ValueError:
                continue
            alarm_time = partial.replace(year=current.year)
            if alarm_time <= current:
                alarm_time = alarm_time.replace(year=current.year + 1)
            return alarm_time

        raise ValueError("格式示例：21:30、2026-05-18 21:30、05-19 08:30")

    def set_custom_alarm(self, parent: tk.Misc | None = None) -> None:
        dialog_parent = parent or self.root
        text = simpledialog.askstring(
            "设置闹钟",
            "输入时间：\n21:30\n2026-05-18 21:30\n05-19 08:30",
            parent=dialog_parent,
        )
        if text is None:
            return
        try:
            alarm_time = self.parse_alarm_input(text)
        except ValueError as exc:
            messagebox.showerror("闹钟时间无效", str(exc), parent=dialog_parent)
            return
        label = simpledialog.askstring(
            "闹钟名称",
            "提醒内容：",
            initialvalue="提醒",
            parent=dialog_parent,
        )
        if label is None:
            return
        self.set_alarm(alarm_time, label.strip() or alarm_time.strftime(ALARM_MENU_TIME_FORMAT))

    def clear_alarm(self) -> None:
        was_active = self.alarm_ringing or bool(self.alarms)
        self.alarms.clear()
        self.ringing_alarm = None
        self.alarm_ringing = False
        self.alarm_next_sound_at = 0.0
        self.alarm_flash_until = 0.0
        self.save_settings()
        if was_active:
            self.resize_window_for_content()
            self.play_sound("toggle")

    def snooze_alarm(self, minutes: int = 5) -> None:
        label = self.alarm_display_label() or "提醒"
        self.alarm_ringing = False
        self.ringing_alarm = None
        self.set_alarm(datetime.now() + timedelta(minutes=minutes), f"{label} · 稍后 {minutes} 分钟")

    def remove_alarm(self, alarm_id: str) -> None:
        before = len(self.alarms)
        self.alarms = [alarm for alarm in self.alarms if alarm.id != alarm_id]
        if len(self.alarms) != before:
            self.save_settings()
            self.resize_window_for_content()
            self.play_sound("toggle")

    def trigger_alarm(self, alarm: AlarmItem) -> None:
        self.alarm_ringing = True
        self.ringing_alarm = alarm
        self.alarm_next_sound_at = 0.0
        self.alarm_flash_until = time.monotonic() + 12.0
        self.alarms = [item for item in self.alarms if item.id != alarm.id]
        self.save_settings()
        self.resize_window_for_content()
        self.spawn_sparks(*self.pet_center(), count=28)

    def dismiss_alarm(self) -> None:
        if not self.alarm_ringing:
            return
        self.alarm_ringing = False
        self.ringing_alarm = None
        self.alarm_next_sound_at = 0.0
        self.alarm_flash_until = 0.0
        self.resize_window_for_content()
        self.play_sound("toggle")

    def tick_alarm(self, now: float) -> None:
        if not self.alarm_ringing:
            due = [alarm for alarm in self.alarms if time.time() >= alarm.at]
            if due:
                self.trigger_alarm(min(due, key=lambda alarm: alarm.at))
        if not self.alarm_ringing:
            return
        if now >= self.alarm_next_sound_at:
            self.play_sound("alarm")
            self.spawn_sparks(*self.pet_center(), count=10)
            self.alarm_next_sound_at = now + 0.8

    def format_alarm_item(self, alarm: AlarmItem) -> str:
        return f"{datetime.fromtimestamp(alarm.at).strftime(ALARM_MENU_TIME_FORMAT)}  {alarm.label or '闹钟'}"

    def show_alarm_manager(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("管理闹钟")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.transient(self.root)

        listbox = tk.Listbox(dialog, width=42, height=8, activestyle="dotbox")
        listbox.grid(row=0, column=0, columnspan=4, padx=10, pady=(10, 8), sticky="nsew")
        alarm_ids: list[str] = []

        def refresh() -> None:
            alarm_ids.clear()
            listbox.delete(0, tk.END)
            if self.alarm_ringing and self.ringing_alarm is not None:
                listbox.insert(tk.END, f"响铃中  {self.ringing_alarm.label or '闹钟'}")
                alarm_ids.append("")
            for alarm in sorted(self.alarms, key=lambda item: item.at):
                listbox.insert(tk.END, self.format_alarm_item(alarm))
                alarm_ids.append(alarm.id)
            if not alarm_ids:
                listbox.insert(tk.END, "没有已设置的闹钟")

        def delete_selected() -> None:
            selection = listbox.curselection()
            if not selection:
                return
            alarm_id = alarm_ids[selection[0]] if selection[0] < len(alarm_ids) else ""
            if alarm_id:
                self.remove_alarm(alarm_id)
                refresh()

        def add_custom() -> None:
            self.set_custom_alarm(dialog)
            refresh()

        def snooze_current() -> None:
            if self.alarm_ringing:
                self.snooze_alarm(5)
                refresh()

        tk.Button(dialog, text="新增", width=8, command=add_custom).grid(row=1, column=0, padx=(10, 4), pady=(0, 10))
        tk.Button(dialog, text="删除", width=8, command=delete_selected).grid(row=1, column=1, padx=4, pady=(0, 10))
        tk.Button(dialog, text="清空", width=8, command=lambda: (self.clear_alarm(), refresh())).grid(row=1, column=2, padx=4, pady=(0, 10))
        tk.Button(dialog, text="关闭", width=8, command=dialog.destroy).grid(row=1, column=3, padx=(4, 10), pady=(0, 10))
        tk.Button(dialog, text="稍后 5 分钟", width=14, command=snooze_current).grid(row=2, column=0, columnspan=4, pady=(0, 10))
        refresh()

    def process_path_for_pid(self, pid: int) -> str:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(MAX_PATH)
            size = ctypes.c_ulong(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            return ""
        finally:
            kernel32.CloseHandle(handle)

    def qqmusic_window_title(self) -> str:
        user32 = ctypes.windll.user32
        titles: list[str] = []

        enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            path = self.process_path_for_pid(pid.value)
            if not path.lower().endswith("qqmusic.exe"):
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if title:
                titles.append(title)
            return True

        user32.EnumWindows(enum_windows_proc(callback), 0)
        for title in titles:
            if " - " in title:
                return title
        return titles[0] if titles else ""

    def parse_track_title(self, title: str) -> MediaSnapshot | None:
        if not title or title in {"QQ音乐", "QQMusic"} or " - " not in title:
            return None
        song, artist = [part.strip() for part in title.rsplit(" - ", 1)]
        if not song or not artist:
            return None
        return MediaSnapshot(title=song, artist=artist, source="QQMusic.exe")

    async def media_thumbnail_bytes(self, props: object) -> bytes | None:
        thumbnail = getattr(props, "thumbnail", None)
        if thumbnail is None:
            return None
        try:
            from winsdk.windows.storage.streams import DataReader  # type: ignore[import-not-found]

            stream = await thumbnail.open_read_async()
            size = int(getattr(stream, "size", 0) or 0)
            if size <= 0:
                return None
            reader = DataReader(stream)
            await reader.load_async(size)
            data = bytearray(size)
            reader.read_bytes(data)
            return bytes(data)
        except Exception:
            return None

    async def system_media_snapshot_async(self) -> MediaSnapshot | None:
        try:
            from winsdk.windows.media.control import (  # type: ignore[import-not-found]
                GlobalSystemMediaTransportControlsSessionManager as MediaManager,
            )
        except ImportError:
            return None

        manager = await MediaManager.request_async()
        sessions = list(manager.get_sessions())
        if not sessions:
            return None

        current = manager.get_current_session()
        session = None
        for candidate in sessions:
            source = getattr(candidate, "source_app_user_model_id", "")
            if "qqmusic" in source.lower():
                session = candidate
                break
        if session is None:
            session = current or sessions[0]

        playback = session.get_playback_info()
        status = playback.playback_status
        status_name = getattr(status, "name", str(status)).upper()
        if "PLAYING" in status_name:
            is_playing: bool | None = True
        elif any(name in status_name for name in ("PAUSED", "STOPPED", "CLOSED")):
            is_playing = False
        else:
            is_playing = None

        props = await session.try_get_media_properties_async()
        title = str(getattr(props, "title", "") or "").strip()
        artist = str(getattr(props, "artist", "") or "").strip()
        album_title = str(getattr(props, "album_title", "") or "").strip()
        cover_bytes = await self.media_thumbnail_bytes(props)
        source = str(getattr(session, "source_app_user_model_id", "") or "")
        if not title and not artist and is_playing is None:
            return None
        return MediaSnapshot(
            title=title,
            artist=artist,
            album_title=album_title,
            cover_bytes=cover_bytes,
            is_playing=is_playing,
            source=source,
        )

    def read_media_snapshot(self) -> MediaSnapshot | None:
        try:
            snapshot = asyncio.run(self.system_media_snapshot_async())
        except Exception:
            snapshot = None
        if snapshot is not None:
            return snapshot
        return self.parse_track_title(self.qqmusic_window_title())

    def media_poll_worker(self) -> None:
        snapshot = self.read_media_snapshot()
        if snapshot is None:
            return
        with self.media_poll_lock:
            self.pending_media_snapshot = snapshot

    def start_media_poll(self) -> None:
        if self.media_poll_thread is not None and self.media_poll_thread.is_alive():
            return
        self.media_poll_thread = threading.Thread(target=self.media_poll_worker, daemon=True)
        self.media_poll_thread.start()

    def apply_media_snapshot(self, snapshot: MediaSnapshot) -> None:
        changed = False
        now = time.monotonic()
        if snapshot.title and snapshot.artist:
            changed = snapshot.title != self.track_title or snapshot.artist != self.track_artist
            self.track_title = snapshot.title
            self.track_artist = snapshot.artist
        if snapshot.album_title or changed:
            self.album_title = snapshot.album_title
        old_cover = self.album_cover_image
        if snapshot.cover_bytes is not None:
            cover_key = (len(snapshot.cover_bytes), zlib.crc32(snapshot.cover_bytes))
            if cover_key != self.album_cover_key:
                self.album_cover_image = self.prepare_album_cover(snapshot.cover_bytes)
                self.album_cover_key = cover_key if self.album_cover_image is not None else None
        elif changed:
            self.album_cover_image = None
            self.album_cover_key = None
        cover_ready = self.album_cover_image is not None
        cover_just_arrived = old_cover is None and cover_ready
        if snapshot.is_playing is not None:
            self.playing_hint = snapshot.is_playing
        if changed:
            if cover_ready:
                self.album_cover_wait_until = 0.0
                self.album_popup_until = now + 3.6
            elif self.media_hover_disabled(now):
                self.album_popup_until = 0.0
            else:
                self.album_popup_until = now + 2.4
            self.resize_window_for_content()
        elif cover_just_arrived and self.media_hover_disabled(now):
            self.album_cover_wait_until = 0.0
            self.album_popup_until = now + 3.6

    def apply_pending_media_snapshot(self) -> None:
        with self.media_poll_lock:
            snapshot = self.pending_media_snapshot
            self.pending_media_snapshot = None
        if snapshot is not None:
            self.apply_media_snapshot(snapshot)

    def refresh_music_info(self) -> None:
        snapshot = self.read_media_snapshot()
        if snapshot is not None:
            self.apply_media_snapshot(snapshot)

    def send_media_key(self, virtual_key: int) -> None:
        user32 = ctypes.windll.user32
        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, 0)

    def media_action(self, action: str) -> None:
        key_map = {
            "play_pause": VK_MEDIA_PLAY_PAUSE,
            "prev": VK_MEDIA_PREV_TRACK,
            "next": VK_MEDIA_NEXT_TRACK,
        }
        indicator_map = {
            "prev": "prev",
            "next": "next",
        }
        virtual_key = key_map.get(action)
        if virtual_key is None:
            return
        self.send_media_key(virtual_key)
        if action == "play_pause":
            # Optimistic hint for immediate feedback; the media session poll
            # corrects it to the real QQ Music state shortly after.
            self.playing_hint = not self.playing_hint
            self.media_indicator = "pause" if self.playing_hint else "play"
        else:
            self.playing_hint = True
            self.media_indicator = indicator_map[action]
            self.hover_media_action = ""
            self.album_cover_wait_until = time.monotonic() + 3.2
        self.media_indicator_until = time.monotonic() + 0.62
        self.next_track_poll_at = time.monotonic() + 0.28
        self.click_until = time.monotonic() + 0.22
        self.save_settings()
        self.spawn_sparks(*self.pet_center(), count=8)
        self.play_sound("click")

    def media_action_from_click(self, event: tk.Event) -> bool:
        action = self.media_action_at_point(event.x, event.y, allow_while_waiting=True)
        if not action:
            return False

        self.media_action(action)
        return True

    def media_hover_disabled(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return current < self.album_cover_wait_until

    def media_action_at_point(self, x: int, y: int, allow_while_waiting: bool = False) -> str:
        if not self.music_clicks_enabled or self.sleeping or self.dragging or self.alarm_ringing:
            return ""
        if self.media_hover_disabled() and not allow_while_waiting:
            return ""
        center_x, center_y = self.pet_center()
        robot_left = center_x - self.base.width // 2
        robot_top = center_y - self.base.height // 2
        screen_left, screen_top, screen_right, screen_bottom = self.screen_bbox
        relative_x = x - robot_left
        relative_y = y - robot_top
        if (
            relative_x < screen_left
            or relative_x > screen_right
            or relative_y < screen_top
            or relative_y > screen_bottom
        ):
            return ""

        screen_width = screen_right - screen_left
        screen_x = relative_x - screen_left
        if screen_x < screen_width * 0.34:
            return "prev"
        elif screen_x > screen_width * 0.66:
            return "next"
        return "play_pause"

    def hover_indicator(self) -> tuple[str, float]:
        if self.hover_media_action == "prev":
            return "prev", -0.2
        if self.hover_media_action == "next":
            return "next", 0.2
        if self.hover_media_action == "play_pause":
            return ("pause" if self.playing_hint else "play"), 0.0
        return "", 0.0

    def update_cursor(self, event: tk.Event | None = None) -> None:
        if self.media_hover_disabled():
            self.hover_media_action = ""
        elif event is not None:
            self.hover_media_action = self.media_action_at_point(event.x, event.y)
        elif self.dragging or self.sleeping or not self.music_clicks_enabled:
            self.hover_media_action = ""

        if self.dragging:
            cursor = "fleur"
        elif self.sleeping:
            cursor = "watch"
        elif self.hover_media_action:
            cursor = "hand2"
        else:
            cursor = "hand2"
        if cursor != self.current_cursor:
            self.canvas.config(cursor=cursor)
            self.current_cursor = cursor

    def clear_cursor(self, _event: tk.Event | None = None) -> None:
        if not self.dragging:
            self.hover_media_action = ""
            if self.current_cursor:
                self.canvas.config(cursor="")
                self.current_cursor = ""

    def scaled_robot(self, height: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
        scale = height / self.master_base.height
        width = max(1, round(self.master_base.width * scale))
        base = hard_alpha(self.master_base.resize((width, height), Image.Resampling.LANCZOS))
        bbox = tuple(round(value * scale) for value in self.master_screen_bbox)
        return base, bbox

    def prepare_album_cover(self, cover_bytes: bytes) -> Image.Image | None:
        try:
            cover = Image.open(BytesIO(cover_bytes)).convert("RGBA")
        except Exception:
            return None
        side = min(cover.width, cover.height)
        if side <= 0:
            return None
        left = (cover.width - side) // 2
        top = (cover.height - side) // 2
        cover = cover.crop((left, top, left + side, top + side))
        pixel_side = max(14, min(26, round(self.pet_height * 0.12)))
        return cover.resize((pixel_side, pixel_side), Image.Resampling.BILINEAR)

    def window_size(self) -> tuple[int, int]:
        needs_text = self.show_track_info or self.alarm_visual_active()
        text_height = self.track_text_height() if needs_text else 0
        text_width = self.max_track_text_width() if needs_text else 0
        return max(260, self.base.width + 96, text_width + 32), max(180, self.base.height + text_height + 30)

    def resize_window_for_content(self) -> None:
        if not hasattr(self, "canvas"):
            return
        new_width, new_height = self.window_size()
        if new_width == self.window_width and new_height == self.window_height:
            return
        pet_screen_x = self.root.winfo_x() + self.pet_center()[0]
        pet_screen_y = self.root.winfo_y() + self.pet_center()[1]
        self.window_width, self.window_height = new_width, new_height
        new_x = max(0, pet_screen_x - self.pet_center()[0])
        new_y = max(0, pet_screen_y - self.pet_center()[1])
        self.canvas.config(width=self.window_width, height=self.window_height)
        self.root.geometry(f"{self.window_width}x{self.window_height}+{new_x}+{new_y}")
        self.canvas.coords(self.image_id, *self.pet_center())

    def pet_center(self) -> tuple[int, int]:
        return self.window_width // 2, self.window_height - self.base.height // 2 - 18

    def track_text_height(self) -> int:
        title_size, artist_size = self.track_font_sizes()
        album_size = self.album_font_size()
        equalizer_height = self.equalizer_height(title_size)
        return title_size + artist_size + album_size + equalizer_height + max(20, round(self.pet_height * 0.12))

    def track_text_width(self) -> int:
        if not self.track_title:
            return 0
        title_size, artist_size = self.track_font_sizes()
        album_size = self.album_font_size()
        max_text_width = self.max_track_text_width()
        title = self.fit_text_to_width(self.track_title, title_size, max_text_width)
        artist = self.fit_text_to_width(self.track_artist, artist_size, max_text_width)
        album = self.fit_text_to_width(self.album_popup_text(), album_size, max_text_width)
        return max(self.text_width(title, title_size), self.text_width(artist, artist_size), self.text_width(album, album_size), 48)

    def track_font_sizes(self) -> tuple[int, int]:
        title_size = max(18, min(38, round(self.pet_height * 0.16)))
        artist_size = max(12, min(25, round(self.pet_height * 0.105)))
        return title_size, artist_size

    def album_font_size(self) -> int:
        return max(11, min(20, round(self.pet_height * 0.085)))

    def equalizer_height(self, title_size: int) -> int:
        return max(10, round(title_size * 0.6))

    def album_popup_active(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return (bool(self.album_title) or self.album_cover_image is not None) and current < self.album_popup_until

    def album_popup_text(self) -> str:
        return f"专辑 {self.album_title}" if self.album_title else ""

    def track_font(self, size: int, font_path: Path | None = None) -> ImageFont.FreeTypeFont:
        path = font_path or (TRACK_FONT_PATH if TRACK_FONT_PATH.exists() else CHINESE_TRACK_FONT_PATH)
        return ImageFont.truetype(str(path), size=size)

    def max_track_text_width(self) -> int:
        return max(220, min(560, round(self.pet_height * 3.55)))

    def is_kana(self, char: str) -> bool:
        codepoint = ord(char)
        return 0x3040 <= codepoint <= 0x30ff or 0x31f0 <= codepoint <= 0x31ff

    def is_han(self, char: str) -> bool:
        codepoint = ord(char)
        return (
            0x3400 <= codepoint <= 0x4dbf
            or 0x4e00 <= codepoint <= 0x9fff
            or 0xf900 <= codepoint <= 0xfaff
        )

    def text_prefers_japanese(self, text: str) -> bool:
        return any(self.is_kana(char) for char in text)

    def needs_latin_embolden(self, text: str) -> bool:
        return any(0x0021 <= ord(char) <= 0x024f for char in text)

    def latin_width_scale(self, size: int) -> float:
        return 1.24 if size >= 18 else 1.18

    def latin_tracking(self, size: int) -> int:
        return max(1, round(size * 0.09))

    def split_latin_embolden_runs(self, text: str) -> list[tuple[str, bool]]:
        if not text:
            return []
        runs: list[tuple[str, bool]] = []
        current_text = text[0]
        current_embolden = self.needs_latin_embolden(text[0])
        for char in text[1:]:
            embolden = self.needs_latin_embolden(char)
            if embolden == current_embolden:
                current_text += char
            else:
                runs.append((current_text, current_embolden))
                current_text = char
                current_embolden = embolden
        runs.append((current_text, current_embolden))
        return runs

    def latin_segment_width(self, text: str, font: ImageFont.FreeTypeFont, size: int) -> int:
        width = 0
        tracking = self.latin_tracking(size)
        scale = self.latin_width_scale(size)
        for index, char in enumerate(text):
            width += max(1, round(font.getlength(char) * scale))
            if index < len(text) - 1:
                width += tracking
        return width

    def draw_latin_segment(
        self,
        image: Image.Image,
        cursor_x: int,
        y: int,
        text: str,
        font: ImageFont.FreeTypeFont,
        size: int,
        fill: tuple[int, int, int, int],
    ) -> int:
        scale = self.latin_width_scale(size)
        tracking = self.latin_tracking(size)
        segment_bbox = font.getbbox(text)
        baseline_y = y - segment_bbox[1]
        start_x = cursor_x
        pad = 3

        for index, char in enumerate(text):
            advance = max(1, round(font.getlength(char) * scale))
            if not char.isspace():
                bbox = font.getbbox(char)
                glyph_width = max(1, bbox[2] - bbox[0] + pad * 2 + 2)
                glyph_height = max(1, bbox[3] - bbox[1] + pad * 2)
                glyph = Image.new("RGBA", (glyph_width, glyph_height), (0, 0, 0, 0))
                glyph_draw = ImageDraw.Draw(glyph)
                glyph_draw.text((pad - bbox[0], pad - bbox[1]), char, font=font, fill=fill)
                glyph_draw.text((pad - bbox[0] + 1, pad - bbox[1]), char, font=font, fill=fill)
                glyph = hard_alpha(glyph, threshold=96)
                scaled_width = max(1, round(glyph.width * scale))
                glyph = glyph.resize((scaled_width, glyph.height), Image.Resampling.NEAREST)
                dest_x = max(0, round(cursor_x - pad * scale))
                dest_y = max(0, round(baseline_y + bbox[1] - pad))
                image.alpha_composite(glyph, (dest_x, dest_y))
            cursor_x += advance
            if index < len(text) - 1:
                cursor_x += tracking

        return cursor_x - start_x

    def font_supports_char(self, font_path: Path, char: str) -> bool:
        if not font_path.exists():
            return False
        return ord(char) in font_codepoints(str(font_path))

    def font_path_for_char(self, char: str, prefer_japanese: bool) -> Path:
        if char.isspace():
            return TRACK_FONT_PATH

        if self.is_kana(char):
            candidates = [TRACK_FONT_PATH, CHINESE_TRACK_FONT_PATH, FALLBACK_TRACK_FONT_PATH]
        elif self.is_han(char):
            if prefer_japanese:
                candidates = [TRACK_FONT_PATH, CHINESE_TRACK_FONT_PATH, FALLBACK_TRACK_FONT_PATH]
            else:
                candidates = [CHINESE_TRACK_FONT_PATH, FALLBACK_TRACK_FONT_PATH, TRACK_FONT_PATH]
        else:
            candidates = [TRACK_FONT_PATH, CHINESE_TRACK_FONT_PATH, FALLBACK_TRACK_FONT_PATH]

        for candidate in candidates:
            if self.font_supports_char(candidate, char):
                return candidate
        return CHINESE_TRACK_FONT_PATH if CHINESE_TRACK_FONT_PATH.exists() else TRACK_FONT_PATH

    def line_runs(self, text: str, size: int) -> list[tuple[str, ImageFont.FreeTypeFont]]:
        prefer_japanese = self.text_prefers_japanese(text)
        runs: list[tuple[str, ImageFont.FreeTypeFont]] = []
        current_path: Path | None = None
        current_text = ""
        for char in text:
            path = self.font_path_for_char(char, prefer_japanese)
            if current_path is None:
                current_path = path
                current_text = char
                continue
            if path == current_path:
                current_text += char
            else:
                runs.append((current_text, self.track_font(size, current_path)))
                current_path = path
                current_text = char
        if current_text and current_path is not None:
            runs.append((current_text, self.track_font(size, current_path)))
        return runs

    def text_width(self, text: str, size: int) -> int:
        width = 0
        for run_text, font in self.line_runs(text, size):
            for segment, embolden in self.split_latin_embolden_runs(run_text):
                if embolden:
                    width += self.latin_segment_width(segment, font, size)
                else:
                    width += round(font.getlength(segment))
        return width

    def text_height(self, text: str, size: int) -> int:
        heights = []
        for run_text, font in self.line_runs(text or " ", size):
            bbox = font.getbbox(run_text)
            heights.append(bbox[3] - bbox[1])
        return max(heights or [size])

    def fit_text_to_width(self, text: str, size: int, max_width: int) -> str:
        clean = " ".join(text.split())
        if self.text_width(clean, size) <= max_width:
            return clean
        ellipsis = "…"
        lo = 1
        hi = len(clean)
        best = ellipsis
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = clean[:mid].rstrip() + ellipsis
            if self.text_width(candidate, size) <= max_width:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def set_pet_size(self, height: int) -> None:
        if height == self.pet_height:
            return

        center_x = self.root.winfo_x() + self.window_width // 2
        center_y = self.root.winfo_y() + self.window_height // 2
        self.pet_height = height
        self.size_var.set(height)
        self.base, self.screen_bbox = self.scaled_robot(height)
        self.window_width, self.window_height = self.window_size()
        new_x = max(0, center_x - self.window_width // 2)
        new_y = max(0, center_y - self.window_height // 2)

        self.canvas.config(width=self.window_width, height=self.window_height)
        self.root.geometry(f"{self.window_width}x{self.window_height}+{new_x}+{new_y}")
        self.canvas.coords(self.image_id, *self.pet_center())
        self.frame_photo_cache.clear()
        self.track_text_key = None
        self.particles.clear()
        self.save_settings()
        self.spawn_sparks(self.window_width / 2, self.window_height / 2, count=8)
        self.play_sound("resize")

    def toggle_sleep(self, _event: tk.Event | None = None) -> None:
        self.sleeping = not self.sleeping
        self.hover_media_action = ""
        if not self.sleeping:
            self.spawn_sparks(*self.pet_center(), count=12)
            self.play_sound("wake")
        else:
            self.play_sound("sleep")
        self.update_cursor()

    def toggle_topmost(self) -> None:
        self.always_on_top = bool(self.topmost_var.get())
        self.root.attributes("-topmost", self.always_on_top)
        self.play_sound("toggle")

    def show_menu(self, event: tk.Event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def on_press(self, event: tk.Event) -> None:
        self.dragging = False
        self.drag_distance = 0
        self.drag_start_root = (self.root.winfo_x(), self.root.winfo_y())
        self.drag_start_pointer = (event.x_root, event.y_root)

    def on_drag(self, event: tk.Event) -> None:
        dx = event.x_root - self.drag_start_pointer[0]
        dy = event.y_root - self.drag_start_pointer[1]
        self.drag_distance = max(self.drag_distance, abs(dx) + abs(dy))
        self.dragging = self.drag_distance > 4
        self.update_cursor()
        new_x = self.drag_start_root[0] + dx
        new_y = self.drag_start_root[1] + dy
        self.root.geometry(f"+{new_x}+{new_y}")

    def on_release(self, event: tk.Event) -> None:
        now = time.monotonic()
        if self.dragging:
            self.drop_until = now + 0.35
            self.spawn_sparks(self.window_width / 2, self.window_height - 58, count=8)
            self.play_sound("drop")
        elif self.alarm_ringing:
            self.dismiss_alarm()
            self.spawn_sparks(*self.pet_center(), count=10)
        elif self.sleeping:
            self.sleeping = False
            self.spawn_sparks(*self.pet_center(), count=12)
            self.play_sound("wake")
        else:
            handled_media = self.media_action_from_click(event)
            if not handled_media:
                self.click_until = now + 0.32
            if not handled_media and now - self.last_click_effect_at >= 0.08:
                self.spawn_sparks(event.x, event.y, count=10)
                self.play_sound("click")
                self.last_click_effect_at = now
        self.dragging = False
        self.update_cursor()

    def spawn_sparks(self, x: float, y: float, count: int = 10) -> None:
        colors = ["#4fe8d8", "#ff8a61", "#fff3d2", "#1f2d36"]
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(1.4, 4.0)
            self.particles.append(
                Particle(
                    x=x,
                    y=y,
                    vx=math.cos(angle) * speed,
                    vy=math.sin(angle) * speed - 1.0,
                    life=random.uniform(0.28, 0.62),
                    color=random.choice(colors),
                    size=random.choice([3, 4, 5]),
                )
            )

    def expression(self, now: float) -> str:
        if self.sleeping:
            return "sleep"
        if self.dragging:
            return "drag"
        if now < self.click_until:
            return "happy"
        if now < self.blink_until:
            return "blink"
        if now >= self.next_blink_at:
            self.blink_until = now + 0.11
            self.next_blink_at = now + random.uniform(1.6, 4.2)
            return "blink"
        return "idle"

    def draw_led_dot(self, draw: ImageDraw.ImageDraw, x: int, y: int, block: int) -> None:
        draw.rectangle((x, y, x + block - 1, y + block - 1), fill=(80, 235, 216, 255))

    def draw_media_indicator(
        self,
        draw: ImageDraw.ImageDraw,
        screen: tuple[int, int, int, int],
        block: int,
        indicator: str | None = None,
        size_scale: float = 0.88,
        x_bias: float = 0.0,
    ) -> None:
        indicator = indicator or self.media_indicator
        if not indicator:
            return

        left, top, right, bottom = screen
        width = right - left
        height = bottom - top
        led = (86, 241, 220, 255)
        cy = top + height // 2
        cx = left + width // 2 + round(width * x_bias)
        size = max(block * 3, round(max(block * 4, width // 8) * size_scale))

        if indicator == "play":
            draw.polygon(
                [
                    (cx - size // 2, cy - size),
                    (cx - size // 2, cy + size),
                    (cx + size, cy),
                ],
                fill=led,
            )
        elif indicator == "pause":
            gap = max(block * 2, size // 4)
            bar_width = max(block, size // 3)
            draw.rectangle((cx - gap - bar_width, cy - size, cx - gap, cy + size), fill=led)
            draw.rectangle((cx + gap, cy - size, cx + gap + bar_width, cy + size), fill=led)
        elif indicator == "prev":
            draw.rectangle((cx - size - block * 2, cy - size, cx - size - block, cy + size), fill=led)
            draw.polygon([(cx - size, cy), (cx, cy - size), (cx, cy + size)], fill=led)
            draw.polygon([(cx, cy), (cx + size, cy - size), (cx + size, cy + size)], fill=led)
        elif indicator == "next":
            draw.rectangle((cx + size + block, cy - size, cx + size + block * 2, cy + size), fill=led)
            draw.polygon([(cx - size, cy - size), (cx - size, cy + size), (cx, cy)], fill=led)
            draw.polygon([(cx, cy - size), (cx, cy + size), (cx + size, cy)], fill=led)

    def draw_alarm_indicator(
        self,
        draw: ImageDraw.ImageDraw,
        screen: tuple[int, int, int, int],
        block: int,
        now: float,
    ) -> None:
        left, top, right, bottom = screen
        width = right - left
        height = bottom - top
        cx = left + width // 2
        cy = top + height // 2
        pulse = int(now * 5) % 2 == 0
        led = (255, 174, 114, 255) if pulse else (86, 241, 220, 255)
        bar_w = max(block * 2, width // 12)
        bar_h = max(block * 8, height // 3)
        draw.rectangle((cx - bar_w // 2, cy - bar_h, cx + bar_w // 2, cy + block * 2), fill=led)
        dot = max(block * 2, bar_w)
        draw.rectangle((cx - dot // 2, cy + bar_h // 2, cx + dot // 2, cy + bar_h // 2 + dot), fill=led)

    def draw_album_cover_on_screen(
        self,
        image: Image.Image,
        screen: tuple[int, int, int, int],
        block: int,
    ) -> None:
        if self.album_cover_image is None:
            return
        left, top, right, bottom = screen
        width = right - left
        height = bottom - top
        inset = max(2, block)
        cover_size = max(1, min(width - inset * 2, height - inset * 2))
        cover = self.album_cover_image.resize((cover_size, cover_size), Image.Resampling.NEAREST)
        cover_x = left + (width - cover_size) // 2
        cover_y = top + (height - cover_size) // 2
        image.alpha_composite(cover, (cover_x, cover_y))

    def draw_expression(self, image: Image.Image, expression: str, now: float) -> Image.Image:
        image = image.copy()
        draw = ImageDraw.Draw(image)
        left, top, right, bottom = self.screen_bbox
        width = right - left
        height = bottom - top
        block = max(3, round(width / 35))

        # Repaint only the face display area so expressions stay crisp.
        draw.rounded_rectangle(
            (left + block, top + block, right - block, bottom - block),
            radius=max(8, height // 5),
            fill=(8, 20, 28, 255),
        )

        eye_y = top + height // 2 - block * 3
        left_eye_x = left + width // 3 - block * 2
        right_eye_x = left + width * 2 // 3 - block * 2
        mouth_y = top + height * 2 // 3 + block
        led = (86, 241, 220, 255)

        if self.alarm_ringing and not self.dragging:
            self.draw_alarm_indicator(draw, self.screen_bbox, block, now)
        elif self.album_popup_active(now) and self.album_cover_image is not None and not self.sleeping and not self.dragging:
            self.draw_album_cover_on_screen(image, self.screen_bbox, block)
        elif self.media_indicator and now < self.media_indicator_until and not self.sleeping:
            x_bias = -0.12 if self.media_indicator == "prev" else 0.12 if self.media_indicator == "next" else 0.0
            self.draw_media_indicator(draw, self.screen_bbox, block, self.media_indicator, 0.82, x_bias)
        elif self.hover_media_action and not self.sleeping:
            indicator, x_bias = self.hover_indicator()
            self.draw_media_indicator(draw, self.screen_bbox, block, indicator, 0.72, x_bias)
        elif expression == "blink":
            draw.rectangle((left_eye_x - block, eye_y + block * 2, left_eye_x + block * 5, eye_y + block * 3), fill=led)
            draw.rectangle((right_eye_x - block, eye_y + block * 2, right_eye_x + block * 5, eye_y + block * 3), fill=led)
        elif expression == "happy":
            for offset in range(4):
                draw.line(
                    (
                        left_eye_x - block * 2 + offset * block,
                        eye_y + block * 3 - abs(offset - 1.5) * block,
                        left_eye_x + block * 5 - offset * block,
                        eye_y + block * 3 - abs(offset - 1.5) * block,
                    ),
                    fill=led,
                    width=block,
                )
                draw.line(
                    (
                        right_eye_x - block * 2 + offset * block,
                        eye_y + block * 3 - abs(offset - 1.5) * block,
                        right_eye_x + block * 5 - offset * block,
                        eye_y + block * 3 - abs(offset - 1.5) * block,
                    ),
                    fill=led,
                    width=block,
                )
            draw.rectangle((left + width // 2 - block, mouth_y, left + width // 2 + block, mouth_y + block), fill=led)
        elif expression == "sleep":
            for i in range(5):
                y = eye_y + i * block
                draw.rectangle((left_eye_x - block * 2 + i * block, y, left_eye_x - block + i * block, y + block - 1), fill=led)
                draw.rectangle((right_eye_x - block * 2 + i * block, y, right_eye_x - block + i * block, y + block - 1), fill=led)
            draw.rectangle((left + width // 2 - block, mouth_y + block, left + width // 2 + block, mouth_y + block * 2), fill=led)
        elif expression == "drag":
            for ex in (left_eye_x, right_eye_x):
                draw.rectangle((ex, eye_y - block, ex + block * 3, eye_y + block * 6), fill=led)
                draw.rectangle((ex + block, eye_y - block * 2, ex + block * 2, eye_y + block * 7), fill=led)
            draw.rectangle((left + width // 2 - block, mouth_y, left + width // 2 + block, mouth_y + block), fill=led)
        else:
            for ex in (left_eye_x, right_eye_x):
                for py in range(5):
                    for px in range(4):
                        if (px in (0, 3) and py in (0, 4)):
                            continue
                        self.draw_led_dot(draw, ex + px * block, eye_y + py * block, block)
            draw.rectangle((left + width // 2 - block, mouth_y, left + width // 2 + block, mouth_y + block), fill=led)

        return image

    def shorten(self, text: str, limit: int) -> str:
        clean = " ".join(text.split())
        if len(clean) <= limit:
            return clean
        return clean[: max(1, limit - 1)] + "…"

    def render_track_text_image(
        self,
        title: str,
        artist: str,
        album: str,
        title_size: int,
        artist_size: int,
        album_size: int,
    ) -> Image.Image:
        title_width = self.text_width(title, title_size)
        artist_width = self.text_width(artist, artist_size)
        album_width = self.text_width(album, album_size)
        title_height = self.text_height(title, title_size)
        artist_height = self.text_height(artist, artist_size)
        album_height = self.text_height(album, album_size) if album else 0
        gap = max(3, round(self.pet_height * 0.025))
        shadow = max(1, round(self.pet_height / 100))
        album_gap = max(2, round(self.pet_height * 0.018)) if album else 0
        width = max(title_width, artist_width, album_width) + shadow * 2 + 8
        height = title_height + artist_height + album_height + gap + album_gap + shadow * 2 + 8
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        def draw_centered_text(y: int, text: str, size: int, fill: tuple[int, int, int, int]) -> None:
            line_width = self.text_width(text, size)
            x = (width - line_width) // 2
            for draw_shadow in (True, False):
                cursor_x = x + (shadow if draw_shadow else 0)
                for run_text, font in self.line_runs(text, size):
                    text_fill = (21, 33, 38, 255) if draw_shadow else fill
                    for segment, embolden in self.split_latin_embolden_runs(run_text):
                        line_y = y + (shadow if draw_shadow else 0)
                        if embolden:
                            cursor_x += self.draw_latin_segment(
                                image,
                                round(cursor_x),
                                line_y,
                                segment,
                                font,
                                size,
                                text_fill,
                            )
                        else:
                            bbox = font.getbbox(segment)
                            baseline_y = line_y - bbox[1]
                            text_x = cursor_x - bbox[0]
                            draw.text((text_x, baseline_y), segment, font=font, fill=text_fill)
                            cursor_x += round(font.getlength(segment))

        title_y = 4
        artist_y = title_y + title_height + gap
        album_y = artist_y + artist_height + album_gap
        draw_centered_text(title_y, title, title_size, (255, 243, 210, 255))
        draw_centered_text(artist_y, artist, artist_size, (79, 232, 216, 255))
        if album:
            draw_centered_text(album_y, album, album_size, (255, 174, 114, 255))
        return hard_alpha(image, threshold=96)

    def draw_track_text(self) -> None:
        self.canvas.delete("equalizer")
        title = artist = album = ""
        title_size, artist_size = self.track_font_sizes()
        album_size = self.album_font_size()
        if self.alarm_ringing:
            max_text_width = min(self.max_track_text_width(), max(80, self.window_width - 32))
            title = self.fit_text_to_width("闹钟时间到", title_size, max_text_width)
            label = self.alarm_display_label() or "点击关闭"
            artist = self.fit_text_to_width(label, artist_size, max_text_width)
            album = self.fit_text_to_width("点击关闭 · 右键稍后提醒", album_size, max_text_width)
        elif self.show_track_info and self.track_title:
            max_text_width = min(self.max_track_text_width(), max(80, self.window_width - 32))
            title = self.fit_text_to_width(self.track_title, title_size, max_text_width)
            artist = self.fit_text_to_width(self.track_artist, artist_size, max_text_width)
            album = self.fit_text_to_width(self.album_popup_text(), album_size, max_text_width) if self.album_popup_active() else ""
        else:
            self.canvas.delete("track_text")
            self.track_text_item = None
            self.track_text_key = None
            return

        key = (title, artist, album, title_size, artist_size, album_size, self.pet_height)
        if key != self.track_text_key or self.track_photo is None:
            text_image = self.render_track_text_image(title, artist, album, title_size, artist_size, album_size)
            self.track_photo = ImageTk.PhotoImage(text_image)
            self.track_text_key = key

        center_x, center_y = self.pet_center()
        robot_top = center_y - self.base.height // 2
        if self.alarm_ringing:
            text_top = max(0, robot_top - max(6, round(self.pet_height * 0.05)) - self.track_photo.height())
        else:
            equalizer_height = self.equalizer_height(title_size)
            equalizer_base_y = robot_top - max(5, round(self.pet_height * 0.035))
            text_gap = max(4, round(self.pet_height * 0.03))
            text_top = max(0, equalizer_base_y - equalizer_height - text_gap - self.track_photo.height())

        if self.track_text_item is None:
            self.track_text_item = self.canvas.create_image(
                center_x,
                text_top,
                anchor="n",
                image=self.track_photo,
                tags="track_text",
            )
        else:
            self.canvas.itemconfig(self.track_text_item, image=self.track_photo)
            self.canvas.coords(self.track_text_item, center_x, text_top)

        if not self.alarm_ringing:
            self.draw_playing_equalizer(center_x, equalizer_base_y, title_size)

    def draw_playing_equalizer(self, center_x: int, base_y: int, title_size: int) -> None:
        if not self.playing_hint:
            return
        bar_count = 4
        scale = max(1, round(self.pet_height / 150))
        bar_width = max(3, round(title_size * 0.18))
        gap = max(2, round(title_size * 0.12))
        max_height = self.equalizer_height(title_size)
        total_width = bar_count * bar_width + (bar_count - 1) * gap
        x0 = center_x - total_width // 2
        now = time.monotonic()
        for index in range(bar_count):
            phase = now * 7.2 + index * 1.35
            height = max(5 * scale, round(max_height * (0.35 + 0.65 * abs(math.sin(phase)))))
            left = x0 + index * (bar_width + gap)
            self.canvas.create_rectangle(
                left + scale,
                base_y - height + scale,
                left + bar_width + scale,
                base_y + scale,
                fill="#152126",
                outline="",
                tags="equalizer",
            )
            self.canvas.create_rectangle(
                left,
                base_y - height,
                left + bar_width,
                base_y,
                fill="#4fe8d8",
                outline="",
                tags="equalizer",
            )

    def cycle_frame(self, now: float, frames: list[FrameSpec], fps: float) -> FrameSpec:
        return frames[int(now * fps) % len(frames)]

    def timed_frame(self, now: float, until: float, duration: float, frames: list[FrameSpec]) -> FrameSpec:
        remaining = max(0.0, until - now)
        progress = max(0.0, min(1.0, 1.0 - remaining / duration))
        index = min(len(frames) - 1, int(progress * len(frames)))
        return frames[index]

    def animation_frame_spec(self, now: float) -> FrameSpec:
        if self.dragging:
            return self.cycle_frame(now, DRAG_FRAMES, fps=12.0)
        if self.alarm_ringing:
            return self.cycle_frame(now, ALARM_FRAMES, fps=18.0)
        if now < self.click_until:
            return self.timed_frame(now, self.click_until, 0.32, CLICK_FRAMES)
        if now < self.drop_until:
            return self.timed_frame(now, self.drop_until, 0.35, DROP_FRAMES)
        if self.sleeping:
            return self.cycle_frame(now, SLEEP_FRAMES, fps=4.0)
        return self.cycle_frame(now, IDLE_FRAMES, fps=8.0)

    def transform_frame(self, image: Image.Image, spec: FrameSpec) -> tuple[Image.Image, int]:
        new_size = (
            max(1, round(image.width * spec.x_scale)),
            max(1, round(image.height * spec.y_scale)),
        )
        frame = image.resize(new_size, Image.Resampling.NEAREST)
        if spec.rotate:
            frame = frame.rotate(spec.rotate, resample=Image.Resampling.NEAREST, expand=True)
        return frame, spec.bob

    def frame_cache_key(self, expr: str, spec: FrameSpec, now: float) -> tuple[object, ...] | None:
        if self.alarm_ringing:
            return None
        if self.album_popup_active(now) and self.album_cover_image is not None and not self.sleeping and not self.dragging:
            return None
        active_indicator = self.media_indicator if self.media_indicator and now < self.media_indicator_until and not self.sleeping else ""
        hover_action = self.hover_media_action if self.hover_media_action and not self.sleeping else ""
        return (
            self.pet_height,
            expr,
            spec,
            active_indicator,
            hover_action,
            self.playing_hint if hover_action == "play_pause" else None,
        )

    def make_frame(self, now: float, expr: str | None = None, spec: FrameSpec | None = None) -> tuple[Image.Image, int]:
        expr = expr or self.expression(now)
        spec = spec or self.animation_frame_spec(now)
        image = self.draw_expression(self.base, expr, now)
        return self.transform_frame(image, spec)

    def render_frame_photo(self, now: float) -> tuple[ImageTk.PhotoImage, int]:
        expr = self.expression(now)
        spec = self.animation_frame_spec(now)
        key = self.frame_cache_key(expr, spec, now)
        if key is not None:
            cached = self.frame_photo_cache.get(key)
            if cached is not None:
                return cached, spec.bob

        frame, bob = self.make_frame(now, expr, spec)
        photo = ImageTk.PhotoImage(frame)
        if key is not None:
            if len(self.frame_photo_cache) > 96:
                self.frame_photo_cache.clear()
            self.frame_photo_cache[key] = photo
        return photo, bob

    def alarm_shake_x(self, now: float) -> int:
        if not self.alarm_ringing:
            return 0
        return round(math.sin(now * 58.0) * max(5, self.pet_height * 0.045))

    def tick_particles(self, dt: float) -> None:
        self.canvas.delete("particle")
        alive: list[Particle] = []
        step = max(0.5, min(3.0, dt * 33.0))
        for particle in self.particles:
            particle.life -= dt
            if particle.life <= 0:
                continue
            particle.x += particle.vx * step
            particle.y += particle.vy * step
            particle.vy += 0.12 * step
            alive.append(particle)
            self.canvas.create_rectangle(
                particle.x,
                particle.y,
                particle.x + particle.size,
                particle.y + particle.size,
                fill=particle.color,
                outline="",
                tags="particle",
            )
        self.particles = alive[-80:]

    def next_update_delay_ms(self, now: float) -> int:
        if self.alarm_ringing or self.dragging:
            return 30
        if self.particles or now < self.click_until or now < self.drop_until:
            return 33
        if now < self.media_indicator_until or self.hover_media_action:
            return 50
        if self.album_popup_active(now):
            return 60
        if self.show_track_info and self.track_title and self.playing_hint:
            return 80
        if self.sleeping:
            return 180
        return 110

    def update(self) -> None:
        now = time.monotonic()
        self.tick_alarm(now)
        self.apply_pending_media_snapshot()
        if now >= self.next_track_poll_at:
            self.start_media_poll()
            self.next_track_poll_at = now + 1.0
        self.photo, bob = self.render_frame_photo(now)
        self.canvas.itemconfig(self.image_id, image=self.photo)
        center_x, center_y = self.pet_center()
        self.canvas.coords(self.image_id, center_x + self.alarm_shake_x(now), center_y + bob)
        particle_dt = min(0.12, max(0.001, now - self.last_particle_tick_at))
        self.last_particle_tick_at = now
        self.tick_particles(particle_dt)
        self.draw_track_text()
        self.root.after(self.next_update_delay_ms(now), self.update)

    def run(self) -> None:
        self.update()
        self.root.mainloop()


def main() -> None:
    missing = [path for path in (ASSETS / "robot.png", ASSETS / "metadata.json") if not path.exists()]
    if missing:
        raise SystemExit("Missing assets. Run: python tools\\make_assets.py")
    RobotPet().run()


if __name__ == "__main__":
    main()
