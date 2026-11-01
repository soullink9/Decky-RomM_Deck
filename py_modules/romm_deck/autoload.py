"""Turn off "resume from the last save state when a game starts" in every emulator that has it.

Emulators with no such option (Dolphin, melonDS, Azahar, Ryujinx, Cemu, RPCS3...) aren't listed.
To add one: a Setting in SETTINGS. Files are edited one line at a time (see ini.py), so everything
else in them stays as the emulator wrote it.
"""
import re
from typing import NamedTuple

from . import ini
from .config import HOME


class Setting(NamedTuple):
    """One emulator setting that makes a game resume from a save state when it starts."""
    emulator: str           # the name shown in the panel
    file: object            # its settings file (a Path)
    section: object         # the [section] the key is in, or None for a file without sections
    key: str
    off: str                # the value that turns it off, written exactly like this
    missing_means_on: bool  # does the emulator resume when the key isn't in the file at all?


FP = HOME / ".var/app"  # flatpak app data
RA = FP / "org.libretro.RetroArch/config/retroarch"

SETTINGS = [
    Setting("RetroArch", RA / "retroarch.cfg", None, "savestate_auto_load", '"false"', False),
    Setting("PPSSPP", FP / "org.ppsspp.PPSSPP/config/ppsspp/PSP/SYSTEM/ppsspp.ini", "General", "AutoLoadSaveState", "0", False),
    Setting("Flycast", FP / "org.flycast.Flycast/config/flycast/emu.cfg", "config", "Dreamcast.AutoLoadState", "no", False),
    # DuckStation and PCSX2 resume from a state they save when you quit; turning that off stops it
    Setting("DuckStation", HOME / ".local/share/duckstation/settings.ini", "Main", "SaveStateOnExit", "false", True),
    Setting("PCSX2", HOME / ".config/PCSX2/inis/PCSX2.ini", "EmuCore", "SaveStateOnShutdown", "false", False),
    Setting("PCSX2", FP / "net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini", "EmuCore", "SaveStateOnShutdown", "false", False),
]
# EmuDeck's "auto save" setting turns RetroArch's back on whenever EmuDeck updates or resets it
EMUDECK_SETTINGS = [HOME / ".config/EmuDeck/settings.sh", HOME / "emudeck/settings.sh"]


def _all_settings():
    """SETTINGS plus RetroArch's per-core, per-folder and per-game overrides that set it (an
    override wins over retroarch.cfg, so each one has to be turned off too). Only files that exist."""
    out = list(SETTINGS)
    overrides = RA / "config"
    if overrides.is_dir():
        for cfg in sorted(overrides.rglob("*.cfg")):
            if "savestate_auto_load" in cfg.read_text(errors="ignore"):
                out.append(Setting(f"RetroArch ({cfg.parent.name})", cfg, None, "savestate_auto_load", '"false"', False))
    return [s for s in out if s.file.is_file()]


def _is_on(setting):
    """Does this setting still make games resume from a state? Quotes and case don't matter
    ("false", "False" and \"false\" are all off)."""
    value = ini.get_value(setting.file, setting.section, setting.key)
    if value is None:
        return setting.missing_means_on
    return value.strip('"').lower() != setting.off.strip('"').lower()


def status():
    """Emulators that still resume from a state on start: [name], each once."""
    on = []
    for setting in _all_settings():
        if _is_on(setting) and setting.emulator not in on:
            on.append(setting.emulator)
    return on


def turn_off():
    """Switch it off everywhere. Returns the emulators that were changed, each once."""
    changed = []
    for setting in _all_settings():
        if not _is_on(setting):
            continue
        ini.set_value(setting.file, setting.section, setting.key, setting.off)
        if setting.emulator not in changed:
            changed.append(setting.emulator)
    for f in EMUDECK_SETTINGS:
        if f.is_file():
            text = f.read_text()
            if re.search(r"^RAautoSave=true", text, re.M):
                f.write_text(re.sub(r"^RAautoSave=true", "RAautoSave=false", text, flags=re.M))
    return changed
