# Pet Evolved

Pet Evolved is a small Windows desktop pet app written in Python. It can load
installed Codex pet sprites from `~/.codex/pets`, then let the pet wander around
the desktop like a lightweight Tamagotchi-style companion.

Version: `0.2.0`

Date created: `2026-05-07`

Authors: Made by Codex, supervised by Dzonas

## Requirements

- Windows 11
- Python 3.10 or newer
- Codex installed
- One or more Codex pets installed in:

```text
C:\Users\<you>\.codex\pets
```

Each pet folder should contain:

```text
pet.json
spritesheet.webp
```

or:

```text
pet.json
spritesheet.png
```

## Python Libraries

This app uses the Python standard library plus two small packages:

```text
Pillow
pystray
```

Install them with:

```powershell
python -m pip install pillow pystray
```

`tkinter` is also used, but it is normally included with the standard Windows
Python installer.

## Run

From the folder containing `desktop_pet.py`:

```powershell
python desktop_pet.py
```

The pet should appear as a frameless always-on-top desktop window.

## Controls

- Left-click: pet the character
- Drag: move the pet manually
- Hover: show Hunger, Happiness, and Energy
- Right-click: open the care menu

The right-click menu includes:

- Feed
- Play
- Sleep
- Stats
- Change Pet
- Companions
- Help / About
- Hide
- Quit

There is also a small system tray icon with Show, Hide, and Quit actions.

## Multiple Pets

Use **Right-click → Companions** to add or remove extra installed Codex pets.

The app runs all pets inside one Python process instead of starting multiple
copies. This lets pets share their screen positions and gently steer away from
each other while wandering.

Companion pets can also be dragged manually. Right-click a companion pet to
remove it or make it play.

When pets bump into each other, they briefly stop and play a small happy/playing
"bump dance" before wandering again.

## Codex Pet Support

The app looks for pets in:

```text
~/.codex/pets
```

For example:

```text
C:\Users\<you>\.codex\pets\rem
C:\Users\<you>\.codex\pets\gojo
```

It supports the common Codex pet atlas format:

```text
1536 x 1872 spritesheet
192 x 208 cells
8 columns x 9 rows
```

It also has basic support for simple horizontal frame strips when `pet.json`
contains values like `frameWidth`, `frameHeight`, or `frameCount`.

If no compatible pet is found, the app falls back to a simple drawn tkinter
sprite.

## Saved State

Pet state is saved here:

```text
~/.codex/desktop-pet-state.json
```

The saved state includes:

- selected pet
- companion pets
- window position
- hunger
- happiness
- energy
- age
- last seen time

If the app is closed for a while, the pet will be hungrier or lower energy when
you reopen it.

## Notes

- This is a lightweight prototype, not an official Codex feature.
- Some community spritesheets may have magenta or violet edge artifacts. The app
  includes a cleanup pass, but some sprites may still look better than others.
- If a pet seems too large or too small, adjust the thumbnail size in
  `SpriteBank._fit`.
