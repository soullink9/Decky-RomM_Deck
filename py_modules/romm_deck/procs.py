"""Telling whether a process we started is still running, safely.

A process id alone isn't enough: after a reboot (or a long time), Linux hands the same number to
an unrelated program. So a process is remembered as (pid, start time), the start time being the
number of clock ticks after boot at which it began (field 22 of /proc/<pid>/stat). Only a process
with the same pid *and* start time is the one we mean, so we never wait on, or stop, a stranger.
"""
import os
import signal
import time
from pathlib import Path


def start_time(pid):
    """When process `pid` started (clock ticks since boot), or None if it's gone or has already
    exited and is only waiting to be collected (a "zombie", which isn't running anything)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # The process name (field 2) is in parentheses and may itself contain spaces or ")", so the
    # remaining fields are split from the last ")" on. Of those, [0] is the state, [19] the start time.
    fields = stat.rsplit(")", 1)[-1].split()
    if len(fields) < 20 or fields[0] == "Z":
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def is_running(pid, started):
    """Is the process remembered as (pid, started) still running?"""
    return started is not None and start_time(pid) == started


def stop(pid, started, wait=1.0):
    """Ask the process to close (SIGTERM), and force it (SIGKILL) if it hasn't within `wait` seconds.
    Does nothing if that process is already gone, even if its number is now someone else's."""
    if not is_running(pid, started):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not is_running(pid, started):
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def default_close_signals():
    """Make a child process close normally when asked to (for subprocess's preexec_fn).

    The game launcher ignores SIGTERM and SIGHUP so it survives Steam's "Exit game" long enough to
    push saves (see bin/romm_launch.py). Children inherit ignored signals, so the emulator and the
    motion server would ignore them too; this puts the default behaviour back for them.
    """
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGHUP, signal.SIG_DFL)
