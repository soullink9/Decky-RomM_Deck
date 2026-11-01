"""The motion server for a controller preset (see py_modules/romm_deck/motion.py).

presets.apply() starts it before a game:  python3 romm_motion.py <launcher pid> <its start time>
It stops when the launcher is gone (or when presets.restore() stops it after the game).
"""
import logging
import sys
from pathlib import Path

# Steam runs this with the system Python, outside Decky, so the plugin's modules are added by hand
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from romm_deck import config, motion, procs  # noqa: E402


def main():
    """Serve motion until the launcher that started us is gone. Exit code 0 when the game closed."""
    folder = config.LOG_DIR if config.LOG_DIR.exists() else config.SETTINGS_DIR
    logging.basicConfig(filename=folder / "motion.log", level=logging.INFO, format="%(asctime)s %(message)s")
    watch_pid = int(sys.argv[1])
    watch_start = int(sys.argv[2]) if sys.argv[2].isdigit() else None  # ("None": the launcher was already gone)

    def launcher_running():
        """Is the game's launcher still running? (The game is over when it isn't.)"""
        return procs.is_running(watch_pid, watch_start)

    try:
        motion.serve(launcher_running, ready=lambda: config.save("motion-ready", {"ok": True}))
    except Exception as e:
        config.log.exception("Motion server stopped")
        config.save("motion-ready", {"ok": False, "error": str(e)})
        return 1
    config.log.info("Motion server stopped: the game closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
