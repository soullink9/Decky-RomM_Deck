"""Games on this PC: download, recognise games already there, launch, and remove; BIOS files."""
import json
import os
import re
import shlex
import shutil
import time
import unicodedata
import urllib.parse
import zipfile
from pathlib import Path

from . import config, metadata, saves, systems

RYUJINX_SYSTEM_DIRS = [
    config.HOME / ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/system",  # Ryubing flatpak
    config.HOME / ".config/Ryujinx/system",                                    # EmuDeck's Ryujinx
]


def installed():
    """{rom id: entry} for every game RomM Deck knows is on this PC (installed.json). An entry: name,
    platform, system (SYSTEMS key), path (the file or folder in Emulation/roms), launch (the file
    handed to the emulator), app_id (its Steam card), and for taken-over cards the original command."""
    return config.load("installed")


def _without_tags(name):
    """A game name without its "(USA)", "[!]", "[v0]"... tags, for searching RomM by name."""
    return re.sub(r"\s*[\(\[].*?[\)\]]", "", name).strip()


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
    if candidates is None:  # search RomM by the file's name and by the game's name
        found = {}
        for term in {_without_tags(Path(old["path"]).stem), old["name"]}:
            for r in client.roms("search", term) if term else []:
                found[r["id"]] = r
        candidates = found.values()
    candidates = [r for r in candidates if r["id"] != int(rom_id)]
    pick = _same_game(candidates, old)
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


def _same_game(candidates, old):
    """Of RomM entries, the one that is the game `old` (an installed.json entry): best, one whose
    file on this PC is the very same file; else the only one on the same platform with the same
    name. None if neither is certain (never guess with someone's saves)."""
    path = Path(old["path"]).resolve()
    for r in candidates:
        copy = local_copy(r)
        if copy and copy.resolve() == path:
            return r
    same_name = [r for r in candidates if r["platform_id"] == old["platform_id"] and (r.get("name") or "") == old["name"]]
    return same_name[0] if len(same_name) == 1 else None


def install(client, rom_id, progress=None):
    """Download a rom into its EmuDeck folder. Returns the installed.json entry."""
    rom = client.rom(rom_id)
    system = systems.for_rom(rom)
    exts = system["exts"] if system else []
    folder = config.emudeck()["roms"] / (system["folder"] if system else rom["platform_fs_slug"])
    folder.mkdir(parents=True, exist_ok=True)

    multi = rom.get("has_multiple_files")
    if multi and extra_files(rom) and extras_dir():  # Switch: updates & DLC go to their own folder
        return _install_split(client, rom, folder, progress)

    tmp = folder / f".romm-{rom_id}.part"
    client.download(f"/api/roms/{rom_id}/content/{urllib.parse.quote(rom['fs_name'])}", tmp, progress)

    # RomM sends multi-file games (multi-disc, PS3 folders...) as one zip with an .m3u.
    # Single zipped roms are unpacked too, unless the emulator reads zips itself.
    unzip = multi or (system and rom["fs_extension"].lower() == "zip" and "zip" not in exts)
    if multi:
        dest = folder / rom["fs_name"]  # a folder named like RomM's entry
    elif unzip:
        dest = folder / rom["fs_name_no_ext"]  # the zip's contents, in a folder without ".zip"
    else:
        dest = folder / _file_name(rom)
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


def extra_files(rom):
    """A game's update and DLC files, as RomM lists them."""
    return [f for f in rom.get("files") or [] if f.get("category") in EXTRA_KINDS]


def _install_split(client, rom, folder, progress):
    """A Switch game with updates/DLC: the game file into roms/switch, the rest into extras_dir()."""
    game_files = _game_files(rom)
    if not game_files:
        raise ValueError("RomM doesn't say which of this game's files is the game itself")
    overall = _OverallProgress(progress, game_files + extra_files(rom))
    for f in game_files:
        dest = folder / f["file_name"]
        if dest.exists():
            problem = _not_this_game(dest, rom["id"])
            if problem:
                raise ValueError(f"Not downloaded: {dest.name} is already there and {problem}")
        _download_file(client, rom, f, dest, overall.update)
        overall.file_done(f)
    with config.editing("installed") as games:
        games[str(rom["id"])] = _entry(rom, folder / game_files[0]["file_name"])
    _get_extras(client, rom, overall)
    return installed()[str(rom["id"])]


class _OverallProgress:
    """One progress bar across several files: each file's download reports its own bytes, and this
    adds the files already finished, so the panel shows one bar for the whole game."""

    def __init__(self, report, files):
        """`report(done, total)` is called as bytes arrive (or None); `files` are RomM's file records."""
        self.report = report  # report(done bytes, total bytes), or None
        self.total = sum(f["file_size_bytes"] for f in files) or 1  # (never 0: the panel divides by it)
        self.finished = 0  # bytes in files already done

    def update(self, done_in_file, _file_total):
        """Progress within the current file (the signature RomM.download calls back with)."""
        if self.report:
            self.report(self.finished + done_in_file, self.total)

    def file_done(self, f):
        """A file is finished (or was already there): count all of it."""
        self.finished += f["file_size_bytes"]


def download_extras(client, rom_id, progress=None):
    """Get a game's updates and DLC (for a game that's already on the PC). Returns how many."""
    rom = client.rom(rom_id)
    if str(rom_id) not in installed():
        raise ValueError("Download the game first")
    return _get_extras(client, rom, _OverallProgress(progress, extra_files(rom)))


def _get_extras(client, rom, overall):
    """Download a game's updates and DLC into extras_dir(), skipping files already there in full,
    and remember them on the game's entry (so Remove deletes them too). Returns how many there are."""
    folder = extras_dir()
    if not folder:
        raise ValueError("Set the Switch updates & DLC folder first (on the plugin's home page)")
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in extra_files(rom):
        dest = folder / f["file_name"]
        already_there = dest.is_file() and dest.stat().st_size == f["file_size_bytes"]
        if not already_there:
            _download_file(client, rom, f, dest, overall.update)
        overall.file_done(f)
        saved.append(str(dest))
    with config.editing("installed") as games:
        game = games.get(str(rom["id"]))
        if game:
            game["extras"] = sorted(set(game.get("extras", []) + saved))
            game["extras_dir"] = str(folder)
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


def find_existing(rom_list):
    """Add games from RomM that are already in Emulation/roms (put there before this plugin)
    to installed.json. Returns the ids now known to be on this PC."""
    games = installed()
    found = {}
    for rom in rom_list:
        if str(rom["id"]) in games:
            continue
        path = local_copy(rom)
        if not path:
            continue
        # A file belongs to one RomM entry only: a duplicate entry in RomM doesn't get it too
        known = [*games.values(), *found.values()]
        if any(Path(g["path"]).resolve() == path.resolve() for g in known):
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
    for path in paths:  # a game already on this PC: the card starts its file, or a file in its folder
        for rom_id, g in games.items():
            known = {Path(g["path"]).resolve()}
            if g.get("launch"):
                known.add(Path(g["launch"]).resolve())
            if path in known:
                return int(rom_id)
            for k in known:  # (a folder that's a whole platform's doesn't count as the game's)
                if k.is_dir() and path.is_relative_to(k) and not _not_this_game(k, rom_id):
                    return int(rom_id)

    for path in paths:  # not known yet: search RomM for it
        # by the file's name, its folder's, and the game folder's: a PS3 card starts
        # roms/ps3/<game>/PS3_GAME/USRDIR/EBOOT.BIN, where only <game> is the game's name
        rel = path.relative_to(roms_dir).parts
        game_folder = rel[1] if len(rel) > 2 else ""
        names = [path.stem, path.parent.name, game_folder, re.sub(r"\.ps3$", "", game_folder, flags=re.I)]
        for name in dict.fromkeys(n for n in names if n):  # (each name once, in this order)
            term = _without_tags(name)
            for rom in client.roms("search", term) if term else []:
                if _card_starts(rom, path):
                    find_existing([rom])
                    return rom["id"]
    return None


def _card_starts(rom, path):
    """Does a card that starts `path` start this RomM game? Yes if `path` is one of its files on this
    PC (the game, or say its update .nsp), or a file inside its folder."""
    copy = local_copy(rom)
    if not copy:
        return False
    if path in files_on_pc(rom):
        return True
    in_folder = copy.is_dir() and path.is_relative_to(copy.resolve())
    return in_folder and not _not_this_game(copy, rom["id"])


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
    want_tid = None
    if tid and re.fullmatch(r"[0-9A-Fa-f]{16}", tid):
        want_tid = systems.switch_base_title(int(tid, 16))
    want_names = {_simple(n) for n in (rom.get("name"), rom["fs_name_no_ext"]) if n} - {""}
    # Three kinds of match, best first; within a kind there must be exactly one
    base_file, by_tid, by_name = [], [], []  # tagged with the base game's id / its update's or DLC's / same name
    for folder in folders:
        by_name += _game_folders_named(folder, want_names, exts)
        for path in _listing(folder):
            if not any(path.name.lower().endswith("." + e) for e in exts):
                continue
            tags = [int(t, 16) for t in re.findall(r"\[(01[0-9A-Fa-f]{14})\]", path.name)]
            if want_tid is not None and want_tid in tags:
                base_file.append(path)
            elif want_tid is not None and want_tid in [systems.switch_base_title(t) for t in tags]:
                by_tid.append(path)  # its update or DLC
            elif _simple(path.stem) in want_names:
                by_name.append(path)
    for found in (base_file, by_tid, by_name):
        if len(set(found)) == 1:
            return found[0]
    return None


def _game_folders_named(folder, want_names, exts):
    """Sub-folders of `folder` that are a game kept as a folder (PS3: <game>/PS3_GAME/USRDIR/EBOOT.BIN)
    and named like it once simplified. A ".ps3" at the end of the folder name is ignored (a common
    naming for PS3 game folders)."""
    out = []
    try:
        for d in folder.iterdir():
            if not d.is_dir() or d.name.startswith("."):
                continue
            name = _simple(re.sub(r"\.ps3$", "", d.name, flags=re.I))
            if name in want_names and _pick_launch_file(d, exts):
                out.append(d)
    except OSError:
        pass  # the platform folder doesn't exist
    return out


def _simple(name):
    """ "The Legend of Zelda: Tears of the Kingdom (USA) [v0]" -> "legendofzeldatearsofkingdom" """
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()  # Pokémon -> Pokemon
    name = re.sub(r"[\(\[].*?[\)\]]", "", name.lower()).replace("&", "and")
    return "".join(w for w in re.findall(r"[a-z0-9]+", name) if w != "the")


_listings = {}  # folder -> (when listed, folder's mtime, files): see _listing


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
    folders = [roms_dir / rom["platform_fs_slug"]]
    if system:
        folders.insert(0, roms_dir / system["folder"])
    found = set()
    for folder in folders:
        for f in rom.get("files") or []:
            path = folder / f["file_name"]
            if path.is_file():
                found.add(path.resolve())
    copy = local_copy(rom)
    if copy:
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
    shutil.rmtree(metadata.SHOTS / str(rom_id), ignore_errors=True)  # its Steam page's screenshots
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
    if path.is_dir():
        is_platform_folder = path.parent == roms_dir or path in platform_folders
        holds_platform_folder = any(f.is_relative_to(path) for f in platform_folders)
        if is_platform_folder or holds_platform_folder:
            return "is a whole platform folder"
    for other_id, g in installed().items():
        if other_id == str(rom_id):
            continue
        for p in (g.get("path"), g.get("launch")):
            if p and Path(p).resolve().is_relative_to(path):  # (is_relative_to is also true when equal)
                return f"also holds {g['name']}"
    return None


def set_app_id(rom_id, app_id):
    """Remember the Steam card the frontend made for a game (so it can be found and removed later)."""
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


def launch_command(game, extra_args=()):
    """The command that starts a game, plus its environment and folder.
    A taken-over card runs its original command, the way Steam would have.
    extra_args (from a controller preset) go to the emulator first, before the game's own arguments:
    EmuDeck's launchers pass all their arguments on to the emulator."""
    system = systems.SYSTEMS[game["system"]]
    if game.get("original"):
        o = game["original"]
        exe, options = o["exe"], o["options"] or ""
        if extra_args:
            # only when the card runs this platform's EmuDeck launcher: anything else (ES-DE, RetroArch...)
            # wouldn't understand the emulator's arguments
            if Path(exe.strip().strip('"')).name == system.get("launcher"):
                exe = f"{exe} {shlex.join(extra_args)}"
            else:
                config.log.warning("Card runs %s, not %s: the controller preset's settings can't be given to it",
                                   exe, system.get("launcher"))
        # Steam's rule for launch options: "%command%" stands for the card's target; without it,
        # the options are added after the target. Run through bash, as Steam would.
        if "%command%" in options:
            cmd = options.replace("%command%", exe)
        else:
            cmd = f"{exe} {options}"
        return ["/bin/bash", "-c", cmd], dict(os.environ), o["start_dir"].strip('"') or None
    launcher = config.emudeck()["launchers"] / system["launcher"]
    args = [a.replace("{rom}", game["launch"]).replace("{cores}", str(systems.CORES)) for a in system["args"]]
    return ["bash", str(launcher), *extra_args, *args], {**os.environ, **system["env"]}, None


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
    """Delete a file or a whole folder (callers check _not_this_game first)."""
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
