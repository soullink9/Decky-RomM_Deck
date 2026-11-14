"""Zips a folder the same way every time: the same files give a byte-for-byte identical zip, on any machine.

Used by package.sh:  python3 scripts/build_zip.py <folder> <zip>   (the folder is stored as the zip's one top folder)

Why it matters: the release is built twice, by Gitea's runner and by GitHub's, and the Decky store lists one
SHA-256 per version (Decky refuses a zip that doesn't match it), with the download pointing at GitHub. Both
builds have to produce the very same bytes, so nothing that differs between machines may go into the zip:
  - every entry gets the same fixed date (a normal zip records each file's modification time);
  - entries are in sorted order (folder listings come back in any order);
  - permissions are only "executable or not" (644 or 755), never the umask or owner;
  - files are stored, not compressed: compressed bytes can differ between zlib versions, and the plugin is
    small enough that it doesn't matter.
"""
import os
import sys
import zipfile
from pathlib import Path

FIXED_DATE = (1980, 1, 1, 0, 0, 0)  # the earliest date a zip can hold


def _entry(name, mode):
    """A zip entry with nothing machine-specific in it: fixed date, Unix permissions only."""
    info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
    info.create_system = 3  # Unix, so the permissions below are read on Linux
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_STORED
    return info


def build(folder, zip_path):
    """Zip `folder` (as a top folder of the same name) into `zip_path`."""
    folder = Path(folder)
    paths = sorted(p for p in folder.rglob("*"))
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in [folder] + paths:
            name = path.relative_to(folder.parent).as_posix()
            if path.is_dir():
                archive.writestr(_entry(name + "/", 0o40755), b"")
            else:
                executable = os.access(path, os.X_OK)
                archive.writestr(_entry(name, 0o100755 if executable else 0o100644), path.read_bytes())


def main():
    """Read the arguments and build the zip."""
    folder, zip_path = sys.argv[1], sys.argv[2]
    build(folder, zip_path)


if __name__ == "__main__":
    main()
