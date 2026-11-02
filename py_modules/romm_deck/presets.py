"""Controller presets: per platform, off unless turned on. Each one changes a few emulator settings
while a game runs, and puts them back when it closes (also after a crash or power-off).

On a ROG Ally / Xbox Ally (X), "motion" presets:
  Switch (Ryujinx), Wii U (Cemu) and 3DS (Azahar) read motion from the plugin's own motion server
  (motion.py), which reads the Ally's motion itself (EmuDeck's Steam Deck motion server can't see
  it under InputPlumber). EmuDeck already points Cemu and Azahar at that address; the preset only
  sets it where it isn't. The motion is calibrated once from the game page (motion.calibrate).
On any device:
  Wii (Dolphin): use real Wii Remotes for all four players instead of emulated ones, and say whether
  Dolphin can use a Wii Remote sensor on USB (a DolphinBar in mode 4).

Every change is recorded first (settings/controller-backup.json), and after the game a setting is
only put back if it still has the preset's value, so a change you make in the emulator is kept.

To add a device: an entry in DEVICES. To add a platform: an entry in a "presets" list, with a
plan() that says which settings to change.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import config, ini, motion, procs
from .library import RYUJINX_CONFIGS

DMI = Path("/sys/class/dmi/id")  # the firmware's maker/model strings, for recognising the device
MOTION_SERVER = config.PLUGIN_DIR / "bin" / "romm_motion.py"
BACKUP = "controller-backup"  # settings/controller-backup.json while a preset is applied
STATUS = "controller-status"  # how the last game with a preset went, for the game page
# EmuDeck's Steam Deck motion server (SteamDeckGyroDSU), if the user installed it. It can't see
# the Ally's motion under InputPlumber, but while it runs it holds the motion port (26760), so it's
# paused for the length of a game that needs our server, then started again.
DECK_MOTION_SERVICE = "sdgyrodsu.service"

H, FP = config.HOME, config.HOME / ".var/app"  # home, and where flatpak apps keep their settings
CEMU_PROFILES = [H / ".config/Cemu/controllerProfiles/controller0.xml",
                 H / ".local/share/Cemu/controllerProfiles/controller0.xml",
                 FP / "info.cemu.Cemu/data/cemu/controllerProfiles/controller0.xml"]
AZAHAR_CONFIGS = [H / ".config/azahar-emu/qt-config.ini",
                  FP / "io.github.azahar.Azahar/config/azahar-emu/qt-config.ini"]
DOLPHIN_DIRS = [FP / "org.DolphinEmu.dolphin-emu/config/dolphin-emu", H / ".config/dolphin-emu"]

# What each emulator's setting looks like when it reads motion from our server (DSU, a.k.a. "CemuHook",
# the standard way emulators take motion from another program over UDP)
DSU_MOTION = {  # Ryujinx: a player's whole "motion" block
    "motion_backend": "CemuHook", "slot": 0, "alt_slot": 0, "mirror_input": False,
    "dsu_server_host": motion.HOST, "dsu_server_port": motion.PORT,
    "sensitivity": 100, "gyro_deadzone": 1, "enable_motion": True,
}
CEMU_DSU = f"""	<controller>
		<api>DSUController</api>
		<uuid>0</uuid>
		<display_name>RomM Deck motion</display_name>
		<motion>true</motion>
		<ip>{motion.HOST}</ip>
		<port>{motion.PORT}</port>
		<mappings />
	</controller>
"""
AZAHAR_DSU = "engine:cemuhookudp"  # Azahar: a profile's motion_device (address and port default to ours)
REAL_WIIMOTE = "2"  # Dolphin's [WiimoteN] Source: 0 none, 1 emulated, 2 real
# Dolphin talks to Wii Remotes on USB (a Mayflash DolphinBar in mode 4) through their raw HID device files.
# The kernel lists each one under /sys/class/hidraw with its bus and USB ids; the file itself is /dev/hidrawN.
HIDRAW, DEV = Path("/sys/class/hidraw"), Path("/dev")
USB_BUS = "0003"  # the bus number in HID_ID (Bluetooth is 0005)
WII_REMOTE_IDS = ("0000057E:00000306", "0000057E:00000330")  # Nintendo's ids: Wii Remote, Wii Remote Plus


# ---------- what each preset changes ----------

def _ryujinx_motion():
    """Ryujinx player 1 and handheld: motion from the plugin's motion server."""
    changes = []
    for path in RYUJINX_CONFIGS:
        cfg = _load_json(path)
        for i, entry in enumerate((cfg or {}).get("input_config") or []):
            if entry.get("player_index") in ("Player1", "Handheld"):
                changes.append(_change("ryujinx", path, i, entry.get("motion"), DSU_MOTION))
    return changes


def _cemu_motion():
    """Cemu player 1: add a motion source at 127.0.0.1:26760, unless it already reads one there
    (EmuDeck's profile does)."""
    changes = []
    for path in CEMU_PROFILES:
        if path.is_file() and not _cemu_has_dsu(path):
            changes.append(_change("cemu", path, None, None, CEMU_DSU))
    return changes


def _azahar_motion():
    """Azahar, every controller profile: motion from 127.0.0.1:26760 (EmuDeck already sets this)."""
    changes = []
    for path in AZAHAR_CONFIGS:
        if not path.is_file():
            continue
        size = ini.get_value(path, "Controls", "profiles\\size") or "1"
        profiles = int(size) if size.isdigit() else 1
        for n in range(1, profiles + 1):
            key = f"profiles\\{n}\\motion_device"
            current = ini.get_value(path, "Controls", key)
            # Qt's settings files mark a value still at its default with key\default=true, and Azahar
            # then ignores the value written next to it, so that flag has to be cleared as well.
            default = ini.get_value(path, "Controls", key + "\\default")
            if current is None or AZAHAR_DSU not in current or default == "true":
                changes.append(_change("ini", path, ["Controls", key], current, AZAHAR_DSU))
                changes.append(_change("ini", path, ["Controls", key + "\\default"], default, "false"))
    return changes


def _dolphin_real_wiimotes():
    """Dolphin: all four Wii Remotes real (not emulated), and keep looking for them, so pressing 1+2
    on a remote connects it."""
    changes = []
    for folder in DOLPHIN_DIRS:
        if not folder.is_dir():
            continue
        wiimotes, core = folder / "WiimoteNew.ini", folder / "Dolphin.ini"
        for n in range(1, 5):
            current = ini.get_value(wiimotes, f"Wiimote{n}", "Source")
            if current != REAL_WIIMOTE:
                changes.append(_change("ini", wiimotes, [f"Wiimote{n}", "Source"], current, REAL_WIIMOTE))
        current = ini.get_value(core, "Core", "WiimoteContinuousScanning")
        if current != "True":
            changes.append(_change("ini", core, ["Core", "WiimoteContinuousScanning"], current, "True"))
    return changes


def _usb_wii_remotes():
    """The Wii Remote slots on USB: (how many Dolphin can open, how many it can't).

    A DolphinBar only shows up as Wii Remotes in mode 4; in modes 1-3 it's a mouse, keyboard or gamepad,
    and Dolphin then has no real remote to connect, so the game gets nothing from it. Remotes on Bluetooth
    don't appear here: Dolphin finds those itself."""
    usable = blocked = 0
    try:
        entries = sorted(HIDRAW.iterdir())
    except OSError:
        return 0, 0  # no raw HID devices at all
    for entry in entries:
        ids = ""
        for line in _read(entry / "device" / "uevent").splitlines():
            if line.startswith("HID_ID="):
                ids = line[len("HID_ID="):].upper()
        bus, _, device_ids = ids.partition(":")
        if bus != USB_BUS or device_ids not in WII_REMOTE_IDS:
            continue
        # Dolphin runs as this same user, so it can open the file exactly when this process can
        if os.access(DEV / entry.name, os.R_OK | os.W_OK):
            usable += 1
        else:
            blocked += 1
    return usable, blocked


def _wii_remotes_running():
    """What the popup and the game page say during a Wii game: whether Dolphin can use a Wii Remote sensor
    on USB, so a remote that doesn't connect has a reason next to it."""
    usable, blocked = _usb_wii_remotes()
    if blocked:
        config.log.warning("Wii Remote sensor on USB: Dolphin can open %d slot(s), not %d", usable, blocked)
        return ("using real Wii Remotes, but Dolphin isn't allowed to open the Wii Remote sensor on USB "
                "(see Troubleshooting)")
    if usable:
        return "using real Wii Remotes on the USB sensor (press 1+2 on each to connect)"
    return "using real Wii Remotes (press 1+2 on each to connect; a DolphinBar has to be in mode 4)"


# The presets on offer. DEVICES: only on that handheld (recognised by its firmware's name);
# ANY_DEVICE: everywhere. Each preset: a label and description for the game page, whether it needs
# the motion server, plan(), which lists the settings to change for one game, and optionally running(),
# which says what's going on during the game (by default, that it's reading the Ally's motion).
ALLY_MOTION = "Motion and tilt from the Ally's own sensor"
DEVICES = {
    "rog-ally": {
        "matches": lambda name: "ally" in name.lower() and ("rog" in name.lower() or "asus" in name.lower()),
        "presets": {
            "switch": {"label": "Ally motion (gyro & tilt) for Switch", "motion": True, "plan": _ryujinx_motion,
                       "about": f"{ALLY_MOTION}. Your own Ryujinx motion settings come back when the game closes."},
            "wiiu": {"label": "Ally motion (gyro) for Wii U", "motion": True, "plan": _cemu_motion,
                     "about": f"{ALLY_MOTION}, as the GamePad's motion in Cemu. Your own Cemu controller "
                              "settings come back when the game closes."},
            "3ds": {"label": "Ally motion (gyro) for 3DS", "motion": True, "plan": _azahar_motion,
                    "about": f"{ALLY_MOTION}, as the 3DS's motion in Azahar. Your own Azahar settings come back "
                             "when the game closes."},
        },
    },
}
ANY_DEVICE = {
    "wii": {"label": "Use my real Wii Remotes", "motion": False, "plan": _dolphin_real_wiimotes,
            "about": "Dolphin uses real Wii Remotes for all four players instead of emulated ones; press 1+2 on "
                     "a remote to connect it. A DolphinBar has to be in mode 4. Your own Dolphin settings come "
                     "back when the game closes.",
            "running": _wii_remotes_running},
}


# ---------- what's available ----------

def device():
    """(device key, its name) for the handheld this is running on, or (None, name)."""
    name = " ".join(_read(DMI / f) for f in ("sys_vendor", "product_name", "board_name")).strip()
    for key, d in DEVICES.items():
        if d["matches"](name):
            return key, name
    return None, name


def preset_for(platform):
    """The preset for a platform (the plugin's system key, e.g. "switch") on this device, or None."""
    key, _ = device()
    return (DEVICES[key]["presets"].get(platform) if key else None) or ANY_DEVICE.get(platform)


def enabled(platform):
    """Turned on for this platform."""
    return bool(config.load("settings").get("controller_presets", {}).get(platform))


def set_enabled(platform, on):
    """Turn a platform's preset on or off. Off puts the emulator's settings back right away."""
    if on and not preset_for(platform):
        raise ValueError("There's no preset for this platform on this device")
    s = config.load("settings")
    s.setdefault("controller_presets", {})[platform] = bool(on)
    config.save("settings", s)
    if not on:
        restore()


def status(platform):
    """For the game page: is motion calibrated, and how did the last game go."""
    return {"calibrated": motion.calibrated(), "last": config.load(STATUS).get(platform, "")}


# ---------- around a game (bin/romm_launch.py) ----------

def apply(game, launcher_pid=None):
    """Before a game starts: undo anything left from last time, then apply its platform's preset.
    Returns None (preset off), or (ok, what to tell the user)."""
    restore()
    platform = game.get("system")
    if not enabled(platform):
        return None
    preset = _turned_on_preset(platform)
    if not preset:
        return None
    backup = {}
    if preset["motion"]:
        if not motion.calibrated():
            return _report(platform, False, "Not calibrated yet: press Calibrate motion on the game's page")
        if _systemctl("is-active", DECK_MOTION_SERVICE).strip() == "active":  # it would hold the motion port
            _systemctl("stop", DECK_MOTION_SERVICE)
            backup["_restart_deck_motion_service"] = True
        config.save(BACKUP, backup)
        ok, why = _start_server(launcher_pid or os.getpid(), backup)
        if not ok:
            restore()
            return _report(platform, False, why)
    changes = preset["plan"]()
    backup["_changes"] = changes
    config.save(BACKUP, backup)  # recorded before anything changes, so a crash midway is undone too
    for c in changes:
        _set(c, c["ours"])
    config.log.info("Controller preset on for %s (%s): %d settings changed", game["name"], platform, len(changes))
    running = preset["running"]() if "running" in preset else "reading the Ally's motion"
    return _report(platform, True, f"{preset['label']} · {running}")


def _turned_on_preset(platform):
    """The preset to apply for a platform that's turned on. A device preset could only have been
    turned on on that device, so it's looked up without detecting the device again (that reads
    firmware files, and the launcher calls this before every game)."""
    preset = preset_for(platform)
    if preset:
        return preset
    for d in DEVICES.values():
        if platform in d["presets"]:
            return d["presets"][platform]
    return None


def applied():
    """Is a preset applied right now (between apply and restore)?"""
    return bool(config.load(BACKUP))


def restore():
    """Put back the settings a preset changed, and stop its motion server
    (after the game, after a crash, or when the preset is turned off)."""
    backup = config.load(BACKUP)
    if not backup:
        return
    for c in reversed(backup.get("_changes") or []):
        try:
            if _get(c) == c["ours"]:  # only if it's still the preset's: a change made meanwhile is kept
                _set(c, c["before"])
        except (OSError, ValueError):
            config.log.exception("Couldn't put back %s in %s", c.get("key"), c.get("path"))
    if backup.get("_motion_server"):
        procs.stop(*backup["_motion_server"])
    if backup.get("_restart_deck_motion_service"):
        _systemctl("start", DECK_MOTION_SERVICE)
    config.save(BACKUP, {})
    config.log.info("Controller settings restored")


# ---------- reading and changing one setting ----------
#
# Every setting a preset touches is described by a "change" record, saved in controller-backup.json
# before anything is written:
#   kind    how to read and write it: "ryujinx" (a player's motion block in Ryujinx's Config.json),
#           "ini" (one key in an INI file), "cemu" (a <controller> block in a Cemu profile)
#   path    the file
#   key     which setting: the player's index (ryujinx), [section, key] (ini), unused (cemu)
#   before  its value before the preset (None: it wasn't there)
#   ours    the value the preset sets
# Being plain JSON, the records survive a crash, and restore() can undo them in a later process.

def _change(kind, path, key, before, ours):
    """A change record (see above)."""
    return {"kind": kind, "path": str(path), "key": key, "before": before, "ours": ours}


def _get(c):
    """The setting's current value in the file (None if it isn't there)."""
    path = Path(c["path"])
    if c["kind"] == "ryujinx":
        entries = (_load_json(path) or {}).get("input_config") or []
        return entries[c["key"]].get("motion") if c["key"] < len(entries) else None
    if c["kind"] == "ini":
        return ini.get_value(path, *c["key"])
    if c["kind"] == "cemu":  # our block is either in the profile, exactly as we wrote it, or not
        if path.is_file() and c["ours"] in path.read_text():
            return c["ours"]
        return None
    raise ValueError(c["kind"])


def _set(c, value):
    """Write `value` into the setting (None: remove it), touching nothing else in the file."""
    path = Path(c["path"])
    if c["kind"] == "ryujinx":
        cfg = _load_json(path)
        entries = (cfg or {}).get("input_config") or []
        if c["key"] < len(entries):
            if value is None:
                entries[c["key"]].pop("motion", None)
            else:
                entries[c["key"]]["motion"] = value
            _save_json(path, cfg)
    elif c["kind"] == "ini":
        ini.set_value(path, *c["key"], value)
    elif c["kind"] == "cemu":
        text = path.read_text()
        if value is None:
            text = text.replace(c["ours"], "", 1)
        elif c["ours"] not in text:
            text = _insert_first_controller(text, value)
        config.write_atomic(path, text)


def _insert_first_controller(profile, block):
    """A Cemu profile with `block` added as its first <controller>: Cemu takes motion from the
    first controller that has it, so ours has to come before the player's own ones."""
    first = re.search(r"^\s*<controller>", profile, re.M)
    if not first:  # a profile with no controllers yet: before the closing tag
        first = re.search(r"^\s*</emulated_controller>", profile, re.M)
    if not first:
        return profile  # not a profile we understand: leave it alone
    return profile[:first.start()] + block + profile[first.start():]


def _cemu_has_dsu(path):
    """Does this Cemu profile already read motion from 127.0.0.1:26760?"""
    try:
        text = Path(path).read_text()
    except OSError:
        return False
    # (Regular expressions rather than an XML parser: Decky's bundled Python may lack xml.etree.)
    for block in re.findall(r"<controller>(.*?)</controller>", text, re.S):
        is_dsu = _xml_tag(block, "api") == "DSUController" and _xml_tag(block, "motion") == "true"
        # Cemu's DSU controller uses 127.0.0.1:26760 when the profile doesn't say otherwise
        right_address = (_xml_tag(block, "ip", motion.HOST) == motion.HOST
                         and _xml_tag(block, "port", str(motion.PORT)) == str(motion.PORT))
        if is_dsu and right_address:
            return True
    return False


def _xml_tag(block, name, default=""):
    """The text of the first <name>...</name> in `block`, or `default` if there's none."""
    m = re.search(rf"<{name}>\s*(.*?)\s*</{name}>", block, re.S)
    return m[1] if m else default


# ---------- the motion server process ----------

def _start_server(launcher_pid, backup):
    """Start bin/romm_motion.py and wait until it's serving. Returns (ok, reason if not).

    It runs as its own process (not a thread of the launcher) so that it outlives nothing: it watches
    the launcher and stops when the game is over, however the game ended. It reports through
    settings/motion-ready.json because it has no other channel back to the launcher.
    """
    ready = config.SETTINGS_DIR / "motion-ready.json"
    ready.unlink(missing_ok=True)
    command = [sys.executable or config.PYTHON, str(MOTION_SERVER), str(launcher_pid), str(procs.start_time(launcher_pid))]
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            preexec_fn=procs.default_close_signals)
    backup["_motion_server"] = [proc.pid, procs.start_time(proc.pid)]
    config.save(BACKUP, backup)  # so restore() stops it even if the rest goes wrong
    for _ in range(50):  # up to 5 s
        if ready.exists():
            answer = config.load("motion-ready")
            if answer.get("ok"):
                return True, ""
            return False, answer.get("error") or "Motion server failed"
        if proc.poll() is not None:  # it exited without saying why
            break
        time.sleep(0.1)
    return False, "Motion server didn't start"


# ---------- helpers ----------

def _read(path):
    """A small text file's contents, or "" if it can't be read (firmware info files may be missing)."""
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _load_json(path):
    """An emulator's JSON settings, or None if missing or unreadable (then the preset leaves it alone)."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _save_json(path, cfg):
    """Write an emulator's JSON settings back (in one step, see config.write_atomic)."""
    config.write_atomic(path, json.dumps(cfg, indent=2))


def _report(platform, ok, text):
    """Remember how applying the preset went (the game page shows it), and pass the result on."""
    st = config.load(STATUS)
    st[platform] = ("Last game: " if ok else "Last game: not applied. ") + text.split(" · ")[-1]
    config.save(STATUS, st)
    return ok, text


def _systemctl(*args):
    """Run `systemctl --user ...` and return what it printed ("" if it couldn't run)."""
    try:
        r = subprocess.run(["systemctl", "--user", *args], env=_user_env(), capture_output=True, text=True, timeout=30)
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _user_env():
    """systemctl --user needs the session's bus, which Decky's own process may not have."""
    run = f"/run/user/{os.getuid()}"
    return {**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", run),
            "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path={run}/bus")}
