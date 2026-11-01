"""The motion server for a controller preset (see py_modules/romm_deck/motion.py).

presets.apply() starts it before a game:  python3 romm_motion.py <launcher pid> <its start time>
It stops when the launcher is gone (or when presets.restore() stops it after the game).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from romm_deck import config, motion  # noqa: E402


def main():
    import logging
    folder = config.LOG_DIR if config.LOG_DIR.exists() else config.SETTINGS_DIR
    logging.basicConfig(filename=folder / "motion.log", level=logging.INFO, format="%(asctime)s %(message)s")
    watch_pid, watch_start = int(sys.argv[1]), sys.argv[2]

    def launcher_running():
        try:
            return Path(f"/proc/{watch_pid}/stat").read_text().rsplit(")", 1)[-1].split()[19] == watch_start
        except (OSError, IndexError):
            return False

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
