import json
import math
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:  # pragma: no cover - shown to users at runtime
    Image = ImageDraw = ImageTk = None

try:
    import pystray
except ImportError:  # pragma: no cover - tray is optional
    pystray = None


APP_NAME = "Tiny Desktop Pet"
APP_VERSION = "0.3.0"
APP_CREATED = "2026-05-07"
APP_AUTHORS = "Made by Codex, supervised by Dzonas"
TRANSPARENT = "#ff00ff"
STATE_FILE = Path.home() / ".codex" / "desktop-pet-state.json"
PETS_DIR = Path.home() / ".codex" / "pets"


CODEX_ROWS = {
    "idle": (0, 6),
    "running-right": (1, 8),
    "running-left": (2, 8),
    "happy": (3, 4),
    "jumping": (4, 5),
    "sad": (5, 8),
    "hungry": (6, 6),
    "playing": (7, 6),
    "sleeping": (8, 6),
}


PHRASES_JP = [
    "Nani?", "Sugoi!", "Uso!", "Yatta!", "Kawaii!", "Mou!",
    "Ikuzo!", "Ikimashou!", "Ganbatte!", "Kisama!", "Dame!",
    "Tasukete!", "Yamete!", "Urusai!", "Ohayou!", "Sayonara.",
    "Arigatou.", "Daijoubu?", "Gomen...", "Gomen nasai.",
    "Shinjite!", "Itadakimasu!", "Nakama.", "Senpai...", "Ore wa...!",
]

PHRASES_EN = [
    "Let's go!", "Amazing!", "Do your best!", "I did it!",
    "No way!", "Stop!", "Help!", "Shut up!", "Sorry...",
    "Are you okay?", "Goodbye.", "Thank you.", "Cute!",
    "Believe in me!", "Geez!", "Don't!", "Come on!",
    "Big brother...", "Let's eat!", "I'm with you.",
]


def installed_pet_ids() -> list[str]:
    if not PETS_DIR.exists():
        return []
    return [p.name for p in sorted(PETS_DIR.iterdir()) if (p / "pet.json").exists()]


def pet_dir(pet_id: str | None) -> Path | None:
    if not pet_id:
        return None
    return PETS_DIR / pet_id


def read_pet_config(pet_id: str | None) -> dict:
    directory = pet_dir(pet_id)
    if not directory:
        return {}
    config_path = directory / "petconfig.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_custom_phrases(pet_id: str | None) -> list[str] | None:
    directory = pet_dir(pet_id)
    if not directory:
        return None
    phrases_path = directory / "phrases.json"
    if not phrases_path.exists():
        return None
    try:
        phrases = json.loads(phrases_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(phrases, list):
        return None
    cleaned = [str(phrase).strip() for phrase in phrases if str(phrase).strip()]
    return cleaned or None


def phrase_pool_for_pet(pet_id: str | None) -> tuple[str, list[str]]:
    custom = read_custom_phrases(pet_id)
    if custom:
        return "custom", custom

    language = str(read_pet_config(pet_id).get("phrase_language", "jp")).lower()
    if language == "en":
        return "en", PHRASES_EN
    return "jp", PHRASES_JP


def pick_phrase_sample(pet_id: str | None, count: int = 5) -> list[str]:
    _language, phrases = phrase_pool_for_pet(pet_id)
    if len(phrases) <= count:
        return list(phrases)
    return random.sample(phrases, count)


@dataclass
class PetStats:
    hunger: float = 80.0
    happiness: float = 75.0
    energy: float = 80.0
    age: float = 0.0
    alive: bool = True
    personality: str = "curious"
    last_seen: float = field(default_factory=time.time)

    def degrade(self, seconds: float) -> None:
        if not self.alive:
            return
        seconds = min(seconds, 8 * 3600)
        hours = seconds / 3600
        self.hunger = max(0, self.hunger - 7.0 * hours)
        self.happiness = max(0, self.happiness - 4.0 * hours)
        self.energy = max(0, self.energy - 3.0 * hours)
        self.age = min(100, self.age + 1.2 * hours)
        if self.hunger <= 0 or self.happiness <= 0:
            self.alive = False

    def mood(self) -> str:
        if not self.alive:
            return "sad"
        if self.energy < 18:
            return "sleeping"
        if self.hunger < 25:
            return "hungry"
        if self.happiness < 25:
            return "sad"
        return "idle"


class SpriteBank:
    def __init__(self, pet_id: str | None):
        self.pet_id = pet_id
        self.frames: dict[str, list[ImageTk.PhotoImage]] = {}
        self.raw_frames: dict[str, list[Image.Image]] = {}
        self.loaded = False
        if Image and pet_id:
            self.loaded = self._load_pet(pet_id)

    def _load_pet(self, pet_id: str) -> bool:
        pet_dir = PETS_DIR / pet_id
        manifest_path = pet_dir / "pet.json"
        if not manifest_path.exists():
            return False

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

        sprite_name = manifest.get("spritesheetPath") or "spritesheet.png"
        sprite_path = pet_dir / sprite_name
        if not sprite_path.exists():
            for fallback in ("spritesheet.png", "spritesheet.webp", "spritesheet.gif"):
                if (pet_dir / fallback).exists():
                    sprite_path = pet_dir / fallback
                    break
        if not sprite_path.exists():
            return False

        try:
            sheet = Image.open(sprite_path).convert("RGBA")
        except Exception:
            return False

        animations = manifest.get("animations")
        if isinstance(animations, dict):
            self._load_manifest_animations(sheet, animations)
        elif sheet.size == (1536, 1872):
            self._load_codex_atlas(sheet)
        else:
            self._load_horizontal_strip(sheet, manifest)

        return bool(self.raw_frames)

    def _load_manifest_animations(self, sheet: "Image.Image", animations: dict) -> None:
        cell_w = int(animations.get("frameWidth", 192))
        cell_h = int(animations.get("frameHeight", 208))
        for name, spec in animations.items():
            if not isinstance(spec, dict):
                continue
            row = int(spec.get("row", 0))
            count = int(spec.get("frames", spec.get("frameCount", 1)))
            self.raw_frames[name] = self._crop_row(sheet, row, count, cell_w, cell_h)

    def _load_codex_atlas(self, sheet: "Image.Image") -> None:
        for name, (row, count) in CODEX_ROWS.items():
            self.raw_frames[name] = self._crop_row(sheet, row, count, 192, 208)

    def _load_horizontal_strip(self, sheet: "Image.Image", manifest: dict) -> None:
        count = int(manifest.get("frameCount", manifest.get("frames", 6)))
        frame_w = int(manifest.get("frameWidth", sheet.width // max(1, count)))
        frame_h = int(manifest.get("frameHeight", sheet.height))
        self.raw_frames["idle"] = self._crop_row(sheet, 0, count, frame_w, frame_h)

    def _crop_row(self, sheet: "Image.Image", row: int, count: int, w: int, h: int) -> list["Image.Image"]:
        frames = []
        for i in range(count):
            frame = sheet.crop((i * w, row * h, (i + 1) * w, (row + 1) * h))
            if frame.getchannel("A").getbbox():
                frames.append(self._fit(frame))
        return frames

    def _fit(self, image: "Image.Image") -> "Image.Image":
        image = self._clean_chroma_edges(image)
        bbox = image.getchannel("A").getbbox()
        if bbox:
            image = image.crop(bbox)
        image.thumbnail((84, 94), Image.Resampling.NEAREST)
        canvas = Image.new("RGBA", (112, 124), (255, 0, 255, 0))
        canvas.alpha_composite(image, ((112 - image.width) // 2, 124 - image.height))
        return canvas

    def _clean_chroma_edges(self, image: "Image.Image") -> "Image.Image":
        # Community Codex pet sheets sometimes carry compressed magenta key pixels
        # around transparent edges. Remove them before tkinter scales the frame.
        image = image.convert("RGBA")
        def clean_pixel(pixel: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            r, g, b, a = pixel
            # Pure #ff00ff often becomes a family of purple edge pixels after
            # webp compression, so treat saturated purple as removable key.
            chroma_family = r > 120 and b > 120 and g < 120 and abs(r - b) < 95
            barely_visible = a < 28
            return (0, 0, 0, 0) if chroma_family or barely_visible else pixel

        cleaned = [clean_pixel(pixel) for pixel in image.getdata()]
        image.putdata(cleaned)
        return image

    def tk_frames(self, animation: str) -> list["ImageTk.PhotoImage"]:
        if animation not in self.frames:
            if animation == "sleeping":
                raw = self._sleeping_frames()
            else:
                raw = self.raw_frames.get(animation) or self.raw_frames.get("idle") or []
            self.frames[animation] = [ImageTk.PhotoImage(f) for f in raw]
        return self.frames[animation]

    def _sleeping_frames(self) -> list["Image.Image"]:
        idle = self.raw_frames.get("idle") or []
        if not idle:
            return self.raw_frames.get("sleeping") or []

        frames = []
        for frame in idle[:4]:
            sleeping = frame.rotate(90, expand=True, resample=Image.Resampling.NEAREST)
            sleeping.thumbnail((112, 86), Image.Resampling.NEAREST)
            canvas = Image.new("RGBA", (112, 124), (255, 0, 255, 0))
            canvas.alpha_composite(sleeping, ((112 - sleeping.width) // 2, 124 - sleeping.height - 10))
            frames.append(canvas)
        return frames


class CompanionPet:
    def __init__(self, app: "DesktopPet", pet_id: str, x: int | None = None, y: int | None = None) -> None:
        self.app = app
        self.pet_id = pet_id
        self.root = tk.Toplevel(app.root)
        self.root.title(f"{APP_NAME} - {pet_id}")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT)
        self.root.wm_attributes("-transparentcolor", TRANSPARENT)
        self.canvas = tk.Canvas(self.root, width=128, height=144, bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()

        self.sprite_bank = SpriteBank(pet_id)
        self.frame_index = 0
        self.walk_target = None
        self.drag_offset = None
        self.drag_start = None
        self.drag_moved = False
        self.dance_until = 0.0
        self.phrases = pick_phrase_sample(pet_id)
        self.phrase = self.next_phrase()
        self.next_phrase_at = time.time() + random.randint(5, 11)

        if x is None:
            x = random.randint(30, max(30, self.root.winfo_screenwidth() - 190))
        if y is None:
            y = random.randint(60, max(60, self.root.winfo_screenheight() - 220))
        self.root.geometry(f"+{x}+{y}")

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label=f"Remove {pet_id}", command=self.remove)
        self.menu.add_command(label="Play", command=self.play)

        self.canvas.bind("<Button-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.stop_drag)
        self.canvas.bind("<Button-3>", self.show_menu)

    def position(self) -> tuple[int, int]:
        return self.root.winfo_x(), self.root.winfo_y()

    def next_phrase(self) -> str:
        if not self.phrases:
            self.phrases = pick_phrase_sample(self.pet_id)
        return random.choice(self.phrases)

    def reload_phrases(self) -> None:
        self.phrases = pick_phrase_sample(self.pet_id)
        self.phrase = self.next_phrase()
        self.next_phrase_at = time.time() + random.randint(5, 11)

    def tick(self, now: float) -> None:
        self.maybe_walk()
        animation = self.choose_animation()
        self.draw(animation)
        if now >= self.next_phrase_at:
            self.phrase = self.next_phrase()
            self.next_phrase_at = now + random.randint(6, 12)

    def choose_animation(self) -> str:
        if time.time() < self.dance_until:
            return "playing"
        if self.walk_target:
            return "running-right" if self.walk_target[0] > self.root.winfo_x() else "running-left"
        return "idle"

    def maybe_walk(self) -> None:
        if time.time() < self.dance_until:
            return
        if self.drag_offset:
            return
        x, y = self.position()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()

        if not self.walk_target and random.random() < 0.02:
            self.walk_target = (
                random.randint(20, max(20, sw - 190)),
                random.randint(40, max(40, sh - 220)),
            )

        if self.walk_target:
            tx, ty = self.walk_target
            dx, dy = tx - x, ty - y
            dist = math.hypot(dx, dy)
            if dist < 6:
                self.walk_target = None
            else:
                step = min(4, dist)
                x = int(x + dx / dist * step)
                y = int(y + dy / dist * step)

        x, y = self.app.avoid_crowding(self, x, y)
        self.root.geometry(f"+{x}+{y}")

    def draw(self, animation: str) -> None:
        self.canvas.delete("all")
        if self.sprite_bank.loaded:
            frames = self.sprite_bank.tk_frames(animation)
            if frames:
                self.frame_index = (self.frame_index + 1) % len(frames)
                self.canvas.create_image(64, 82, image=frames[self.frame_index])
            else:
                self.draw_label_fallback()
        else:
            self.draw_label_fallback()
        self.canvas.create_text(64, 10, text=self.phrase, fill="#333333", font=("Segoe UI", 8, "bold"))

    def draw_label_fallback(self) -> None:
        self.canvas.create_oval(32, 38, 96, 112, fill="#94d07a", outline="#202020", width=3)
        self.canvas.create_text(64, 74, text=self.pet_id[:8], fill="#202020", font=("Segoe UI", 8, "bold"))

    def play(self) -> None:
        self.walk_target = (random.randint(20, self.root.winfo_screenwidth() - 190), self.root.winfo_y())
        self.dance_until = time.time() + 2.0

    def bump_dance(self) -> None:
        self.walk_target = None
        self.dance_until = time.time() + 2.5
        self.phrase = random.choice(["Dance!", "Boop.", "Hello!", "Together!"])
        self.next_phrase_at = self.dance_until + 2

    def start_drag(self, event) -> None:
        self.drag_offset = (event.x, event.y)
        self.drag_start = (self.root.winfo_pointerx(), self.root.winfo_pointery())
        self.drag_moved = False
        self.walk_target = None

    def drag(self, event) -> None:
        if not self.drag_offset:
            return
        if self.drag_start:
            dx = self.root.winfo_pointerx() - self.drag_start[0]
            dy = self.root.winfo_pointery() - self.drag_start[1]
            if math.hypot(dx, dy) > 4:
                self.drag_moved = True
        ox, oy = self.drag_offset
        self.root.geometry(f"+{self.root.winfo_pointerx() - ox}+{self.root.winfo_pointery() - oy}")

    def stop_drag(self, _event=None) -> None:
        self.drag_offset = None
        self.drag_start = None

    def show_menu(self, event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def remove(self) -> None:
        self.app.remove_companion(self)

    def destroy(self) -> None:
        self.root.destroy()


class DesktopPet:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT)
        self.root.wm_attributes("-transparentcolor", TRANSPARENT)

        self.canvas = tk.Canvas(self.root, width=128, height=144, bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()

        self.state = self.load_state()
        self.pet_id = self.state.get("pet_id") or self.first_pet_id()
        self.stats = PetStats(**self.state.get("stats", {}))
        self.stats.degrade(max(0, time.time() - self.stats.last_seen))

        self.sprite_bank = SpriteBank(self.pet_id)
        self.animation = "idle"
        self.frame_index = 0
        self.image_item = None
        self.walk_target = None
        self.drag_offset = None
        self.drag_start = None
        self.drag_moved = False
        self.sleeping_until = 0.0
        self.action_until = 0.0
        self.action_animation = None
        self.dance_until = 0.0
        self.last_tick = time.time()
        self.last_save = 0.0
        self.hover_stats = False
        self.phrases = pick_phrase_sample(self.pet_id)
        self.phrase = self.next_phrase()
        self.next_phrase_at = time.time() + 6
        self.companions: list[CompanionPet] = []

        x = int(self.state.get("x", self.root.winfo_screenwidth() - 220))
        y = int(self.state.get("y", self.root.winfo_screenheight() - 240))
        self.root.geometry(f"+{x}+{y}")

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Feed", command=self.feed)
        self.menu.add_command(label="Play", command=self.play)
        self.menu.add_command(label="Sleep", command=self.sleep)
        self.menu.add_command(label="Stats", command=self.show_stats)
        self.menu.add_command(label="Revive", command=self.revive)
        self.menu.add_separator()
        self.menu.add_command(label="Change Pet", command=self.show_pet_menu)
        self.menu.add_command(label="Companions", command=self.show_companion_menu)
        self.menu.add_command(label="Pet Settings", command=self.show_pet_settings)
        self.menu.add_command(label="Help / About", command=self.show_about)
        self.menu.add_command(label="Hide", command=self.hide)
        self.menu.add_command(label="Quit", command=self.quit)

        self.canvas.bind("<Button-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.pet)
        self.canvas.bind("<Button-3>", self.show_menu)
        self.canvas.bind("<Enter>", self.show_hover_stats)
        self.canvas.bind("<Leave>", self.hide_hover_stats)

        self.tray_icon = None
        self.start_tray()
        self.restore_companions()
        self.tick()
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

    def first_pet_id(self) -> str | None:
        pet_ids = installed_pet_ids()
        return pet_ids[0] if pet_ids else None

    def load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def save_state(self) -> None:
        self.stats.last_seen = time.time()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        data = {
            "pet_id": self.pet_id,
            "x": x,
            "y": y,
            "stats": self.stats.__dict__,
            "companions": [
                {"pet_id": c.pet_id, "x": c.root.winfo_x(), "y": c.root.winfo_y()} for c in self.companions
            ],
        }
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def choose_animation(self) -> str:
        if not self.stats.alive:
            return "sad"
        if time.time() < self.dance_until:
            return "playing"
        if self.action_animation and time.time() < self.action_until:
            return self.action_animation
        self.action_animation = None
        if time.time() < self.sleeping_until:
            return "sleeping"
        if self.walk_target:
            return "running-right" if self.walk_target[0] > self.root.winfo_x() else "running-left"
        return self.stats.mood()

    def tick(self) -> None:
        now = time.time()
        self.stats.degrade(max(0.0, now - self.last_tick))
        self.last_tick = now
        self.maybe_walk()
        self.animation = self.choose_animation()
        self.draw()
        for companion in list(self.companions):
            companion.tick(now)
        if now - self.last_save > 5:
            self.save_state()
            self.last_save = now
        if now >= self.next_phrase_at:
            self.phrase = self.next_phrase()
            self.next_phrase_at = now + random.randint(6, 12)
        self.root.after(140, self.tick)

    def maybe_walk(self) -> None:
        if time.time() < self.dance_until:
            return
        if self.drag_offset or time.time() < self.sleeping_until or not self.stats.alive:
            return

        x, y = self.root.winfo_x(), self.root.winfo_y()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()

        if not self.walk_target and random.random() < 0.015:
            self.walk_target = (
                random.randint(20, max(20, sw - 190)),
                random.randint(30, max(30, sh - 220)),
            )

        if self.walk_target:
            tx, ty = self.walk_target
            dx, dy = tx - x, ty - y
            dist = math.hypot(dx, dy)
            if dist < 6:
                self.walk_target = None
            else:
                step = min(5, dist)
                nx, ny = self.avoid_crowding(self, int(x + dx / dist * step), int(y + dy / dist * step))
                self.root.geometry(f"+{nx}+{ny}")

    def occupied_positions(self, exclude=None) -> list[tuple[int, int]]:
        positions = []
        if exclude is not self:
            positions.append((self.root.winfo_x(), self.root.winfo_y()))
        for companion in self.companions:
            if companion is not exclude:
                positions.append(companion.position())
        return positions

    def avoid_crowding(self, actor, x: int, y: int) -> tuple[int, int]:
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        for ox, oy in self.occupied_positions(exclude=actor):
            dx, dy = x - ox, y - oy
            dist = math.hypot(dx, dy)
            if 0 < dist < 88:
                if dist < 50:
                    self.start_bump_dance(actor)
                push = int((88 - dist) / 7) + 1
                x += int(dx / dist * push)
                y += int(dy / dist * push)
                if getattr(actor, "walk_target", None) and dist < 55:
                    actor.walk_target = None
        x = max(0, min(x, sw - 150))
        y = max(0, min(y, sh - 170))
        return x, y

    def start_bump_dance(self, actor) -> None:
        now = time.time()
        if now < getattr(actor, "dance_until", 0):
            return
        actor.dance_until = now + 2.5
        actor.walk_target = None
        if actor is self:
            self.action_animation = "playing"
            self.action_until = actor.dance_until
            self.phrase = random.choice(["Dance!", "Boop.", "Together!"])
            self.next_phrase_at = actor.dance_until + 2
        elif hasattr(actor, "bump_dance"):
            actor.bump_dance()

    def draw(self) -> None:
        self.canvas.delete("all")
        if self.sprite_bank.loaded:
            frames = self.sprite_bank.tk_frames(self.animation)
            if frames:
                self.frame_index = (self.frame_index + 1) % len(frames)
                self.image_item = self.canvas.create_image(64, 82, image=frames[self.frame_index])
                self.draw_status_bar()
                return
        self.draw_fallback_pet()
        self.draw_status_bar()

    def draw_fallback_pet(self) -> None:
        age_color = "#8cc7ff" if self.stats.age < 30 else "#94d07a" if self.stats.age < 70 else "#d0a36f"
        mood = self.animation
        eye = "#222222"
        mouth = "smile"
        if mood in {"sad", "hungry"}:
            mouth = "sad"
        if mood == "sleeping":
            eye = "#777777"

        self.canvas.create_oval(32, 38, 96, 112, fill=age_color, outline="#202020", width=3)
        self.canvas.create_oval(22, 50, 45, 80, fill=age_color, outline="#202020", width=3)
        self.canvas.create_oval(83, 50, 106, 80, fill=age_color, outline="#202020", width=3)
        self.canvas.create_oval(47, 62, 56, 72, fill=eye, outline=eye)
        self.canvas.create_oval(73, 62, 82, 72, fill=eye, outline=eye)
        if mouth == "smile":
            self.canvas.create_arc(52, 72, 76, 92, start=200, extent=140, outline="#202020", width=3)
        else:
            self.canvas.create_arc(52, 82, 76, 100, start=20, extent=140, outline="#202020", width=3)
        if mood == "playing":
            self.canvas.create_oval(92, 26, 112, 46, fill="#ffd966", outline="#202020", width=2)

    def draw_status_bar(self) -> None:
        if self.hover_stats:
            lines = [
                f"Hunger {self.stats.hunger:.0f}",
                f"Happy {self.stats.happiness:.0f}",
                f"Energy {self.stats.energy:.0f}",
            ]
            self.canvas.create_rectangle(22, 2, 106, 43, fill="#fffdf5", outline="#d6cfbd")
            self.canvas.create_text(64, 22, text="\n".join(lines), fill="#333333", font=("Segoe UI", 8))
            return

        if not self.stats.alive:
            text = "Please help..."
        elif self.animation == "hungry":
            text = "I'm hungry."
        elif self.animation == "sleeping":
            text = "Zzz..."
        elif self.animation == "sad":
            text = "Stay with me?"
        else:
            text = self.phrase
        self.canvas.create_text(64, 10, text=text, fill="#333333", font=("Segoe UI", 8, "bold"))

    def next_phrase(self) -> str:
        if not self.phrases:
            self.phrases = pick_phrase_sample(self.pet_id)
        return random.choice(self.phrases)

    def reload_phrases(self) -> None:
        self.phrases = pick_phrase_sample(self.pet_id)
        self.phrase = self.next_phrase()
        self.next_phrase_at = time.time() + 6
        for companion in self.companions:
            if companion.pet_id == self.pet_id:
                companion.reload_phrases()

    def show_hover_stats(self, _event=None) -> None:
        self.hover_stats = True

    def hide_hover_stats(self, _event=None) -> None:
        self.hover_stats = False

    def start_drag(self, event) -> None:
        self.drag_offset = (event.x, event.y)
        self.drag_start = (self.root.winfo_pointerx(), self.root.winfo_pointery())
        self.drag_moved = False
        self.walk_target = None

    def drag(self, event) -> None:
        if not self.drag_offset:
            return
        if self.drag_start:
            dx = self.root.winfo_pointerx() - self.drag_start[0]
            dy = self.root.winfo_pointery() - self.drag_start[1]
            if math.hypot(dx, dy) > 4:
                self.drag_moved = True
        ox, oy = self.drag_offset
        self.root.geometry(f"+{self.root.winfo_pointerx() - ox}+{self.root.winfo_pointery() - oy}")

    def pet(self, _event=None) -> None:
        self.drag_offset = None
        self.drag_start = None
        if self.drag_moved:
            self.drag_moved = False
            return
        self.stats.happiness = min(100, self.stats.happiness + 5)
        if self.stats.alive:
            self.animation = "happy"

    def feed(self) -> None:
        self.walk_target = None
        self.action_animation = "hungry"
        self.action_until = time.time() + 2.5
        self.stats.hunger = min(100, self.stats.hunger + 25)
        self.stats.happiness = min(100, self.stats.happiness + 4)

    def play(self) -> None:
        self.action_animation = "playing"
        self.action_until = time.time() + 3.0
        self.stats.happiness = min(100, self.stats.happiness + 20)
        self.stats.energy = max(0, self.stats.energy - 10)
        self.walk_target = (random.randint(20, self.root.winfo_screenwidth() - 190), self.root.winfo_y())

    def sleep(self) -> None:
        self.sleeping_until = time.time() + 20
        self.stats.energy = min(100, self.stats.energy + 30)

    def revive(self) -> None:
        if not self.stats.alive:
            self.stats.hunger = 50
            self.stats.happiness = 50
            self.stats.energy = 50
            self.stats.alive = True
            self.phrase = "I'm back!"
            self.next_phrase_at = time.time() + 4
            self.save_state()
        else:
            messagebox.showinfo(APP_NAME, "Your pet is already okay.")

    def show_stats(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            f"Pet: {self.pet_id or 'fallback'}\n"
            f"Hunger: {self.stats.hunger:.0f}/100\n"
            f"Happiness: {self.stats.happiness:.0f}/100\n"
            f"Energy: {self.stats.energy:.0f}/100\n"
            f"Age: {self.stats.age:.1f}/100\n"
            f"Alive: {'yes' if self.stats.alive else 'very sad'}",
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME}\n"
            f"Version: {APP_VERSION}\n"
            f"Date created: {APP_CREATED}\n"
            f"{APP_AUTHORS}\n\n"
            "Basic controls:\n"
            "- Left-click: pet the character\n"
            "- Drag: move the pet\n"
            "- Hover: show hunger, happiness, and energy\n"
            "- Right-click: open care/options menu\n\n"
            "Main menu:\n"
            "- Feed, Play, Sleep, Stats, Revive\n"
            "- Change Pet: switch installed Codex pets\n"
            "- Companions: add extra pets to wander together\n"
            "- Pet Settings: choose Japanese, English, or Custom phrases\n"
            "- Hide or Quit from the menu or tray icon\n\n"
            "Pets are loaded from ~/.codex/pets.",
        )

    def show_menu(self, event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def show_pet_menu(self) -> None:
        menu = tk.Toplevel(self.root)
        menu.title("Change Pet")
        menu.attributes("-topmost", True)
        menu.resizable(False, False)
        tk.Label(menu, text="Choose a pet").pack(padx=16, pady=(14, 8))
        pet_ids = installed_pet_ids()
        if not pet_ids:
            tk.Label(menu, text="No Codex pets found.").pack(padx=16, pady=8)
        for pet_id in pet_ids:
            tk.Button(menu, text=pet_id, command=lambda p=pet_id: self.change_pet(p, menu)).pack(
                fill="x", padx=16, pady=4
            )

    def show_companion_menu(self) -> None:
        menu = tk.Toplevel(self.root)
        menu.title("Companions")
        menu.attributes("-topmost", True)
        menu.resizable(False, False)
        tk.Label(menu, text="Toggle companion pets").pack(padx=16, pady=(14, 8))
        pet_ids = installed_pet_ids()
        if not pet_ids:
            tk.Label(menu, text="No Codex pets found.").pack(padx=16, pady=8)
        for pet_id in pet_ids:
            active = any(c.pet_id == pet_id for c in self.companions)
            label = f"{'Remove' if active else 'Add'} {pet_id}"
            tk.Button(menu, text=label, command=lambda p=pet_id, w=menu: self.toggle_companion(p, w)).pack(
                fill="x", padx=16, pady=4
            )
        tk.Button(menu, text="Remove all companions", command=lambda w=menu: self.clear_companions(w)).pack(
            fill="x", padx=16, pady=(10, 14)
        )

    def show_pet_settings(self) -> None:
        if not self.pet_id:
            messagebox.showinfo(APP_NAME, "No Codex pet is selected.")
            return

        directory = pet_dir(self.pet_id)
        if not directory:
            messagebox.showinfo(APP_NAME, "No Codex pet folder was found.")
            return

        current_language, current_phrases = phrase_pool_for_pet(self.pet_id)
        if current_language not in {"jp", "en", "custom"}:
            current_language = "jp"

        window = tk.Toplevel(self.root)
        window.title("Pet Settings")
        window.attributes("-topmost", True)
        window.resizable(True, True)
        window.geometry("360x360")

        tk.Label(window, text=f"Pet: {self.pet_id}", font=("Segoe UI", 11, "bold")).pack(padx=14, pady=(12, 6))

        language_var = tk.StringVar(value=current_language)
        radio_frame = tk.Frame(window)
        radio_frame.pack(fill="x", padx=14)

        text_frame = tk.Frame(window)
        text_frame.pack(fill="both", expand=True, padx=14, pady=8)
        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        text = tk.Text(text_frame, height=10, wrap="word", yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text.yview)

        custom_prefill = list(current_phrases)

        def set_text(lines: list[str], editable: bool) -> None:
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", "\n".join(lines))
            text.configure(state="normal" if editable else "disabled")

        def selected_lines() -> list[str]:
            selected = language_var.get()
            if selected == "en":
                return PHRASES_EN
            if selected == "custom":
                custom = read_custom_phrases(self.pet_id)
                current_text = [line.strip() for line in text.get("1.0", "end").splitlines() if line.strip()]
                return custom or current_text or custom_prefill
            return PHRASES_JP

        def refresh_text() -> None:
            set_text(selected_lines(), language_var.get() == "custom")

        for value, label in (("jp", "Japanese"), ("en", "English"), ("custom", "Custom")):
            tk.Radiobutton(radio_frame, text=label, variable=language_var, value=value, command=refresh_text).pack(
                side="left", padx=(0, 12)
            )

        refresh_text()

        def save_settings() -> None:
            selected = language_var.get()
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "petconfig.json").write_text(
                json.dumps({"phrase_language": selected}, indent=2),
                encoding="utf-8",
            )

            phrases_path = directory / "phrases.json"
            if selected == "custom":
                lines = [line.strip() for line in text.get("1.0", "end").splitlines() if line.strip()]
                if not lines:
                    messagebox.showinfo(APP_NAME, "Custom phrases need at least one line.")
                    return
                phrases_path.write_text(json.dumps(lines, indent=2, ensure_ascii=False), encoding="utf-8")
            elif phrases_path.exists():
                phrases_path.unlink()

            self.reload_phrases()
            messagebox.showinfo(APP_NAME, "Pet settings saved.")
            window.destroy()

        button_frame = tk.Frame(window)
        button_frame.pack(fill="x", padx=14, pady=(0, 12))
        tk.Button(button_frame, text="Save", command=save_settings).pack(side="right")
        tk.Button(button_frame, text="Cancel", command=window.destroy).pack(side="right", padx=(0, 8))

    def restore_companions(self) -> None:
        for item in self.state.get("companions", []):
            pet_id = item.get("pet_id")
            if pet_id and (PETS_DIR / pet_id / "pet.json").exists():
                self.companions.append(CompanionPet(self, pet_id, item.get("x"), item.get("y")))

    def toggle_companion(self, pet_id: str, window: tk.Toplevel | None = None) -> None:
        for companion in list(self.companions):
            if companion.pet_id == pet_id:
                self.remove_companion(companion)
                if window:
                    window.destroy()
                return
        self.companions.append(CompanionPet(self, pet_id))
        self.save_state()
        if window:
            window.destroy()

    def remove_companion(self, companion: CompanionPet) -> None:
        if companion in self.companions:
            self.companions.remove(companion)
        companion.destroy()
        self.save_state()

    def clear_companions(self, window: tk.Toplevel | None = None) -> None:
        for companion in list(self.companions):
            self.remove_companion(companion)
        if window:
            window.destroy()

    def change_pet(self, pet_id: str, window: tk.Toplevel) -> None:
        self.pet_id = pet_id
        self.sprite_bank = SpriteBank(pet_id)
        self.frame_index = 0
        self.reload_phrases()
        self.save_state()
        window.destroy()

    def hide(self) -> None:
        self.root.withdraw()
        for companion in self.companions:
            companion.root.withdraw()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        for companion in self.companions:
            companion.root.deiconify()
            companion.root.lift()

    def quit(self) -> None:
        self.save_state()
        for companion in list(self.companions):
            companion.destroy()
        self.companions.clear()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()

    def start_tray(self) -> None:
        if not pystray or not Image:
            return
        icon_image = Image.new("RGB", (64, 64), "#f5f0df")
        draw = ImageDraw.Draw(icon_image)
        draw.ellipse((12, 12, 52, 52), fill="#8cc7ff", outline="#222222", width=3)
        draw.ellipse((24, 29, 29, 34), fill="#222222")
        draw.ellipse((36, 29, 41, 34), fill="#222222")
        draw.arc((25, 34, 40, 48), 20, 160, fill="#222222", width=2)

        def run_tray() -> None:
            self.tray_icon = pystray.Icon(
                APP_NAME,
                icon_image,
                APP_NAME,
                menu=pystray.Menu(
                    pystray.MenuItem("Show", lambda: self.root.after(0, self.show)),
                    pystray.MenuItem("Hide", lambda: self.root.after(0, self.hide)),
                    pystray.MenuItem("Quit", lambda: self.root.after(0, self.quit)),
                ),
            )
            self.tray_icon.run()

        threading.Thread(target=run_tray, daemon=True).start()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    if Image is None:
        raise SystemExit("Pillow is required. Install with: python -m pip install pillow pystray")
    DesktopPet().run()


if __name__ == "__main__":
    main()
