"""Checks romm-deck.zip the way Decky Loader reads it when installing, so a zip that Decky would stop on never
gets published.

Used by package.sh (so every `npm run package` checks its zip):  python3 .github/scripts/check_package.py romm-deck.zip

Decky's "Install plugin from URL" and "Install plugin from ZIP" (decky_loader/browser.py, _install) open the zip,
look for exactly one plugin.json one folder deep (<folder>/plugin.json), take the plugin's name from it, unpack
the zip into its plugins folder and then look the plugin up by that name. If any of that fails, Decky logs it and
the install popup stays on "Parsing zip file" with nothing to tell the user why. So this checks:

1. it's a zip that opens, and every file in it is intact;
2. everything is inside one top-level folder (it's unpacked straight into Decky's plugins folder, so a file
   outside it would land among other plugins), with no absolute paths or "..";
3. that folder holds plugin.json with a name, and the files Decky loads: main.py, dist/index.js, package.json;
4. the version inside matches the repository's package.json, so the zip is the build it claims to be.

Exits non-zero, with every problem found, when the zip isn't fit to publish.
"""
import json
import sys
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("plugin.json", "main.py", "dist/index.js", "package.json")  # what Decky needs to load the plugin


def problems_in(zip_path):
    """Everything about the zip that would stop Decky installing it (an empty list: it's fine)."""
    try:
        archive = ZipFile(zip_path)
    except (OSError, BadZipFile) as e:
        return [f"not a zip Decky can open: {e}"]
    with archive:
        broken = archive.testzip()
        if broken:
            return [f"damaged file in the zip: {broken}"]
        names = archive.namelist()
        problems = []
        folders = {PurePosixPath(n).parts[0] for n in names}
        for n in names:
            parts = PurePosixPath(n).parts
            if n.startswith("/") or ".." in parts:
                problems.append(f"unsafe path: {n}")
            elif len(parts) < 2 and not n.endswith("/"):
                problems.append(f"file outside the plugin's folder: {n}")
        if len(folders) != 1:
            return problems + [f"expected one top-level folder, found {sorted(folders)}"]
        folder = folders.pop()

        # Decky's own test: plugin.json exactly one folder deep, once
        manifests = [n for n in names if n.endswith("/plugin.json") and n.count("/") == 1]
        if len(manifests) != 1:
            return problems + [f"expected one <folder>/plugin.json, found {manifests}"]
        for required in REQUIRED:
            if f"{folder}/{required}" not in names:
                problems.append(f"missing {folder}/{required}")
        try:
            name = json.loads(archive.read(manifests[0])).get("name", "")
        except ValueError as e:
            return problems + [f"plugin.json isn't valid JSON: {e}"]
        if not str(name).strip():
            problems.append("plugin.json has no name (Decky finds the installed plugin by it)")

        if f"{folder}/package.json" in names:
            inside = json.loads(archive.read(f"{folder}/package.json")).get("version")
            repository = json.loads((ROOT / "package.json").read_text()).get("version")
            if inside != repository:
                problems.append(f"zip is version {inside}, the repository is {repository}: rebuild it")
        return problems


def main():
    """Check the zip named on the command line and report."""
    zip_path = sys.argv[1] if len(sys.argv) > 1 else "romm-deck.zip"
    problems = problems_in(zip_path)
    if problems:
        sys.exit(f"{zip_path} won't install in Decky:\n  " + "\n  ".join(problems))
    print(f"{zip_path}: installs in Decky")


if __name__ == "__main__":
    main()
