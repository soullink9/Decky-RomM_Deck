"""What happens when a game closes, however it's closed.

In Game Mode you close a game with Steam's "Exit game", which ends the game's whole process tree,
and that tree includes our launcher. So the after-game work (push saves, put controller settings
back) can't rely on the launcher surviving. Instead the launcher writes session-<rom>.json before
the game starts, and whoever sees the game has ended first finishes it, exactly once:
  * the launcher, when the emulator exits (it ignores Steam's first "please close", so usually it's this)
  * the Decky plugin, when Steam reports the game stopped (it isn't part of the game, so it's never closed)
  * the Decky plugin when it starts, for a session left over from a crash or a power-off
A session is only finished once nothing is still running the game file, so the emulator is done saving.
"""
import os
import time
from pathlib import Path

from . import config, library, presets, saves
from .api import RomM, RomMError


def start(rom_id, game, before, pids):
    """Right after the game starts. `before`: its save folders' snapshot. `pids`: launcher + emulator."""
    config.save(f"session-{rom_id}", {"rom_id": rom_id, "launch": game.get("launch"), "before": before,
                                      "pids": [[pid, _started(pid)] for pid in pids], "started": time.time()})


def running(rom_id):
    """Is this game being played right now (started through RomM Deck and not closed yet)?"""
    path = config.SETTINGS_DIR / f"session-{rom_id}.json"
    return path.exists() and _still_running(config.load(path.stem))


def pending():
    """Sessions not finished yet (game still running, or closed in a way nobody finished)."""
    return sorted(config.SETTINGS_DIR.glob("session-*.json")) + sorted(config.SETTINGS_DIR.glob("finishing-*.json"))


def finish(timeout=None):
    """Finish every session whose game has ended. Returns how many this call finished."""
    done = 0
    while True:
        claimed = _claim()
        if not claimed:
            return done
        try:
            _finish(config.load(claimed.stem), timeout)
        finally:
            claimed.unlink(missing_ok=True)
        done += 1


def _finish(s, timeout):
    rom_id = str(s.get("rom_id"))
    game = library.installed().get(rom_id)
    synced = bool(game and saves.emu_for(game))
    if synced and s.get("before") is not None:
        before = {k: tuple(v) for k, v in s["before"].items()}  # JSON turned (size, mtime) into lists
        saves.remember_session(rom_id, game, before, saves.snapshot(game))
    try:
        if presets.applied():
            presets.restore()
            config.notify("Controller preset off", "Your own controller settings are back")
    except Exception:
        config.log.exception("Couldn't restore controller settings")
        config.notify("Controller settings not restored", "They'll be put back when you next start a game")
    if synced:
        try:
            client = RomM.from_settings()
            client.timeout = timeout or client.timeout
            n = saves.sync(client, rom_id, game, "push")["up"]
            config.log.info("Saves pushed after %s closed", game["name"])
            config.notify("Saves synced", f"{game['name']}: pushed {n} save file{'s' if n != 1 else ''} to RomM"
                          if n else f"{game['name']}: RomM already has your latest saves")
        except RomMError as e:  # offline: the next game or a Sync button catches up
            config.log.warning("Save push after %s skipped: %s", game["name"], e)
            config.notify("Saves not pushed", f"Couldn't reach RomM. {game['name']}'s saves are safe on this PC "
                                              "and go up next time (or press Sync).")
        except Exception as e:
            config.log.exception("Save push after %s failed", game["name"])
            config.notify("Saves not pushed", f"{game['name']}: {e}. They're still on this PC.")


def _claim():
    """Take one session whose game has ended (by renaming it, so two finishers never both get it).
    A session someone was finishing when they were killed is taken over."""
    for path in pending():
        if path.name.startswith("finishing-"):
            claimer = int(path.name.split("-")[1])
            if claimer == os.getpid() or _alive(claimer):
                continue  # someone is finishing it right now
        if _still_running(config.load(path.stem)):
            continue
        claim = config.SETTINGS_DIR / f"finishing-{os.getpid()}-{time.time_ns()}.json"
        try:
            os.rename(path, claim)
        except FileNotFoundError:
            continue  # someone else got there first
        return claim
    return None


def _still_running(s):
    """Is any of the game's processes still alive (including an emulator still writing its save)?"""
    me = os.getpid()
    for pid, started in s.get("pids") or []:
        # the same start time too: after a reboot, another program may have been given that number
        if pid != me and _alive(pid) and _started(pid) == started:
            return True
    launch = s.get("launch")
    if not launch:
        return False
    for proc in Path("/proc").iterdir():
        if proc.name.isdigit() and int(proc.name) != me:
            try:
                if launch.encode() in (proc / "cmdline").read_bytes():
                    return True
            except OSError:
                continue
    return False


def _started(pid):
    """When a process started (clock ticks since boot), or None."""
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[-1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a finished child nobody has collected yet ("zombie") isn't running
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[-1].split()[0] != "Z"
    except OSError:
        return False
