"""Reading and changing one setting in an emulator's INI-style file, leaving every other byte as it was.

Used for Dolphin's, Azahar's, PPSSPP's, DuckStation's and PCSX2's .ini files and RetroArch's .cfg
files. Python's configparser isn't used on purpose: it rewrites the whole file (dropping comments,
reordering, changing spacing and case), and the presets promise to put a file back exactly as it was.

Each file keeps its own style: a byte-order mark stays, a missing final newline stays missing, and
a new key is written as "key = value" or "key=value" to match the lines already there.
"""
import re
from pathlib import Path

from . import config

BOM = b"\xef\xbb\xbf"


def read_lines(path):
    """(lines, starts with a byte-order mark, ends with a newline). A missing file reads as empty."""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return [], False, True
    lines = raw.decode("utf-8-sig", errors="ignore").splitlines()
    ends_with_newline = raw.endswith(b"\n") or not raw
    return lines, raw.startswith(BOM), ends_with_newline


def find(lines, section, key):
    """Where `key` is in `section`: (its line index or None, where to add it, the section's header index).

    `section` None means the part of the file before any [section] header (RetroArch's .cfg files
    have no sections at all). The header index is None when the section isn't in the file, or when
    `section` is None. A missing key is added after the section's last setting, not after the blank
    lines that usually separate it from the next section.
    """
    in_section = section is None
    header = None
    end = len(lines)
    key_line = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if _is_header(line):
            if in_section:
                end = i  # the next section starts here: ours is over
                break
            if line.strip()[1:-1] == section:
                in_section, header = True, i
            continue
        if in_section and key_line.match(line):
            return i, i, header
    if not in_section:
        return None, len(lines), None
    first_setting = 0 if header is None else header + 1
    while end > first_setting and not lines[end - 1].strip():
        end -= 1
    return None, end, header


def get_value(path, section, key):
    """The value of `key` in `section` (as written, spaces trimmed), or None if it isn't set."""
    lines, _, _ = read_lines(path)
    index, _, _ = find(lines, section, key)
    if index is None:
        return None
    return lines[index].split("=", 1)[1].strip()


def set_value(path, section, key, value):
    """Set `key` in `section` to `value`, or remove the key with value None.

    Only that one line changes. A section that isn't in the file is added at the end; when its
    last key is removed again, the now-empty section at the end of the file goes too, so applying
    and then undoing a change leaves the file byte-for-byte as it started.
    """
    lines, bom, ends_with_newline = read_lines(path)
    index, insert_at, header = find(lines, section, key)
    spaced = not lines or any(re.match(r"^[^=\[]+ = ", line) for line in lines)
    new_line = f"{key} = {value}" if spaced else f"{key}={value}"

    if value is None:
        if index is None:
            return  # nothing to remove
        del lines[index]
        _drop_empty_last_section(lines, header)
    elif index is not None:
        lines[index] = new_line
    elif header is not None or section is None:
        lines.insert(insert_at, new_line)
    else:  # the section isn't there yet: add it at the end, after a blank line
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", new_line]

    text = "\n".join(lines)
    if ends_with_newline and lines:
        text += "\n"
    if bom:
        text = "﻿" + text
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    config.write_atomic(path, text)


def _is_header(line):
    """Is this line a [section] header?"""
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def _drop_empty_last_section(lines, header):
    """After removing a key: if its section is now an empty one at the very end of the file, it's
    the one set_value added, so remove the header (and the blank line set_value put before it)."""
    if header is None or header != len(lines) - 1:
        return
    del lines[header]
    if header > 0 and not lines[header - 1].strip():
        del lines[header - 1]
