"""Where things live, plus tiny JSON stores.

Shared by the Decky backend (main.py) and the game launcher (bin/romm_launch.py),
so it only uses the standard library and works out its paths from its own location.
"""
import contextlib
import fcntl
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

# Decky installs the plugin at ~/homebrew/plugins/<plugin>/, and this file is
# <plugin>/py_modules/romm_deck/config.py. Working the folders out from here (rather than from
# Decky's DECKY_* environment variables) means the game launcher, which Steam starts without
# Decky's environment, finds the same folders as the Decky backend.
PLUGIN_DIR = Path(__file__).resolve().parents[2]
DECKY_HOME = PLUGIN_DIR.parents[1]
SETTINGS_DIR = DECKY_HOME / "settings" / PLUGIN_DIR.name
LOG_DIR = DECKY_HOME / "logs" / PLUGIN_DIR.name
DATA_DIR = DECKY_HOME / "data" / PLUGIN_DIR.name  # Decky serves this folder to Steam's pages (http://localhost:1337)
# Decky's backend may run as root; DECKY_USER_HOME is the real user's home, where EmuDeck lives.
HOME = Path(os.environ.get("DECKY_USER_HOME") or Path.home())

LAUNCHER = PLUGIN_DIR / "bin" / "romm_launch.py"
PYTHON = "/usr/bin/python3"  # the system Python Steam cards run the launcher with (not Decky's bundled one)

log = logging.getLogger("romm_deck")


# ---------- JSON stores (settings/<name>.json: settings, installed, sync, steam-details...) ----------

def load(name, default=None):
    """The store settings/<name>.json, or `default` ({} if not given) if it's missing or unreadable.
    A damaged file reads as empty rather than raising, so one bad file never stops the plugin."""
    try:
        return json.loads((SETTINGS_DIR / f"{name}.json").read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def save(name, data):
    """Write settings/<name>.json in one step (see write_atomic)."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(SETTINGS_DIR / f"{name}.json", json.dumps(data, indent=2))


def write_atomic(path, content):
    """Write a file (text or bytes) in one step: to a temporary file next to it first, then moved
    into place. A crash or power loss leaves either the old file or the new one, never half of one,
    which matters for the plugin's own stores and for emulator settings it changes.
    The temporary name is unique per process and thread, so two writers never share it."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    if isinstance(content, bytes):
        tmp.write_bytes(content)
    else:
        tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


@contextlib.contextmanager
def editing(name):
    """Load, change and save a store with nobody else changing it in between (two downloads
    finishing together, the launcher and the panel...):  with config.editing("installed") as games:"""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_DIR / f"{name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load(name)
        yield data
        save(name, data)


def removed_log(line):
    """Every file the plugin deletes is listed in removed.log, so you can always check."""
    folder = LOG_DIR if LOG_DIR.exists() else SETTINGS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "removed.log", "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")


def notify(title, body=""):
    """A popup in Game Mode. The launcher can't reach the panel directly, so it drops a note in
    settings/notify/ and the Decky backend passes it on (main.py, _pass_on_notifications)."""
    try:
        folder = SETTINGS_DIR / "notify"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{time.time_ns()}-{os.getpid()}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"title": title, "body": body}))
        tmp.replace(path)
    except OSError:
        pass  # a popup is never worth failing over


# ---------- EmuDeck folders ----------

def emudeck():
    """The Emulation folder layout, read from EmuDeck's settings.sh (EmuDeck lets you put it on
    an SD card or anywhere else). Falls back to ~/Emulation, EmuDeck's default."""
    paths = {}
    for f in (HOME / ".config/EmuDeck/settings.sh", HOME / "emudeck/settings.sh"):
        if f.exists():
            for line in f.read_text(errors="ignore").splitlines():
                m = re.match(r"^\s*(emulationPath|romsPath|savesPath|biosPath|storagePath)=(.*)$", line)
                if m:
                    paths[m[1]] = m[2].replace('"', "").replace("'", "").strip()
            break
    emulation = Path(paths.get("emulationPath") or HOME / "Emulation")
    return {
        "emulation": emulation,
        "roms": Path(paths.get("romsPath") or emulation / "roms"),
        "saves": Path(paths.get("savesPath") or emulation / "saves"),
        "bios": Path(paths.get("biosPath") or emulation / "bios"),
        "launchers": emulation / "tools" / "launchers",
    }
