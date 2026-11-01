"""Download, remove and launch games; fetch BIOS files and cover art."""
import base64
import datetime
import hashlib
import json
import os
import re
import shutil
import threading
import time
import unicodedata
import urllib.parse
import zipfile
from pathlib import Path

from . import config, saves, systems

RYUJINX_SYSTEM_DIRS = [
    config.HOME / ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/system",  # Ryubing flatpak
    config.HOME / ".config/Ryujinx/system",                                    # EmuDeck's Ryujinx
]


def installed():
    return config.load("installed")


def resolve(rom_id):
    """A game's current RomM id, following any moves (see relink). Steam cards keep the old id."""
    moved, rid, seen = config.load("moved"), str(rom_id), set()
    while rid in moved and rid not in seen:
        seen.add(rid)
        rid = moved[rid]
    return int(rid)


def relink(client, rom_id, candidates=None):
    """RomM no longer has `rom_id` (it was deleted, e.g. a duplicate). Find the RomM entry that is
    the same game on this PC and move everything to it: Steam card, save tracking, settings.
    Returns the new id, or None if nothing matches."""
    games = installed()
    old = games.get(str(rom_id))
    if not old:
        return None
    if candidates is None:
        term = re.sub(r"\s*[\(\[].*?[\)\]]", "", Path(old["path"]).stem).strip()
        candidates = {r["id"]: r for t in {term, old["name"]} if t for r in client.roms("search", t)}.values()
    candidates = [r for r in candidates if r["id"] != int(rom_id)]
    path = Path(old["path"]).resolve()
    same_file = [r for r in candidates if (c := local_copy(r)) and c.resolve() == path]
    same_game = [r for r in candidates if r["platform_id"] == old["platform_id"] and (r.get("name") or "") == old["name"]]
    pick = same_file[0] if same_file else same_game[0] if len(same_game) == 1 else None
    if not pick:
        return None
    new = str(pick["id"])
    with config.editing("installed") as games:
        old = games.pop(str(rom_id), old)
        games[new] = {**games.get(new, {}), **old, "name": pick.get("name") or old["name"], "title_id": pick.get("title_id")}
    moved = config.load("moved")
    moved[str(rom_id)] = new
    config.save("moved", moved)
    saves.move_history(rom_id, new)
    config.log.info("RomM game %s is gone; moved %s to RomM game %s", rom_id, old["name"], new)
    return pick["id"]


def install(client, rom_id, progress=None):
    """Download a rom into its EmuDeck folder. Returns the installed.json entry."""
    rom = client.rom(rom_id)
    system = systems.for_rom(rom)
    exts = system["exts"] if system else []
    folder = config.emudeck()["roms"] / (system["folder"] if system else rom["platform_fs_slug"])
    folder.mkdir(parents=True, exist_ok=True)

    multi = rom.get("has_multiple_files")
    if multi and _extra_files(rom) and extras_dir():  # Switch: updates & DLC go to their own folder
        return _install_split(client, rom, folder, progress)

    tmp = folder / f".romm-{rom_id}.part"
    client.download(f"/api/roms/{rom_id}/content/{urllib.parse.quote(rom['fs_name'])}", tmp, progress)

    # RomM sends multi-file games (multi-disc, PS3 folders...) as one zip with an .m3u.
    # Single zipped roms are unpacked too, unless the emulator reads zips itself.
    unzip = multi or (system and rom["fs_extension"].lower() == "zip" and "zip" not in exts)
    dest = folder / (rom["fs_name"] if multi else rom["fs_name_no_ext"] if unzip else _file_name(rom))
    if dest.exists():
        problem = _not_this_game(dest, rom_id)
        if problem:
            tmp.unlink()
            raise ValueError(f"Not downloaded: {dest.name} is already there and {problem}")
        _remove_path(dest)
    if unzip and zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as z:
            z.extractall(dest)  # extractall refuses absolute paths and ".." on its own
        tmp.unlink()
    else:
        tmp.replace(dest)

    with config.editing("installed") as games:
        games[str(rom_id)] = game = _entry(rom, dest)
    return game


# ---------- Switch updates & DLC ----------

EXTRA_KINDS = ("update", "dlc")  # RomM's label for each file of a game (read from the Switch file)
RYUJINX_CONFIGS = [
    config.HOME / ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/Config.json",
    config.HOME / ".config/Ryujinx/Config.json",
    config.HOME / "Applications/publish/portable/Config.json",
]


def extras_dir():
    """Where Switch updates and DLC go: the plugin's setting, or else the first folder Ryujinx
    loads them from automatically ("autoload_dirs" in its Config.json). None if neither is set."""
    chosen = config.load("settings").get("switch_extras_dir")
    if chosen:
        return Path(chosen).expanduser()
    for f in RYUJINX_CONFIGS:
        try:
            dirs = json.loads(f.read_text()).get("autoload_dirs") or []
        except (OSError, ValueError):
            continue
        if dirs:
            return Path(dirs[0]).expanduser()
    return None


def _extra_files(rom):
    return [f for f in rom.get("files") or [] if f.get("category") in EXTRA_KINDS]


def _install_split(client, rom, folder, progress):
    """A Switch game with updates/DLC: the game file into roms/switch, the rest into extras_dir()."""
    game_files = _game_files(rom)
    if not game_files:
        raise ValueError("RomM doesn't say which of this game's files is the game itself")
    total = sum(f["file_size_bytes"] for f in game_files + _extra_files(rom)) or 1
    done = [0]

    def overall(d, _t):
        if progress:
            progress(done[0] + d, total)

    for f in game_files:
        dest = folder / f["file_name"]
        if dest.exists() and (problem := _not_this_game(dest, rom["id"])):
            raise ValueError(f"Not downloaded: {dest.name} is already there and {problem}")
        _download_file(client, rom, f, dest, overall)
        done[0] += f["file_size_bytes"]
    with config.editing("installed") as games:
        games[str(rom["id"])] = _entry(rom, folder / game_files[0]["file_name"])
    _get_extras(client, rom, overall, done)
    return installed()[str(rom["id"])]


def download_extras(client, rom_id, progress=None):
    """Get a game's updates and DLC (for a game that's already on the PC). Returns how many."""
    rom = client.rom(rom_id)
    if str(rom_id) not in installed():
        raise ValueError("Download the game first")
    total = sum(f["file_size_bytes"] for f in _extra_files(rom)) or 1
    done = [0]

    def overall(d, _t):
        if progress:
            progress(done[0] + d, total)

    return _get_extras(client, rom, overall, done)


def _get_extras(client, rom, progress, done):
    folder = extras_dir()
    if not folder:
        raise ValueError("Set the Switch updates & DLC folder first (on the plugin's home page)")
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in _extra_files(rom):
        dest = folder / f["file_name"]
        if not (dest.is_file() and dest.stat().st_size == f["file_size_bytes"]):  # already there
            _download_file(client, rom, f, dest, progress)
        done[0] += f["file_size_bytes"]
        saved.append(str(dest))
    with config.editing("installed") as games:
        if str(rom["id"]) in games:  # remembered, so Remove can clean them up
            games[str(rom["id"])]["extras"] = sorted(set(games[str(rom["id"])].get("extras", []) + saved))
            games[str(rom["id"])]["extras_dir"] = str(folder)
    return len(saved)


def _download_file(client, rom, f, dest, progress):
    """One file of a multi-file game (RomM sends just that file when asked for its id)."""
    tmp = dest.parent / f".romm-{rom['id']}-{f['id']}.part"
    client.download(f"/api/roms/{rom['id']}/content/{urllib.parse.quote(f['file_name'])}?file_ids={f['id']}",
                    tmp, progress, timeout=120)
    tmp.replace(dest)


def _file_name(rom):
    """The real file name of a single-file game. RomM names a game kept in its own folder
    ("switch/Astral Chain/Astral Chain.nsp") after the folder, with no extension, so the
    file's own name is used instead."""
    files = [f for f in rom.get("files") or [] if not f["file_name"].lower().endswith(".m3u")]
    if len(files) == 1 and Path(files[0]["file_name"]).suffix:
        return files[0]["file_name"]
    return rom["fs_name"]


def _fix_missing_extension(rom_id, rom):
    """Repair a game an older version saved without its extension: rename it to its real name."""
    g = installed().get(str(rom_id))
    if not g:
        return
    path, name = Path(g["path"]), _file_name(rom)
    if path.is_file() and not path.suffix and Path(name).suffix and path.name != name:
        target = path.with_name(name)
        if target.exists():
            return
        path.rename(target)
        with config.editing("installed") as games:
            if g := games.get(str(rom_id)):
                g["path"] = str(target)
                if g.get("launch") == str(path):
                    g["launch"] = str(target)
        config.log.info("Renamed %s to %s (it was saved without its extension)", path.name, name)


def find_existing(rom_list):
    """Add games from RomM that are already in Emulation/roms (put there before this plugin)
    to installed.json. Returns the ids now known to be on this PC."""
    for rom in rom_list:
        if str(rom["id"]) in installed():
            _fix_missing_extension(rom["id"], rom)
    games = installed()
    found = {}
    for rom in rom_list:
        if str(rom["id"]) not in games and (path := local_copy(rom)):
            owners = [g["name"] for g in [*games.values(), *found.values()] if Path(g["path"]).resolve() == path.resolve()]
            if owners:  # e.g. a duplicate entry in RomM: the file already belongs to that game
                continue
            found[str(rom["id"])] = _entry(rom, path)
    if found:
        with config.editing("installed") as games:
            for rom_id, entry in found.items():
                games.setdefault(rom_id, entry)
    return {int(k) for k in games}


def match_shortcut(client, app_id, exe, options):
    """Which RomM game a Steam card starts, or None.

    Cards made by RomM Deck are known by their app id. Other cards (Steam ROM Manager's)
    are matched by the game file in their launch command, looked up in RomM by name."""
    games = installed()
    for rom_id, g in games.items():
        if g.get("app_id") == app_id:
            return int(rom_id)
    ours = re.search(r'romm_launch\.py"?\s+(\d+)', options)
    if ours and str(resolve(ours[1])) in games:
        return resolve(ours[1])

    roms_dir = config.emudeck()["roms"].resolve()
    paths = [Path(p) for p in re.findall(r'"([^"]+)"', f"{exe} {options}")]
    paths = [p.resolve() for p in paths if p.exists() and p.resolve().is_relative_to(roms_dir)]
    for path in paths:
        for rom_id, g in games.items():
            known = {Path(g["path"]).resolve()} | ({Path(g["launch"]).resolve()} if g.get("launch") else set())
            in_folder = any(path.is_relative_to(k) for k in known if k.is_dir() and not _not_this_game(k, rom_id))
            if path in known or in_folder:
                return int(rom_id)

    for path in paths:  # not known yet: search RomM for it
        # by the file's name, its folder's, and the game folder's: a PS3 card starts
        # roms/ps3/<game>/PS3_GAME/USRDIR/EBOOT.BIN, where only <game> is the game's name
        rel = path.relative_to(roms_dir).parts
        game_folder = rel[1] if len(rel) > 2 else ""
        names = [path.stem, path.parent.name, game_folder, re.sub(r"\.ps3$", "", game_folder, flags=re.I)]
        for name in dict.fromkeys(n for n in names if n):
            term = re.sub(r"\s*[\(\[].*?[\)\]]", "", name).strip()  # drop "(USA)", "[!]"...
            for rom in client.roms("search", term) if term else []:
                copy = local_copy(rom)
                # the card may start the game, or one of its other files (e.g. an update .nsp)
                in_folder = copy and copy.is_dir() and path.is_relative_to(copy.resolve())
                if copy and (path in files_on_pc(rom) or (in_folder and not _not_this_game(copy, rom["id"]))):
                    find_existing([rom])
                    return rom["id"]
    return None


def local_copy(rom):
    """The file or folder in Emulation/roms that is this game, or None.

    Matches RomM's file name, the same name with another file type the emulator opens (say you
    converted a .cue/.bin game to .chd), or, for games RomM keeps as several files (a Switch game
    with its update and DLC), the main game file on its own."""
    roms_dir = config.emudeck()["roms"]
    system = systems.for_rom(rom)
    exts = system["exts"] if system else []
    folders = [roms_dir / system["folder"]] if system else []
    folders.append(roms_dir / rom["platform_fs_slug"])
    stems = [rom["fs_name_no_ext"]] + [Path(f["file_name"]).stem for f in _game_files(rom)]
    names = [rom["fs_name"]] + [f["file_name"] for f in _game_files(rom)]
    names += [f"{stem}.{ext}" for stem in stems for ext in exts] + [rom["fs_name_no_ext"]]
    for folder in folders:
        for name in dict.fromkeys(names):
            path = folder / name
            if path.exists() and path.resolve().is_relative_to(roms_dir.resolve()):
                return path
    for folder in folders:  # the same file names, in a sub-folder (e.g. roms/switch/<game>/<file>)
        for name in dict.fromkeys(names):
            found = [p for p in _listing(folder) if p.name == name]
            if len(found) == 1:
                return found[0]
    return _loose_match(rom, folders, exts)


def _loose_match(rom, folders, exts):
    """A game file named differently from RomM's: the same Switch title id in its name, or the same
    name once tags like "(USA)" / "[v0]", punctuation, case and "The" are ignored.
    Only used when exactly one file fits, so it never guesses between games."""
    tid = rom.get("title_id")
    want_tid = _base_title(int(tid, 16)) if tid and re.fullmatch(r"[0-9A-Fa-f]{16}", tid) else None
    want_names = {_simple(n) for n in (rom.get("name"), rom["fs_name_no_ext"]) if n} - {""}
    base_file, by_tid, by_name = [], [], []  # base_file: tagged with the base game's own id
    for folder in folders:
        try:  # a game kept as a folder (e.g. PS3: <game>/PS3_GAME/USRDIR/EBOOT.BIN), named differently
            for d in folder.iterdir():
                if d.is_dir() and not d.name.startswith(".") and _simple(re.sub(r"\.ps3$", "", d.name, flags=re.I)) in want_names \
                        and _pick_launch_file(d, exts):
                    by_name.append(d)
        except OSError:
            pass
        for path in _listing(folder):
            if not any(path.name.lower().endswith("." + e) for e in exts):
                continue
            tags = [int(t, 16) for t in re.findall(r"\[(01[0-9A-Fa-f]{14})\]", path.name)]
            if want_tid is not None and want_tid in tags:
                base_file.append(path)
            elif want_tid is not None and want_tid in [_base_title(t) for t in tags]:
                by_tid.append(path)  # its update or DLC
            elif _simple(path.stem) in want_names:
                by_name.append(path)
    for found in (base_file, by_tid, by_name):
        if len(set(found)) == 1:
            return found[0]
    return None


def _simple(name):
    """ "The Legend of Zelda: Tears of the Kingdom (USA) [v0]" -> "legendofzeldatearsofkingdom" """
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()  # Pokémon -> Pokemon
    name = re.sub(r"[\(\[].*?[\)\]]", "", name.lower()).replace("&", "and")
    return "".join(w for w in re.findall(r"[a-z0-9]+", name) if w != "the")


def _base_title(title_id):
    """A Switch update's or DLC's title id -> its base game's."""
    return title_id & ~0xFFF & ~0x1000


_listings = {}


def _listing(folder):
    """Files in a folder and its sub-folders. Kept until the folder changes or 30 seconds pass,
    so browsing a big platform stays quick."""
    try:
        mtime = folder.stat().st_mtime_ns
    except OSError:
        return []
    cached = _listings.get(folder)
    if not cached or cached[1] != mtime or time.monotonic() - cached[0] > 30:
        files = []
        for root, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files += [Path(root, n) for n in names if not n.startswith(".")]
        _listings[folder] = cached = (time.monotonic(), mtime, files)
    return cached[2]


def files_on_pc(rom):
    """Every file of this game that's in Emulation/roms, including its updates and DLC."""
    roms_dir = config.emudeck()["roms"]
    system = systems.for_rom(rom)
    folders = ([roms_dir / system["folder"]] if system else []) + [roms_dir / rom["platform_fs_slug"]]
    found = {(folder / f["file_name"]).resolve() for folder in folders for f in rom.get("files") or []
             if (folder / f["file_name"]).is_file()}
    if (copy := local_copy(rom)):
        found.add(copy.resolve())
    return found


def _game_files(rom):
    """RomM's main game file(s) for a multi-file game (not its updates, DLC, manuals...)."""
    files = rom.get("files") or []
    return [f for f in files if f.get("category") in (None, "game") and not f["file_name"].lower().endswith(".m3u")]


def _entry(rom, path):
    """installed.json entry for a game at `path`."""
    system = systems.for_rom(rom)
    preferred = [f["file_name"] for f in _game_files(rom)]
    launch = _pick_launch_file(path, system["exts"], preferred) if system else None
    return {
        "name": rom.get("name") or rom["fs_name_no_ext"],
        "platform": rom["platform_display_name"],
        "platform_id": rom["platform_id"],
        "system": rom["platform_slug"] if rom["platform_slug"] in systems.SYSTEMS else rom["platform_fs_slug"],
        "path": str(path),
        "launch": str(launch) if launch else None,
        "app_id": None,
        "title_id": rom.get("title_id"),  # Switch: finds the game's save folder
    }


def uninstall(client, rom_id):
    """Remove a game from this PC completely, without ever losing a save:
    1. sync its saves and states with RomM
    2. check RomM now holds an identical copy of every one (if not: stop, delete nothing)
    3. delete the save files, then the game. Returns {"app_id", "deleted", "kept"}."""
    game = installed().get(str(rom_id))
    if not game:
        raise ValueError("This game isn't on this PC")
    problem = _not_this_game(Path(game["path"]), rom_id)
    if problem:
        raise ValueError(f"Nothing removed: {game['path']} {problem}")
    deleted, kept = [], []
    if saves.emu_for(game):
        saves.sync(client, str(rom_id), game, "both")
        missing = saves.not_on_romm(client, str(rom_id), game)
        if missing:
            raise ValueError(f"Nothing removed: {len(missing)} save file(s) didn't reach RomM, e.g. {missing[0]}")
        deleted, kept = saves.delete_local(str(rom_id), game)
    return {"app_id": remove(rom_id), "deleted": deleted, "kept": kept}


def remove(rom_id):
    """Delete a downloaded game's files (not its saves). Returns its Steam app id, if any."""
    game = installed().get(str(rom_id))
    if not game:
        return None
    path = Path(game["path"])
    if path.exists() and not _not_this_game(path, rom_id):
        _remove_path(path)
        config.removed_log(f"game {game['name']}: {path}")
    for extra in game.get("extras", []):  # its updates & DLC: only files it downloaded, only in that folder
        extra = Path(extra)
        if extra.is_file() and extra.resolve().parent == Path(game.get("extras_dir", "/nonexistent")).resolve():
            extra.unlink()
            config.removed_log(f"update/DLC of {game['name']}: {extra}")
    with config.editing("installed") as games:
        games.pop(str(rom_id), None)
    shutil.rmtree(SHOTS / str(rom_id), ignore_errors=True)  # its Steam page's screenshots
    return game.get("app_id")


def _not_this_game(path, rom_id):
    """Why `path` must not be deleted as game `rom_id`'s files, or None if it's safe.
    The last line of defence: a platform folder, or a folder holding another game, is never
    deleted, whatever led here."""
    roms_dir = config.emudeck()["roms"].resolve()
    path = path.resolve()
    if not path.is_relative_to(roms_dir) or path == roms_dir:
        return "is outside the Emulation/roms folder"
    platform_folders = {(roms_dir / s["folder"]).resolve() for s in systems.SYSTEMS.values()}
    if path.is_dir() and (path.parent == roms_dir or path in platform_folders or
                          any(f.is_relative_to(path) for f in platform_folders)):
        return "is a whole platform folder"
    for other_id, g in installed().items():
        if other_id == str(rom_id):
            continue
        for p in (g.get("path"), g.get("launch")):
            if p and (Path(p).resolve() == path or Path(p).resolve().is_relative_to(path)):
                return f"also holds {g['name']}"
    return None


def set_app_id(rom_id, app_id):
    with config.editing("installed") as games:
        if str(rom_id) in games:
            games[str(rom_id)]["app_id"] = app_id


def take_over(rom_id, app_id, exe, options, start_dir):
    """Make an existing Steam card (e.g. EmuDeck's) start through RomM Deck. Its original command is
    kept, and the launcher runs exactly that. Returns the new command for the frontend to set."""
    with config.editing("installed") as games:
        game = games.get(str(rom_id))
        if not game:
            raise ValueError("This game isn't on this PC")
        if str(config.LAUNCHER) not in options:  # not already ours: remember what it ran
            game["original"] = {"exe": exe, "options": options, "start_dir": start_dir}
        game["app_id"] = app_id
    return shortcut(rom_id)


def taken_over():
    """Cards RomM Deck has taken over: [{"rom_id", "app_id"}] (so they can be re-checked)."""
    return [{"rom_id": int(k), "app_id": g["app_id"]} for k, g in installed().items()
            if g.get("original") and g.get("app_id")]


def shortcut(rom_id):
    """What the frontend needs to create the Steam card. Steam runs our launcher, not the emulator."""
    return {
        "exe": config.PYTHON,
        "start_dir": str(config.LAUNCHER.parent),
        "options": f'"{config.LAUNCHER}" {rom_id}',
    }


def launch_command(game):
    """The command that starts a game, plus its environment and folder.
    A taken-over card runs its original command, the way Steam would have."""
    if game.get("original"):
        o = game["original"]
        exe, options = o["exe"], o["options"] or ""
        cmd = options.replace("%command%", exe) if "%command%" in options else f"{exe} {options}"
        return ["/bin/bash", "-c", cmd], dict(os.environ), o["start_dir"].strip('"') or None
    system = systems.SYSTEMS[game["system"]]
    launcher = config.emudeck()["launchers"] / system["launcher"]
    args = [a.replace("{rom}", game["launch"]).replace("{cores}", str(systems.CORES)) for a in system["args"]]
    return ["bash", str(launcher), *args], {**os.environ, **system["env"]}, None


def install_firmware(client, platform_id):
    """Download every BIOS/firmware file RomM has for a platform into Emulation/bios."""
    bios = config.emudeck()["bios"]
    bios.mkdir(parents=True, exist_ok=True)
    names = []
    for fw in client.firmware(platform_id):
        dest = bios / fw["file_name"]
        client.download(f"/api/firmware/{fw['id']}/content/{urllib.parse.quote(fw['file_name'])}", dest)
        if dest.suffix == ".keys":  # Switch keys belong in Ryujinx's own system folder
            for d in RYUJINX_SYSTEM_DIRS:
                if d.parent.exists():
                    d.mkdir(exist_ok=True)
                    shutil.copy2(dest, d / dest.name)
        names.append(fw["file_name"])
    return names


def cover(client, rom_id):
    """Cover art as base64 for Steam's grid image, or None."""
    path = client.rom(rom_id).get("path_cover_large")
    if not path:
        return None
    data = client.fetch_bytes(path)
    return {"data": base64.b64encode(data).decode(), "ext": "png" if data[:4] == b"\x89PNG" else "jpg"}


COVERS = config.SETTINGS_DIR / "covers"  # small cover art for the panel, kept after the first time
_cover_slots = threading.Semaphore(4)  # a long list doesn't send RomM dozens of requests at once


def thumb(client, rom_id, path=""):
    """A game's small cover art for the panel: (data: URL or "" if RomM has none, RomM's path for it).
    `path`: RomM's path, when the list already gave one (saves asking RomM for the game)."""
    rom_id = str(rom_id)
    COVERS.mkdir(parents=True, exist_ok=True)
    mine = sorted(COVERS.glob(f"{rom_id}-*"))
    if not path:
        if mine:
            return _data_url(mine[-1]), ""
        with _cover_slots:
            rom = client.rom(rom_id)
        path = rom.get("path_cover_small") or rom.get("path_cover_large") or ""
        if not path:
            return "", ""
    target = COVERS / f"{rom_id}-{hashlib.sha1(path.encode()).hexdigest()[:10]}"
    if target.exists():
        return _data_url(target), path
    try:
        with _cover_slots:
            data = client.fetch_bytes(path, timeout=15)
    except Exception as e:
        e.cover_path = path  # (so the panel can still try RomM's own address for it)
        raise
    for old in mine:  # the cover changed in RomM: keep only the new one
        old.unlink(missing_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    return _data_url(target), path


# Steam's feature icons on a game page (its "store categories"), from RomM's game modes
STEAM_FEATURES = {"single player": 2, "multiplayer": 1, "co-operative": 9, "split screen": 24}


def details(rom, base_url="", ra_progress=None):
    """Everything RomM knows about a game, for its Steam page: Steam's own fields (description,
    developers, publishers, release date, rating, feature icons), every other fact as
    (label, text) rows, links for the Game Info buttons, and the Activity list (see activity).
    Missing data is simply left out. `base_url`: RomM's address (for the RomM link)."""
    meta = rom.get("metadatum") or {}
    igdb = rom.get("igdb_metadata") or {}
    ra = rom.get("merged_ra_metadata") or rom.get("ra_metadata") or {}
    hltb = rom.get("hltb_metadata") or {}
    mine = rom.get("rom_user") or {}

    def pick(*values):
        for v in values:
            if v:
                return v
        return [] if isinstance(values[-1], list) else None

    def names(values):
        return [v if isinstance(v, str) else (v or {}).get("name", "") for v in values or []]

    companies = names(pick(meta.get("companies"), igdb.get("companies"), []))
    developers = names(pick(meta.get("developers"), ra.get("developers"), companies[:1], []))
    publishers = names(pick(meta.get("publishers"), ra.get("publishers"), companies[1:2], []))
    date = pick(meta.get("first_release_date"), igdb.get("first_release_date"), ra.get("first_release_date"))
    if isinstance(date, (int, float)) and date > 1e11:  # milliseconds
        date /= 1000
    rating = _number(pick(meta.get("average_rating"), igdb.get("total_rating")))
    if rating is not None and rating <= 10:  # a 0-10 score
        rating *= 10
    modes = pick(meta.get("game_modes"), igdb.get("game_modes"), [])

    facts = []
    def fact(label, value):
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value if v)
        if value not in (None, "", 0):
            facts.append([label, str(value)])

    fact("Genres", pick(meta.get("genres"), igdb.get("genres"), ra.get("genres"), []))
    fact("Themes", igdb.get("themes"))
    fact("Game modes", modes)
    fact("Players", meta.get("player_count") if str(meta.get("player_count") or "") not in ("", "1") else "")
    fact("Perspective", igdb.get("player_perspectives"))
    fact("Franchise", pick(meta.get("franchises"), igdb.get("franchises"), []))
    fact("Series", pick(meta.get("collections"), igdb.get("collections"), []))
    fact("Age rating", pick(meta.get("age_ratings"), [a.get("rating", "") for a in igdb.get("age_ratings") or [] if isinstance(a, dict)], []))
    if rating:
        count = meta.get("rating_count") or igdb.get("total_rating_count")
        fact("Rating", f"{round(rating)}/100" + (f" ({count:,} ratings)" if isinstance(count, int) and count else ""))
    fact("How long to beat", " · ".join(f"{label} {_hours(hltb.get(key))}" for key, label in (
        ("main_story", "Main"), ("main_plus_extra", "Main + extras"), ("completionist", "Completionist"))
        if _hours(hltb.get(key))))
    cheevos = [a for a in ra.get("achievements") or [] if isinstance(a, dict)]
    if cheevos:
        points = sum(a.get("points") or 0 for a in cheevos)
        fact("RetroAchievements", f"{len(cheevos)} achievements, {points:,} points")
    fact("Also known as", (rom.get("alternative_names") or igdb.get("alternative_names") or [])[:3])
    fact("Keywords", (igdb.get("keywords") or [])[:8])
    fact("Regions", rom.get("regions"))
    fact("Languages", rom.get("languages"))
    fact("Revision", rom.get("revision"))
    fact("Tags", rom.get("tags"))
    fact("Platform", rom.get("platform_display_name"))
    size = rom.get("fs_size_bytes") or 0
    fact("File", f"{rom.get('fs_name', '')}" + (f" · {size / 1024**3:.1f} GB" if size >= 1024**3 else f" · {size / 1024**2:.0f} MB" if size else ""))
    status = [str(mine.get("status")).replace("_", " ").capitalize() if mine.get("status") else "",
              f"{mine['completion']}% complete" if mine.get("completion") else "",
              f"rated {mine['rating']}/10" if mine.get("rating") else "",
              "now playing" if mine.get("now_playing") else "", "in backlog" if mine.get("backlogged") else ""]
    fact("In your RomM", [x for x in status if x])
    fact("RomM game", f"#{rom['id']}" if rom.get("id") else "")

    return {
        "description": (rom.get("summary") or "").strip(),
        "developers": [d for d in developers if d][:4],
        "publishers": [p for p in publishers if p][:4],
        "release_date": int(date) if isinstance(date, (int, float)) and date > 0 else None,
        "rating": round(rating) if rating else None,
        "features": sorted({STEAM_FEATURES[m.lower()] for m in names(modes) if m and m.lower() in STEAM_FEATURES}),
        "facts": facts,
        "links": links(rom, base_url),
        "activity": activity(rom, ra_progress),
    }


def links(rom, base_url=""):
    """[label, address] for the buttons under Game Info: the game in RomM, and the sites RomM matched it to."""
    out = []
    if base_url and rom.get("id"):
        out.append(["RomM", f"{base_url.rstrip('/')}/rom/{rom['id']}"])
    if rom.get("ra_id"):
        out.append(["RetroAchievements", f"https://retroachievements.org/game/{rom['ra_id']}"])
    if rom.get("hltb_id"):
        out.append(["HowLongToBeat", f"https://howlongtobeat.com/game/{rom['hltb_id']}"])
    if rom.get("youtube_video_id"):
        out.append(["Trailer", f"https://www.youtube.com/watch?v={urllib.parse.quote(str(rom['youtube_video_id']))}"])
    return out


def activity(rom, ra_progress=None, limit=40):
    """What's happened with a game, newest first, for its Steam page's Activity:
    [{"at": unix time, "kind": note|achievement|award|save|state|played, "title", "body", "by", "image"}].
    From RomM: notes (yours and other players' public ones), RetroAchievements unlocks
    (`ra_progress`: the user's progress from /api/users/me), saves and states, last played."""
    events = []

    def add(when, kind, title, body="", by="", image=""):
        at = _when(when)
        if at:
            events.append({"at": at, "kind": kind, "title": title, "body": body, "by": by, "image": image})

    for n in rom.get("all_user_notes") or []:
        text = (n.get("content") or "").strip()
        add(n.get("updated_at") or n.get("created_at"), "note", (n.get("title") or "").strip() or "Note",
            text if len(text) <= 1200 else text[:1200].rstrip() + "…", n.get("username") or "")

    ra = rom.get("merged_ra_metadata") or rom.get("ra_metadata") or {}
    badges = {a.get("badge_id"): a for a in ra.get("achievements") or [] if isinstance(a, dict) and a.get("badge_id")}
    for game in (ra_progress or {}).get("results") or []:
        if not rom.get("ra_id") or game.get("rom_ra_id") != rom.get("ra_id"):
            continue
        for e in game.get("earned_achievements") or []:
            a = badges.get(e.get("id")) or {}
            body = [a.get("description") or "", f"{a['points']} points" if a.get("points") else "", "hardcore" if e.get("date_hardcore") else ""]
            add(e.get("date_hardcore") or e.get("date"), "achievement", a.get("title") or "Achievement unlocked",
                " · ".join(x for x in body if x), image=a.get("badge_url") or "")
        if game.get("highest_award_kind"):
            add(game.get("most_recent_awarded_date"), "award", f"{str(game['highest_award_kind']).replace('-', ' ').capitalize()} on RetroAchievements",
                f"{game.get('num_awarded') or 0} of {game.get('max_possible') or 0} achievements")

    for kind, label in (("save", "Save"), ("state", "Save state")):
        for s in sorted(rom.get(f"user_{kind}s") or [], key=lambda s: str(s.get("updated_at") or ""), reverse=True)[:10]:
            add(s.get("updated_at") or s.get("created_at"), kind, f"{label} in RomM",
                " · ".join(x for x in (s.get("file_name"), s.get("emulator")) if x))
    add((rom.get("rom_user") or {}).get("last_played"), "played", "Played")

    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


def _when(value):
    """RomM's and RetroAchievements' times (ISO, "2026-01-02 10:00:00", seconds or ms) as unix time, or None."""
    if isinstance(value, (int, float)) and value > 0:
        return int(value / 1000 if value > 1e11 else value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"\.\d+", "", value.strip().replace("Z", "+00:00").replace(" ", "T", 1))  # (older Pythons: no fractions)
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            when = datetime.datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)  # both report UTC
    return int(when.timestamp())


SHOTS = config.DATA_DIR / "shots"  # RomM's screenshots, copied for Steam's game pages


def screenshots(client, rom_id, paths, limit=10):
    """Copies on this PC of RomM's screenshots of a game: ["shots/<rom>/<file>"] (under DATA_DIR).
    Steam's pages can't show pictures from a plain-http (or self-signed) RomM, but they can show
    what Decky serves from DATA_DIR. Ones already copied aren't fetched again; old ones are removed."""
    folder = SHOTS / str(rom_id)
    wanted = {}
    for path in (paths or [])[:limit]:
        ext = Path(urllib.parse.urlparse(path).path).suffix.lower()
        wanted[hashlib.sha1(path.encode()).hexdigest()[:12] + (ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg")] = path
    out = []
    if wanted:
        folder.mkdir(parents=True, exist_ok=True)
    for name, path in wanted.items():
        target = folder / name
        if not target.exists():
            try:
                data = client.fetch_bytes(path, timeout=20)
            except Exception as e:
                config.log.warning("Screenshot %s of rom %s not copied: %s", path, rom_id, e)
                continue
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        out.append(f"shots/{rom_id}/{name}")
    if folder.is_dir():
        for old in folder.iterdir():
            if old.name not in wanted:
                old.unlink(missing_ok=True)
        if not any(folder.iterdir()):
            folder.rmdir()
    return out


def _number(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _hours(value):
    """HLTB times are seconds: "12 h" (or "" if unknown)."""
    v = _number(value)
    if not v:
        return ""
    hours = v / 3600 if v > 500 else v
    return f"{hours:.0f} h" if hours >= 1 else f"{round(hours * 60)} min"


def _data_url(path):
    data = Path(path).read_bytes()
    kind = ("png" if data[:4] == b"\x89PNG" else "webp" if data[8:12] == b"WEBP" else
            "gif" if data[:3] == b"GIF" else "jpeg")
    return f"data:image/{kind};base64,{base64.b64encode(data).decode()}"


# ---------- helpers ----------

def _pick_launch_file(path, exts, preferred=()):
    """The file to hand the emulator: the download itself, or the best match inside a folder.
    RomM's main game file wins over updates and DLC sitting next to it."""
    if path.is_file():
        return path
    files = sorted(p for p in path.rglob("*") if p.is_file())
    for p in files:
        if p.name in preferred and any(p.name.lower().endswith("." + ext) for ext in exts):
            return p
    for ext in exts:
        for p in files:
            name = p.name.lower()
            if name == ext or name.endswith("." + ext):
                if ext == "m3u" and p.stat().st_size == 0:
                    continue
                return p
    return None


def _remove_path(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
