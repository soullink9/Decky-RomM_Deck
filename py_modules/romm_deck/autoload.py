"""Turn off "resume from the last save state when a game starts" in every emulator that has it.

Emulators with no such option (Dolphin, melonDS, Azahar, Ryujinx, Cemu, RPCS3...) aren't listed.
To add one: a line in SETTINGS with its config file, [section] (None if it has none), key, "off" value,
and whether the emulator treats a missing key as on.
"""
import re
from pathlib import Path

from .config import HOME

FP = HOME / ".var/app"  # flatpak app data
RA = FP / "org.libretro.RetroArch/config/retroarch"

SETTINGS = [
    # emulator, file, section, key, off, missing means on
    ("RetroArch", RA / "retroarch.cfg", None, "savestate_auto_load", '"false"', False),
    ("PPSSPP", FP / "org.ppsspp.PPSSPP/config/ppsspp/PSP/SYSTEM/ppsspp.ini", "General", "AutoLoadSaveState", "0", False),
    ("Flycast", FP / "org.flycast.Flycast/config/flycast/emu.cfg", "config", "Dreamcast.AutoLoadState", "no", False),
    # DuckStation and PCSX2 resume from a state they save when you quit; turning that off stops it
    ("DuckStation", HOME / ".local/share/duckstation/settings.ini", "Main", "SaveStateOnExit", "false", True),
    ("PCSX2", HOME / ".config/PCSX2/inis/PCSX2.ini", "EmuCore", "SaveStateOnShutdown", "false", False),
    ("PCSX2", FP / "net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini", "EmuCore", "SaveStateOnShutdown", "false", False),
]
# EmuDeck's "auto save" setting turns RetroArch's back on whenever EmuDeck updates or resets it
EMUDECK_SETTINGS = [HOME / ".config/EmuDeck/settings.sh", HOME / "emudeck/settings.sh"]


def _all_settings():
    """SETTINGS plus RetroArch's per-core, per-folder and per-game overrides that set it."""
    out = list(SETTINGS)
    if (RA / "config").is_dir():
        for cfg in sorted((RA / "config").rglob("*.cfg")):
            if "savestate_auto_load" in cfg.read_text(errors="ignore"):
                out.append((f"RetroArch ({cfg.parent.name})", cfg, None, "savestate_auto_load", '"false"', False))
    return [s for s in out if s[1].is_file()]


def _is_on(file, section, key, off, missing_on):
    value = _read(file, section, key)
    if value is None:
        return missing_on
    return value.strip('"').lower() != off.strip('"').lower()


def status():
    """Emulators that still resume from a state on start: [name]."""
    on = []
    for name, file, section, key, off, missing_on in _all_settings():
        if _is_on(file, section, key, off, missing_on) and name not in on:
            on.append(name)
    return on


def turn_off():
    """Switch it off everywhere. Returns the emulators that were changed."""
    changed = []
    for name, file, section, key, off, missing_on in _all_settings():
        if not _is_on(file, section, key, off, missing_on):
            continue
        _write(file, section, key, off)
        if name not in changed:
            changed.append(name)
    for f in EMUDECK_SETTINGS:
        if f.is_file():
            text = f.read_text()
            if re.search(r"^RAautoSave=true", text, re.M):
                f.write_text(re.sub(r"^RAautoSave=true", "RAautoSave=false", text, flags=re.M))
    return changed


# ---------- minimal ini / cfg editing (keeps every other line as it is) ----------

def _lines(file):
    raw = file.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig", errors="ignore").splitlines(), bom


def _find(lines, section, key):
    """(index of the key's line in that section, or None;  where to add it if missing)."""
    current, end = None, len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section is not None and current == section:
                end = i  # reached the next section
                break
            current = stripped[1:-1]
        elif current == section and re.match(rf"^\s*{re.escape(key)}\s*=", line):
            return i, i
    while end > 0 and not lines[end - 1].strip():  # add it before any blank lines
        end -= 1
    return None, end


def _read(file, section, key):
    lines, _ = _lines(file)
    i, _ = _find(lines, section, key)
    return lines[i].split("=", 1)[1].strip() if i is not None else None


def _write(file, section, key, value):
    lines, bom = _lines(file)
    i, insert = _find(lines, section, key)
    new = f"{key} = {value}"
    if i is not None:
        lines[i] = new
    elif section is None or any(line.strip() == f"[{section}]" for line in lines):
        lines.insert(insert, new)
    else:
        lines += ["", f"[{section}]", new]
    Path(file).write_text(("﻿" if bom else "") + "\n".join(lines) + "\n", encoding="utf-8")
