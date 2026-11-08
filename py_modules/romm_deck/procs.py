"""Telling whether a process we started is still running, safely, and looking at what it runs.

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


# ---------- looking at the emulator a game started (for checking a controller preset took) ----------

def _parent(pid):
    """The parent of process `pid`, or None if it's gone (field 4 of /proc/<pid>/stat)."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[-1].split()
        return int(fields[1])
    except (OSError, ValueError, IndexError):
        return None


def descendants(pid):
    """Every process started, directly or not, by process `pid`. An emulator run through EmuDeck's
    launcher and flatpak is a few levels down, but still in the tree, also inside flatpak's sandbox."""
    parents = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            parent = _parent(int(entry.name))
            if parent is not None:
                parents.setdefault(parent, []).append(int(entry.name))
    found, todo = [], [pid]
    while todo:
        children = parents.get(todo.pop(), [])
        found += children
        todo += children
    return found


def command_line(pid):
    """The program and arguments process `pid` was started with ([] if it's gone or not ours to read)."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def name(pid):
    """The process's short name (what `ps` shows), or "" if it's gone."""
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def holding_open(path):
    """The processes that have the file `path` open, as {pid: name}. Only this user's processes can be
    looked at, so a system service holding it (one running as root) isn't listed."""
    target = str(path)
    holders = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fds = list((entry / "fd").iterdir())
        except OSError:
            continue  # another user's process, or gone
        for fd in fds:
            try:
                if os.readlink(fd) == target:
                    holders[int(entry.name)] = name(int(entry.name))
                    break
            except OSError:
                continue
    return holders
