"""Steam runs this for every RomM Deck card:  python3 romm_launch.py <rom_id>

1. pull newer saves from RomM (and apply a controller preset, if one is on)
2. play: a taken-over card runs its original command (e.g. EmuDeck's), others EmuDeck's launcher
3. after the game: push the saves that changed, put controller settings back (see session.py:
   this still happens when Steam's "Exit game" closes the launcher along with the game)

If RomM can't be reached the game still starts; saves sync next time.
"""
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

# Steam runs this with the system Python, outside Decky, so the plugin's modules are added by hand
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from romm_deck import config, library, presets, procs, saves, session  # noqa: E402
from romm_deck.api import RomM, RomMError  # noqa: E402


LOG_FILE = (config.LOG_DIR if config.LOG_DIR.exists() else config.SETTINGS_DIR) / "launch.log"


def setup_logging():
    """Log to launch.log (Steam shows nothing of what the launcher does, so this is the only record).
    Past 5 MB the old log is kept once as launch.old.log and a new one started."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOG_FILE.is_file() and LOG_FILE.stat().st_size > 5_000_000:
        LOG_FILE.replace(LOG_FILE.with_suffix(".old.log"))
    logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def pull_saves(rom_id, game):
    """Bring the game's saves up to date from RomM before it starts, and say how it went.
    Never stops the game: with RomM unreachable it starts with the saves on this PC."""
    try:
        client = RomM.from_settings()
        client.timeout = 10  # a dead server mustn't keep the player waiting long
        r = saves.sync(client, rom_id, game, "pull")
        n = r["down"]
        config.notify("Saves synced", f"{game['name']}: pulled {n} save file{'s' if n != 1 else ''} from RomM"
                      if n else f"{game['name']}: already up to date with RomM")
    except RomMError as e:  # offline, server down...: play anyway, sync next time
        config.log.warning("Save pull skipped for rom %s: %s", rom_id, e)
        config.notify("Saves not synced", f"Couldn't reach RomM. {game['name']} starts with the saves on this PC.")
    except Exception as e:
        config.log.exception("Save pull failed for rom %s; continuing", rom_id)
        config.notify("Saves not synced", f"{game['name']}: {e}")


def main():
    """Sync, play, sync. Returns the emulator's exit code (Steam ignores it, the log keeps it)."""
    setup_logging()
    rom_id = str(library.resolve(sys.argv[1]))  # the card may still carry an old RomM id
    game = library.installed().get(rom_id)
    if not game or not game.get("launch"):
        config.log.error("Rom %s isn't downloaded (or has no emulator set up)", rom_id)
        return 1

    session.finish()  # anything left from a game that was closed before it could finish
    synced = bool(saves.emu_for(game))
    if synced:
        pull_saves(rom_id, game)
    try:
        preset = presets.apply(game)  # a device controller preset, if turned on for this platform
        if preset:
            ok, text = preset
            config.notify("Controller preset on" if ok else "Controller preset not applied", text)
    except Exception as e:
        config.log.exception("Controller preset not applied; starting anyway")
        config.notify("Controller preset not applied", str(e))
    before = saves.snapshot(game) if synced else None

    cmd, env, cwd = library.launch_command(game)
    rom = Path(game["launch"])
    config.log.info("Launching %s: %s", game["name"], cmd)
    config.log.info("Game file: %s (%s)", rom, f"{rom.stat().st_size:,} bytes" if rom.is_file() else "MISSING")
    # Steam's "Exit game" sends every process of the game a close signal. The emulator closes; the
    # launcher keeps going so it can finish up (and if Steam kills it anyway, the plugin finishes).
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    # the emulator's own messages go into launch.log too, so a game that won't start can be explained
    with open(LOG_FILE, "a") as out:
        proc = subprocess.Popen(cmd, env=env, cwd=cwd if cwd and Path(cwd).is_dir() else None,
                                stdout=out, stderr=subprocess.STDOUT,
                                preexec_fn=procs.default_close_signals)
        session.start(rom_id, game, before, [os.getpid(), proc.pid])
        code = proc.wait()
    config.log.info("%s closed (exit code %s)", game["name"], code)
    session.finish(timeout=10)
    return code


if __name__ == "__main__":
    sys.exit(main())
