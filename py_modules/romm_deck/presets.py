"""Controller presets: per platform, off unless turned on. Each one changes a few emulator settings
while a game runs, and puts them back when it closes (also after a crash or power-off).

On a ROG Ally / Xbox Ally (X), "motion" presets:
  Switch (Ryujinx), Wii U (Cemu) and 3DS (Azahar) read motion from the plugin's own motion server
  (motion.py), which reads the Ally's motion itself (EmuDeck's Steam Deck motion server can't see
  it under InputPlumber). EmuDeck already points Cemu and Azahar at that address; the preset only
  sets it where it isn't. The motion is calibrated once from the game page (motion.calibrate).
On any device:
  Wii (Dolphin): use real Wii Remotes for all four players instead of emulated ones.

Every change is recorded first (settings/controller-backup.json), and after the game a setting is
only put back if it still has the preset's value, so a change you make in the emulator is kept.

To add a device: an entry in DEVICES. To add a platform: an entry in a "presets" list, with a
plan() that says which settings to change.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import config, motion
from .library import RYUJINX_CONFIGS

DMI = Path("/sys/class/dmi/id")
MOTION_SERVER = config.PLUGIN_DIR / "bin" / "romm_motion.py"
BACKUP = "controller-backup"  # settings/controller-backup.json while a preset is applied
STATUS = "controller-status"  # how the last game with a preset went, for the game page
# EmuDeck's Steam Deck motion server (SteamDeckGyroDSU), if the user installed it. It can't see
# the Ally's motion under InputPlumber, but while it runs it holds the motion port (26760), so it's
# paused for the length of a game that needs our server, then started again.
DECK_MOTION_SERVICE = "sdgyrodsu.service"

H, FP = config.HOME, config.HOME / ".var/app"
CEMU_PROFILES = [H / ".config/Cemu/controllerProfiles/controller0.xml",
                 H / ".local/share/Cemu/controllerProfiles/controller0.xml",
                 FP / "info.cemu.Cemu/data/cemu/controllerProfiles/controller0.xml"]
AZAHAR_CONFIGS = [H / ".config/azahar-emu/qt-config.ini",
                  FP / "io.github.azahar.Azahar/config/azahar-emu/qt-config.ini"]
DOLPHIN_DIRS = [FP / "org.DolphinEmu.dolphin-emu/config/dolphin-emu", H / ".config/dolphin-emu"]

DSU_MOTION = {  # Ryujinx: motion from 127.0.0.1:26760 ("CemuHook")
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
AZAHAR_DSU = "engine:cemuhookudp"
REAL_WIIMOTE = "2"  # Dolphin's [WiimoteN] Source: 0 none, 1 emulated, 2 real


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
        size = _ini_get(path, "Controls", "profiles\\size") or "1"
        for n in range(1, (int(size) if size.isdigit() else 1) + 1):
            key = f"profiles\\{n}\\motion_device"
            current, default = _ini_get(path, "Controls", key), _ini_get(path, "Controls", key + "\\default")
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
            current = _ini_get(wiimotes, f"Wiimote{n}", "Source")
            if current != REAL_WIIMOTE:
                changes.append(_change("ini", wiimotes, [f"Wiimote{n}", "Source"], current, REAL_WIIMOTE))
        current = _ini_get(core, "Core", "WiimoteContinuousScanning")
        if current != "True":
            changes.append(_change("ini", core, ["Core", "WiimoteContinuousScanning"], current, "True"))
    return changes


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
                     "a remote to connect it. Your own Dolphin settings come back when the game closes.",
            "running": "using real Wii Remotes (press 1+2 on each to connect)"},
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
    # (it could only be turned on where the device has it, so no need to detect the device again)
    preset = preset_for(platform) or next((d["presets"][platform] for d in DEVICES.values()
                                           if platform in d["presets"]), None)
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
    running = preset.get("running", "reading the Ally's motion")
    return _report(platform, True, f"{preset['label']} · {running}")


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
        _stop(*backup["_motion_server"])
    if backup.get("_restart_deck_motion_service"):
        _systemctl("start", DECK_MOTION_SERVICE)
    config.save(BACKUP, {})
    config.log.info("Controller settings restored")


# ---------- reading and changing one setting ----------

def _change(kind, path, key, before, ours):
    return {"kind": kind, "path": str(path), "key": key, "before": before, "ours": ours}


def _get(c):
    path = Path(c["path"])
    if c["kind"] == "ryujinx":
        entries = (_load_json(path) or {}).get("input_config") or []
        return entries[c["key"]].get("motion") if c["key"] < len(entries) else None
    if c["kind"] == "ini":
        return _ini_get(path, *c["key"])
    if c["kind"] == "cemu":
        return c["ours"] if path.is_file() and c["ours"] in path.read_text() else None
    raise ValueError(c["kind"])


def _set(c, value):
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
        _ini_set(path, *c["key"], value)
    elif c["kind"] == "cemu":
        text = path.read_text()
        if value is None:
            text = text.replace(c["ours"], "", 1)
        elif c["ours"] not in text:
            m = re.search(r"^\s*<controller>", text, re.M) or re.search(r"^\s*</emulated_controller>", text, re.M)
            text = text[:m.start()] + value + text[m.start():] if m else text
        _write_atomic(path, text)


def _cemu_has_dsu(path):
    """Does this Cemu profile already read motion from 127.0.0.1:26760?"""
    try:
        text = Path(path).read_text()
    except OSError:
        return False
    for block in re.findall(r"<controller>(.*?)</controller>", text, re.S):
        tag = lambda name, default="": (re.search(rf"<{name}>\s*(.*?)\s*</{name}>", block, re.S) or [None, default])[1]
        if (tag("api") == "DSUController" and tag("motion") == "true"
                and tag("ip", motion.HOST) == motion.HOST and tag("port", str(motion.PORT)) == str(motion.PORT)):
            return True
    return False


# INI files (Dolphin's and Azahar's): only the one line changes, everything else stays as it is.
# Keys keep the file's own style ("key = value" for Dolphin, "key=value" for Azahar's Qt files).

def _ini_lines(path):
    """(lines, starts with a BOM, ends with a newline)"""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return [], False, True
    return (raw.decode("utf-8-sig", errors="ignore").splitlines(), raw.startswith(b"\xef\xbb\xbf"),
            raw.endswith(b"\n") or not raw)


def _ini_find(lines, section, key):
    """(index of the key's line in the section or None, where to add it, the section's header line)"""
    current, start, end = None, None, len(lines)
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if current == section:
                end = i
                break
            current = s[1:-1]
            if current == section:
                start = i
        elif current == section and re.match(rf"^\s*{re.escape(key)}\s*=", line):
            return i, i, start
    if start is None:
        return None, len(lines), None
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return None, end, start


def _ini_get(path, section, key):
    lines, _, _ = _ini_lines(path)
    i, _, _ = _ini_find(lines, section, key)
    return lines[i].split("=", 1)[1].strip() if i is not None else None


def _ini_set(path, section, key, value):
    """Set (or with None, remove) one key, leaving every other line exactly as it was. A section the
    plugin added at the end of the file is removed again with its last key."""
    lines, bom, newline = _ini_lines(path)
    i, at, header = _ini_find(lines, section, key)
    spaced = any(re.match(r"^[^=\[]+ = ", line) for line in lines) or not lines
    line = f"{key} = {value}" if spaced else f"{key}={value}"
    if value is None:
        if i is None:
            return
        del lines[i]
        if header == len(lines) - 1:  # an empty section left at the very end: the one we added
            del lines[header]
            if header and not lines[header - 1].strip():
                del lines[header - 1]
    elif i is not None:
        lines[i] = line
    elif header is not None:
        lines.insert(at, line)
    else:
        lines += ([""] if lines and lines[-1].strip() else []) + [f"[{section}]", line]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(Path(path), ("\ufeff" if bom else "") + "\n".join(lines) + ("\n" if newline and lines else ""))


# ---------- the motion server process ----------

def _start_server(launcher_pid, backup):
    """Start bin/romm_motion.py and wait until it's serving. (ok, reason if not)"""
    ready = config.SETTINGS_DIR / "motion-ready.json"
    ready.unlink(missing_ok=True)
    proc = subprocess.Popen([sys.executable or config.PYTHON, str(MOTION_SERVER), str(launcher_pid),
                             str(_started(launcher_pid))],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            preexec_fn=_default_signals)
    backup["_motion_server"] = [proc.pid, _started(proc.pid)]
    config.save(BACKUP, backup)  # so restore() stops it even if the rest goes wrong
    for _ in range(50):  # up to 5 s
        if ready.exists():
            r = config.load("motion-ready")
            return (True, "") if r.get("ok") else (False, r.get("error") or "Motion server failed")
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    return False, "Motion server didn't start"


def _stop(pid, started):
    if _started(pid) != started:  # already gone (or the number now belongs to something else)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(20):
        if _started(pid) != started:
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _started(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[-1].split()
        return None if stat[0] == "Z" else stat[19]
    except (OSError, IndexError):
        return None


def _default_signals():
    """The launcher ignores Steam's close signal; the motion server shouldn't."""
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGHUP, signal.SIG_DFL)


# ---------- helpers ----------

def _read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _save_json(path, cfg):
    _write_atomic(Path(path), json.dumps(cfg, indent=2))


def _write_atomic(path, text):
    tmp = path.with_name(path.name + ".romm-tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _report(platform, ok, text):
    st = config.load(STATUS)
    st[platform] = ("Last game: " if ok else "Last game: not applied. ") + text.split(" · ")[-1]
    config.save(STATUS, st)
    return ok, text


def _systemctl(*args):
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
