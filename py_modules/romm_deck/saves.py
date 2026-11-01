"""Save and save-state sync with RomM.

How it works
  * A game's saves can be in Emulation/saves/<emu>/ (EmuDeck), in the emulator's own
    folders, or next to the game in roms/ (see roots()).
  * The launcher snapshots those folders before a game starts and after it closes.
    Whatever changed belongs to that game, and is remembered in sync.json.
  * Upload: emulators that keep one flat folder of files (RetroArch, melonDS, ...)
    upload each file as-is, so RomM's web player can use them too. Everything else
    (Switch, PS3, Wii, ...) uploads one zip per game named "<emu>-<kind>.romm.zip".
  * Download is the reverse, and only happens when RomM has something new.
  * Conflict (changed here AND on RomM since the last sync): the newer copy wins
    locally, and the other copy is uploaded to RomM as "conflict-<time>-<name>".
  * "Use RomM's saves" (force): RomM's copy always wins; this PC's goes up as "backup-...".
"""
import contextlib
import fcntl
import hashlib
import io
import os
import re
import struct
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import config, systems

KINDS = ("saves", "states")
UPLOAD_FIELD = {"saves": "saveFile", "states": "stateFile"}  # the form field RomM's upload expects
MAX_FILE = 512 * 1024 * 1024  # skip anything bigger than this (disk images, not saves)

# Sub-folders of Emulation/saves/<emu> that aren't game saves
SKIP = {"system", "system_saves", "trophy", "profiles", "screenshots", "cheats", "textures"}
# Dolphin's Wii folder is the whole virtual NAND; only title/ holds game saves
SUBFOLDER = {"Wii": "title"}

# Files are identified by a "key": "<folder label>/<path inside that folder>", e.g.
# "ra-saves/Metroid Fusion (USA).srm". Keys (not full paths) are what sync.json and the zips store,
# so the same save lands in the right place on a machine whose folders are somewhere else.
#
# Each emulator's own save folders, used alongside EmuDeck's links because EmuDeck
# doesn't always manage to point an emulator at Emulation/saves. Folders that don't
# exist are ignored, and a folder found twice is only watched once.
# Format: emu -> [(kind, label, folder)]; "{bios}" means Emulation/bios.
H = config.HOME
FP = H / ".var/app"  # flatpak app data
DEFAULT_ROOTS = {
    "retroarch": [
        ("saves", "ra-saves", FP / "org.libretro.RetroArch/config/retroarch/saves"),
        ("states", "ra-states", FP / "org.libretro.RetroArch/config/retroarch/states"),
        ("saves", "ra-native-saves", H / ".config/retroarch/saves"),
        ("states", "ra-native-states", H / ".config/retroarch/states"),
        ("saves", "dreamcast-vmu", "{bios}/dc"),  # Flycast core keeps VMU saves in the BIOS folder
    ],
    "dolphin": [
        ("saves", "dolphin-gc", FP / "org.DolphinEmu.dolphin-emu/data/dolphin-emu/GC"),
        ("saves", "dolphin-wii", FP / "org.DolphinEmu.dolphin-emu/data/dolphin-emu/Wii/title"),
        ("states", "dolphin-states", FP / "org.DolphinEmu.dolphin-emu/data/dolphin-emu/StateSaves"),
        ("saves", "dolphin-native-gc", H / ".local/share/dolphin-emu/GC"),
        ("saves", "dolphin-native-wii", H / ".local/share/dolphin-emu/Wii/title"),
        ("states", "dolphin-native-states", H / ".local/share/dolphin-emu/StateSaves"),
    ],
    "ryujinx": [
        ("saves", "ryubing-save", FP / "io.github.ryubing.Ryujinx/config/Ryujinx/bis/user/save"),
        ("saves", "ryubing-saveMeta", FP / "io.github.ryubing.Ryujinx/config/Ryujinx/bis/user/saveMeta"),
        ("saves", "ryujinx-save", H / ".config/Ryujinx/bis/user/save"),
        ("saves", "ryujinx-saveMeta", H / ".config/Ryujinx/bis/user/saveMeta"),
        ("saves", "ryujinx-portable-save", H / "Applications/publish/portable/bis/user/save"),
        ("saves", "ryujinx-portable-saveMeta", H / "Applications/publish/portable/bis/user/saveMeta"),
    ],
    "azahar": [
        ("saves", "azahar-sdmc", H / ".local/share/azahar-emu/sdmc"),
        ("states", "azahar-states", H / ".local/share/azahar-emu/states"),
        ("saves", "azahar-flatpak-sdmc", FP / "io.github.azahar.Azahar/data/azahar-emu/sdmc"),
        ("states", "azahar-flatpak-states", FP / "io.github.azahar.Azahar/data/azahar-emu/states"),
    ],
    "Cemu": [
        ("saves", "cemu-save", H / ".local/share/Cemu/mlc01/usr/save"),
    ],
    "duckstation": [
        ("saves", "duckstation-memcards", H / ".local/share/duckstation/memcards"),
        ("states", "duckstation-states", H / ".local/share/duckstation/savestates"),
    ],
    "pcsx2": [
        ("saves", "pcsx2-memcards", H / ".config/PCSX2/memcards"),
        ("states", "pcsx2-states", H / ".config/PCSX2/sstates"),
        ("saves", "pcsx2-flatpak-memcards", FP / "net.pcsx2.PCSX2/config/PCSX2/memcards"),
        ("states", "pcsx2-flatpak-states", FP / "net.pcsx2.PCSX2/config/PCSX2/sstates"),
    ],
    "rpcs3": [
        ("saves", "rpcs3-savedata", H / ".config/rpcs3/dev_hdd0/home/00000001/savedata"),
        ("states", "rpcs3-states", H / ".config/rpcs3/savestates"),
    ],
    "ppsspp": [
        ("saves", "ppsspp-savedata", FP / "org.ppsspp.PPSSPP/config/ppsspp/PSP/SAVEDATA"),
        ("states", "ppsspp-states", FP / "org.ppsspp.PPSSPP/config/ppsspp/PSP/PPSSPP_STATE"),
        ("saves", "ppsspp-native-savedata", H / ".config/ppsspp/PSP/SAVEDATA"),
        ("states", "ppsspp-native-states", H / ".config/ppsspp/PSP/PPSSPP_STATE"),
    ],
    # melonDS saves next to the game by default; the game's folder is always watched (see roots)
}


# ---------- where a game's saves can be ----------

def roots(game):
    """Every folder a game's saves might be in: [(kind, label, folder)].

    1. Emulation/saves/<emu>/*  (EmuDeck's links and folders)
    2. the emulator's own folders (DEFAULT_ROOTS), in case EmuDeck didn't set it up
    3. the folder a single-file game sits in, for emulators that save next to it (melonDS)
    kind is 'saves' or 'states'.
    """
    emu = emu_for(game)
    paths = config.emudeck()
    found = []
    base = _emudeck_saves_folder(paths["saves"], emu)
    if base:
        for child in sorted(base.iterdir()):
            if child.name not in SKIP and child.is_dir():
                kind = "states" if "state" in child.name.lower() else "saves"
                found.append((kind, child.name, child / SUBFOLDER.get(child.name, "")))
    for kind, label, folder in DEFAULT_ROOTS.get(emu, []):
        found.append((kind, label, Path(str(folder).replace("{bios}", str(paths["bios"])))))
    rom = Path(game["path"])
    if emu in systems.SAVES_NEXT_TO_GAME and rom.is_file():  # only files named after the game count there
        found.append(("saves", "rom-folder", rom.parent))

    unique = []
    for kind, label, folder in found:
        if not folder.is_dir():
            continue
        folder = folder.resolve()
        # watch each folder once, even when it's linked twice or sits inside another one
        overlaps = any(folder == f or folder.is_relative_to(f) or f.is_relative_to(folder) for _, _, f in unique)
        if not overlaps:
            unique.append((kind, label, folder))
    return unique


def _emudeck_saves_folder(saves_dir, emu):
    """Emulation/saves/<emu>, matched without regard to case (EmuDeck writes "Cemu" but "dolphin"),
    or None if EmuDeck has no folder for this emulator."""
    if not saves_dir.is_dir():
        return None
    for d in saves_dir.iterdir():
        if d.name.lower() == emu.lower():
            return d
    return None


def _where(folders):
    """{label: folder} for the folders roots() found, to turn file keys into real paths."""
    return {label: path for _, label, path in folders}


def _main_labels(folders):
    """{kind: label of the first folder of that kind}: the emulator's main saves and states folders,
    where a single file from RomM goes when its key doesn't say otherwise."""
    main = {}
    for kind, label, _ in folders:
        main.setdefault(kind, label)
    return main


def snapshot(game):
    """{"label/relative/path": (size, mtime)} for every file in the game's save folders."""
    snap = {}
    for _, label, root in roots(game):
        for folder, _, files in os.walk(root):
            for name in files:
                p = Path(folder, name)
                with contextlib.suppress(OSError):
                    st = p.stat()
                    snap[f"{label}/{p.relative_to(root).as_posix()}"] = (st.st_size, st.st_mtime_ns)
    return snap


def remember_session(rom_id, game, before, after):
    """Files that changed while the game ran now belong to this game (if they can be its saves)."""
    folders = roots(game)
    kind_of = {label: kind for kind, label, _ in folders}
    where = _where(folders)
    with _locked() as state:
        entry = _entry(state, rom_id, emu_for(game))
        for key, stat in after.items():
            label = key.split("/", 1)[0]
            if before.get(key) == stat or label not in kind_of:
                continue  # unchanged, or not in a folder we watch
            known = entry["files"][kind_of[label]]
            if key not in known and _could_be_save(key, _path(where, key), game):
                known.append(key)


def _could_be_save(key, path, game):
    """Never treat a game file, or anything belonging to another game, as this game's save.
    In Emulation/roms (melonDS saves next to the game) only files named after the game that
    aren't game files count. (Emulators' own save folders are left alone: Wii and Switch saves
    are often .bin files.)"""
    if path is None:
        return False
    if key.startswith("rom-folder/") and (path.suffix.lower().lstrip(".") in systems.GAME_EXTS
                                          or not _named_after(path.name, game)):
        return False
    return not _inside_a_game(path)


def _named_after(name, game):
    """"<game>.srm", "<game>.state1", "<game>_1.mcd" (a DuckStation memory card slot) -- but not
    "<game>_2.srm" or "<game>_2.sav", which are a sequel's."""
    stem = Path(game.get("launch") or game["path"]).stem
    return bool(re.match(re.escape(stem) + r"(\.|_\d+\.mcd$)", name, re.I))


def _inside_a_game(path):
    """Is this file a downloaded game's file, or inside a game's folder?"""
    path = path.resolve()
    for g in config.load("installed").values():
        for p in (g.get("path"), g.get("launch")):
            if not p:
                continue
            game_path = Path(p).resolve()
            if path == game_path or (game_path.is_dir() and path.is_relative_to(game_path)):
                return True
    return False


# Save files shared by many games (one memory card for every game): never deleted
SHARED = re.compile(r"(^Mcd\d+\.ps2$|^shared_card_\d+\.mcd$|^MemoryCard[AB].*\.raw$)", re.I)


def move_history(old_id, new_id):
    """A game moved to another RomM entry: keep which files are its saves, but forget what was
    synced, so the next sync treats the new entry as empty and uploads everything to it."""
    with _locked() as state:
        old = state.pop(str(old_id), None)
        if old:
            new = state.setdefault(str(new_id), _entry({}, new_id, old["emu"]))
            for kind in KINDS:
                new["files"][kind] += [k for k in old["files"][kind] if k not in new["files"][kind]]
            new["hashes"], new["server"] = {}, {k: {} for k in KINDS}
    with config.editing("sync-status") as st:  # the new entry hasn't been synced yet: the page says so
        st.pop(str(old_id), None)


# ---------- removing a game ----------

def not_on_romm(client, rom_id, game):
    """This game's save files that RomM doesn't hold an identical copy of: [key]. Empty = safe."""
    folders = roots(game)
    where, main = _where(folders), _main_labels(folders)
    with _locked() as state:
        entry = _entry(state, rom_id, emu_for(game))
        _claim_by_name(entry, folders, game)
        _claim_switch(entry, folders, _switch_title(client, rom_id, game))
        local = {}  # key -> sha1 of the file on this PC (None: too big to sync, so never "safe")
        for kind in KINDS:
            for k in entry["files"][kind]:
                p = _path(where, k)
                if p is not None and p.is_file():
                    local[k] = _sha1(p) if _usable(p) else None
    remote = {}  # key -> sha1 of RomM's copy, after unpacking zips the same way a pull would
    for kind in KINDS:
        chosen, _ = _choose(client.assets(kind, rom_id), kind, entry["emu"], _game_stem(game))
        for item, local_name in chosen:
            data = client.fetch_bytes(f"/api/{kind}/{item['id']}/content", timeout=120)
            files = _unpack(item["file_name"], data, kind, main, local_name) or {}
            for key, blob in files.items():
                remote[key] = hashlib.sha1(blob).hexdigest()
    return [k for k, h in local.items() if h is None or remote.get(k) != h]


def delete_local(rom_id, game):
    """Delete this game's save files from the PC (call not_on_romm first!).
    Files another game also uses are kept. Returns (deleted, kept) file names."""
    folders = roots(game)
    where = _where(folders)
    deleted, kept = [], []
    with _locked() as state:
        entry = state.pop(str(rom_id), None)  # forget its sync history: a re-download pulls everything
        if not entry:
            return deleted, kept
        others = {k for rid, e in state.items() for kind in KINDS for k in e["files"][kind]}
        for kind in KINDS:
            for k in entry["files"][kind]:
                p = _path(where, k)
                if p is None or not p.is_file():
                    continue
                if k in others or SHARED.search(p.name) or not _could_be_save(k, p, game):
                    kept.append(p.name)  # shared with another game, or not a save at all
                    continue
                p.unlink()
                deleted.append(p.name)
                config.removed_log(f"save of {game['name']}: {p}")
                _remove_empty_parents(p, where[k.split("/", 1)[0]])
    return deleted, kept


def _remove_empty_parents(path, root):
    """Remove the folders a deleted save left empty (a Switch game's numbered folder, say),
    walking up from `path` but never removing `root` itself or anything outside it."""
    for parent in path.parents:
        if parent == root or not parent.is_relative_to(root) or any(parent.iterdir()):
            break
        parent.rmdir()


# ---------- syncing ----------

def sync(client, rom_id, game, direction="both", force=False):
    """See _sync. Also remembers how it went, for the game page ("Saves synced 10 min ago")."""
    try:
        r = _sync(client, rom_id, game, direction, force)
    except Exception as e:
        _mark(rom_id, False, str(e))
        raise
    _mark(rom_id, True)
    return r


def status(rom_id):
    """{"ok", "at" (unix time), "error"} of the game's last sync, or None if it never synced."""
    return config.load("sync-status").get(str(rom_id))


def _mark(rom_id, ok, error=""):
    """Record how the game's last sync went (sync-status.json), for the panel and Steam's Activity."""
    try:
        with config.editing("sync-status") as st:
            st[str(rom_id)] = {"ok": ok, "at": time.time(), "error": error[:200]}
    except OSError:
        pass  # only a status line; never worth failing a sync over


def _sync(client, rom_id, game, direction="both", force=False):
    """Pull newer saves from RomM, then push local changes. direction: both | pull | push.

    force: the chosen side always wins, even if the other is newer.
      pull: take RomM's copy of every save; this PC's goes to RomM first as "backup-<time>-<name>".
      push: upload every save from this PC; RomM's old copy is kept as "backup-<time>-<name>".
    Returns {"down": files downloaded, "up": files uploaded (a zip of 20 files counts 20),
             "other": emulators whose saves RomM has for this game but this PC can't use,
             "on_romm": saves + states RomM lists for this game from this PC's emulator}."""
    folders = roots(game)
    with _locked() as state:
        entry = _entry(state, rom_id, emu_for(game))
        where, main = _where(folders), _main_labels(folders)
        # saves made outside RomM Deck (an emulator's own card, a Switch game's numbered folder)
        _claim_by_name(entry, folders, game)
        _claim_switch(entry, folders, _switch_title(client, rom_id, game))
        down = up = 0
        other = []
        if direction in ("both", "pull"):
            down, other = _pull(client, rom_id, entry, where, main, force, _game_stem(game))
        if direction in ("both", "push"):
            up = _push(client, rom_id, entry, where, main, force)
        # A last check that the uploads really landed under this game in RomM: if they didn't,
        # the sync must fail loudly, because Remove relies on RomM holding every save.
        on_romm = 0
        for kind in KINDS:
            on_romm += sum(1 for item in client.assets(kind, rom_id) if item.get("emulator") == entry["emu"])
        if up and not on_romm:
            raise RuntimeError(f"Uploaded {up} files, but RomM lists no saves for game #{rom_id}")
        return {"down": down, "up": up, "other": other, "on_romm": on_romm}


def _push(client, rom_id, entry, where, main, force=False):
    """Upload this game's files that changed since the last sync (all of them with force).
    Returns how many files went up (each file in a zip counts)."""
    count = 0
    for kind in KINDS:
        keys = [k for k in entry["files"][kind] if _usable(_path(where, k))]
        hashes = {k: _sha1(_path(where, k)) for k in keys}
        changed = keys if force else [k for k in keys if entry["hashes"].get(k) != hashes[k]]
        if not changed:
            continue
        # {name on RomM: {file key: sha1}} for what we're about to upload. One file each when the
        # emulator keeps a flat folder; otherwise one zip with ALL the game's files, not just the
        # changed ones, because a zip on RomM replaces the previous one entirely.
        if _is_flat(keys, main.get(kind)):
            uploads = {k.split("/", 1)[1]: {k: hashes[k]} for k in changed}
        else:
            uploads = {f"{entry['emu']}-{kind}.romm.zip": {k: hashes[k] for k in keys}}
        if force:
            _backup_server_copies(client, rom_id, entry, kind, uploads)
        for name, files in uploads.items():
            if name.endswith(".romm.zip"):
                data = _zip(where, list(files))
            else:
                only_key = next(iter(files))
                data = _path(where, only_key).read_bytes()
            _upload(client, rom_id, entry, kind, name, data)
        entry["hashes"].update(hashes)
        count += len(changed)
        config.log.info("Uploaded %s for rom %s: %s", kind, rom_id, ", ".join(changed))
    return count


def _backup_server_copies(client, rom_id, entry, kind, uploads):
    """Before overwriting RomM's saves, keep any that differ from ours as backup-<time>-<name>."""
    for item in client.assets(kind, rom_id):
        name = item["file_name"]
        if item.get("emulator") != entry["emu"] or name not in uploads:
            continue
        data = client.fetch_bytes(f"/api/{kind}/{item['id']}/content", timeout=120)
        if name.endswith(".romm.zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                theirs = {n: hashlib.sha1(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith("/")}
        else:
            theirs = {next(iter(uploads[name])): hashlib.sha1(data).hexdigest()}
        if theirs != uploads[name]:
            _upload(client, rom_id, entry, kind, f"backup-{time.strftime('%Y%m%d-%H%M%S')}-{name}", data, track=False)


def _choose(items, kind, emu, stem):
    """Which of RomM's saves to pull: [(item, name to save it as, or None to keep its own name)],
    and the emulators of the ones left out.

    Saves this PC uploaded carry its emulator's name. Saves from RomM's web player and other apps
    carry their own (e.g. "mgba"): for RetroArch games those are the same libretro cores, so the
    newest one is used if it's newer than ours, saved under RetroArch's name for the game."""
    items = [i for i in items if not i["file_name"].startswith(("conflict-", "backup-"))]
    chosen = [(i, None) for i in items if i.get("emulator") == emu]
    others = [i for i in items if i.get("emulator") != emu]
    if emu == "retroarch" and stem:
        if kind == "saves":
            fits = [i for i in others if Path(i["file_name"]).suffix.lower() in (".srm", ".sav")]
        else:
            fits = [i for i in others if ".state" in i["file_name"].lower()]
        if fits:
            newest = max(fits, key=lambda i: _timestamp(i["updated_at"]))
            ours = max((_timestamp(i["updated_at"]) for i, _ in chosen), default=0)
            if _timestamp(newest["updated_at"]) > ours:
                target = f"{stem}.srm" if kind == "saves" else f"{stem}.state"
                chosen = [(i, n) for i, n in chosen if i["file_name"] != target]  # older copy of the same file
                chosen.append((newest, target))
                others = []  # we found something usable
    return chosen, sorted({i.get("emulator") or "unknown" for i in others})


def _pull(client, rom_id, entry, where, main, force=False, stem=None):
    """Download RomM's saves and states that are new since the last sync into the game's folders.
    Returns (files written, emulators whose saves RomM has for this game but this PC can't use).

    Before anything on this PC is overwritten, its copy is kept on RomM: as "backup-..." when the
    user asked for RomM's copy (force), or as "conflict-..." when both sides changed (then the newer
    one wins). That way no version of a save is ever lost."""
    count, other = 0, set()
    for kind in KINDS:
        chosen, left_out = _choose(client.assets(kind, rom_id), kind, entry["emu"], stem)
        other.update(left_out)
        for item, local_name in chosen:
            name, stamp = item["file_name"], item["updated_at"]
            if entry["server"][kind].get(name) == stamp and not force:
                continue  # we've already got this one
            data = client.fetch_bytes(f"/api/{kind}/{item['id']}/content", timeout=120)
            files = _unpack(name, data, kind, main, local_name)
            if files is None:
                continue  # a single file, but this emulator has no folder of that kind here
            local = [k for k in files if _usable(_path(where, k))]  # what it would overwrite
            if force:
                _back_up_local(client, rom_id, entry, kind, name, files, local, where)
            elif _changed_since_sync(entry, where, local):
                if _settle_conflict(client, rom_id, entry, kind, name, stamp, data, local, where):
                    continue  # this PC's copy won: nothing to write
            _write_pulled(entry, where, main, kind, files)
            entry["server"][kind][name] = stamp
            count += len(files)
            config.log.info("Downloaded %s %s for rom %s", kind, name, rom_id)
    return count, sorted(other)


def _unpack(name, data, kind, main, local_name=None):
    """A downloaded save as {file key: bytes}: a ".romm.zip" holds keys already; a single file goes
    in the emulator's main folder for that kind, under `local_name` if given. None if there's no
    such folder on this PC."""
    if name.endswith(".romm.zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    if kind in main:
        return {f"{main[kind]}/{local_name or name}": data}
    return None


def _changed_since_sync(entry, where, keys):
    """Has any of these files on this PC changed since the last sync?"""
    return any(entry["hashes"].get(k) != _sha1(_path(where, k)) for k in keys)


def _back_up_local(client, rom_id, entry, kind, name, files, local, where):
    """Before RomM's copy replaces this PC's (force pull): upload this PC's copy as backup-<time>-<name>,
    if it differs at all."""
    differs = [k for k in local if _sha1(_path(where, k)) != hashlib.sha1(files[k]).hexdigest()]
    if not differs:
        return
    if name.endswith(".romm.zip"):
        mine = _zip(where, differs)
    else:
        mine = _path(where, differs[0]).read_bytes()
    _upload(client, rom_id, entry, kind, f"backup-{time.strftime('%Y%m%d-%H%M%S')}-{name}", mine, track=False)
    config.log.info("Replacing %s for rom %s with RomM's copy (backed up)", name, rom_id)


def _settle_conflict(client, rom_id, entry, kind, name, stamp, data, local, where):
    """A save changed both here and on RomM since the last sync. The newer copy wins; the other one is
    uploaded as conflict-<time>-<name>, so it isn't lost. Returns True if this PC's copy won (then
    nothing is downloaded, and the next push uploads it)."""
    local_wins = max(_path(where, k).stat().st_mtime for k in local) > _timestamp(stamp)
    if local_wins:
        loser = data
    elif name.endswith(".romm.zip"):
        loser = _zip(where, local)
    else:
        loser = _path(where, local[0]).read_bytes()
    _upload(client, rom_id, entry, kind, f"conflict-{time.strftime('%Y%m%d-%H%M%S')}-{name}", loser, track=False)
    config.log.info("Conflict on %s (rom %s): kept the %s copy", name, rom_id, "local" if local_wins else "RomM")
    if local_wins:
        entry["server"][kind][name] = stamp  # RomM's version has been seen (and kept as conflict-...)
        for k in local:  # these files are this game's; push() uploads them next
            if k not in entry["files"][kind]:
                entry["files"][kind].append(k)
    return local_wins


def _write_pulled(entry, where, main, kind, files):
    """Write downloaded files into place and remember them as this game's, with their hashes."""
    for key, blob in files.items():
        if key.split("/", 1)[0] not in where and kind in main:
            # a folder this machine doesn't have (the save came from another PC): use the main one
            key = f"{main[kind]}/{key.split('/', 1)[1]}"
        target = _path(where, key)
        if target is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        entry["hashes"][key] = hashlib.sha1(blob).hexdigest()
        if key not in entry["files"][kind]:
            entry["files"][kind].append(key)


def _claim_by_name(entry, folders, game):
    """Find saves for games not started through RomM Deck (e.g. an older Steam ROM Manager card):
    files named after the game file, like "<game>.srm", "<game>.state1" or "<game>_1.mcd"."""
    if not game.get("launch"):
        return
    stem = Path(game["launch"]).stem
    for kind, label, root in folders:
        for folder, _, names in os.walk(root):
            for name in names:
                if not name.startswith(stem) or not _named_after(name, game):
                    continue
                key = f"{label}/{Path(folder, name).relative_to(root).as_posix()}"
                if not _could_be_save(key, Path(folder, name), game):
                    continue
                if key not in entry["files"][kind]:
                    entry["files"][kind].append(key)


# ---------- Switch (Ryujinx): which numbered save folder is which game ----------

def _switch_title(client, rom_id, game):
    """A Switch game's title id as a number (e.g. 0x0100F4700B2E0000), or None.
    From RomM if it read it from the game file, else from a "[0100...]" tag in the file name."""
    if (emu_for(game) or "") != "ryujinx":
        return None
    tid = game.get("title_id")
    if tid is None:
        try:
            tid = client.rom(rom_id).get("title_id") or ""
        except Exception:
            tid = ""
        if not tid:
            m = re.search(r"\[(01[0-9A-Fa-f]{14})\]", f'{game.get("launch") or ""} {game.get("path", "")}')
            tid = m[1] if m else ""
        with config.editing("installed") as games:  # remember it
            if str(rom_id) in games:
                games[str(rom_id)]["title_id"] = tid
    return systems.switch_base_title(int(tid, 16)) if tid else None


def _switch_save_ids(base, title_id):
    """Save folder ids Ryujinx gave a game, read from its save index
    (bis/system/save/8000000000000000/0/imkvdb.arc: "IMKV" header, then "IMEN" entries whose key
    starts with the game's program id and whose value starts with the save folder id)."""
    try:
        data = (base / "bis/system/save/8000000000000000/0/imkvdb.arc").read_bytes()
    except OSError:
        return []
    if data[:4] != b"IMKV" or len(data) < 12:
        return []
    count = struct.unpack_from("<I", data, 8)[0]
    pos, ids = 12, []
    for _ in range(count):
        if data[pos:pos + 4] != b"IMEN" or pos + 12 > len(data):
            break
        key_size, value_size = struct.unpack_from("<II", data, pos + 4)
        key = data[pos + 12:pos + 12 + key_size]
        value = data[pos + 12 + key_size:pos + 12 + key_size + value_size]
        pos += 12 + key_size + value_size
        if len(key) > 0x20 and len(value) >= 8:
            program_id, save_type = struct.unpack_from("<Q", key, 0)[0], key[0x20]
            if program_id == title_id and save_type in (1, 3):  # 1 = user save, 3 = device save
                ids.append(struct.unpack_from("<Q", value, 0)[0])
    return ids


def _claim_switch(entry, folders, title_id):
    """Claim the game's numbered folders in every Ryujinx save folder we watch."""
    if title_id is None:
        return
    for kind, label, root in folders:
        if root.name not in ("save", "saveMeta") or root.parent.name != "user":
            continue
        base = root.parent.parent.parent  # .../Ryujinx (from .../Ryujinx/bis/user/save)
        for save_id in _switch_save_ids(base, title_id):
            for name in (f"{save_id:016x}", f"{save_id:016X}"):
                folder = root / name
                if not folder.is_dir():
                    continue
                for path in folder.rglob("*"):
                    key = f"{label}/{path.relative_to(root).as_posix()}"
                    if path.is_file() and key not in entry["files"][kind]:
                        entry["files"][kind].append(key)
                break


def _upload(client, rom_id, entry, kind, name, data, track=True):
    """Upload one save or state file to RomM under this game and this PC's emulator.
    `track`: remember it as the latest version of that file (not for backup-/conflict- copies).
    Raises if RomM files it under another game, so a sync never reports success for a save that
    went to the wrong place."""
    saved = client.upload(f"/api/{kind}", {"rom_id": rom_id, "emulator": entry["emu"]}, UPLOAD_FIELD[kind], name, data)
    config.log.info("RomM stored %s %s as #%s on game #%s", kind, saved.get("file_name"), saved.get("id"), saved.get("rom_id"))
    if str(saved.get("rom_id")) != str(rom_id):
        raise RuntimeError(f"RomM filed {name} under game #{saved.get('rom_id')}, not #{rom_id}")
    if track:
        entry["server"][kind][saved["file_name"]] = saved["updated_at"]


# ---------- helpers ----------

@contextlib.contextmanager
def _locked():
    """sync.json, locked so the launcher and the Decky panel never sync at the same time."""
    config.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.SETTINGS_DIR / "sync.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = config.load("sync")
        try:
            yield state
        finally:
            config.save("sync", state)


def _entry(state, rom_id, emu):
    """The game's record in sync.json, created empty the first time."""
    return state.setdefault(str(rom_id), {
        "emu": emu,
        "files": {k: [] for k in KINDS},   # "label/path" keys that belong to this game
        "hashes": {},                      # sha1 of each file at the last sync
        "server": {k: {} for k in KINDS},  # RomM file name -> updated_at we last saw
    })


def _path(where, key):
    """'label/rel/path' -> real path, or None if the folder is unknown or the path escapes it."""
    label, _, rel = key.partition("/")
    root = where.get(label)
    if not root or not rel:
        return None
    target = (root / rel).resolve()
    return target if target.is_relative_to(root) else None


def _usable(path):
    """A file that can be synced: it exists, and isn't too big to be a save (MAX_FILE)."""
    return path is not None and path.is_file() and path.stat().st_size <= MAX_FILE


def _is_flat(keys, main_label):
    """All files sit directly in the emulator's main folder: upload them one by one.

    Anything else goes in a zip, which remembers the folder each file came from.
    So do names RomM would change on upload (it swaps characters like : and ?),
    so they come back with the exact name the emulator looks for."""
    if {k.split("/", 1)[0] for k in keys} != {main_label}:
        return False  # some files are in another folder
    for k in keys:
        inside = k.split("/", 1)[1]
        if "/" in inside or re.search(r'[\\:|*?"<>]', k):
            return False  # in a sub-folder, or a name RomM would change
    return True


def _zip(where, keys):
    """The files as a zip, each stored under its key (so a pull puts it back in the same folder)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k in keys:
            z.write(_path(where, k), k)
    return buf.getvalue()


def _sha1(path):
    """A file's SHA-1, read in 1 MB pieces (a Switch save folder can be large)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _timestamp(iso):
    """RomM's ISO 8601 time as unix time. (Older Pythons don't accept a trailing "Z".)"""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def emu_for(game):
    """The emulator whose saves a downloaded game uses, or None if it isn't synced (unknown platform,
    a platform whose saves can't be synced, or a game with nothing to launch)."""
    system = systems.SYSTEMS.get(game.get("system"))
    if system and system["sync"] and game.get("launch"):
        return system["emu"]
    return None


def _game_stem(game):
    """The game file's name without its extension, which emulators name saves after; None if it
    has no launch file."""
    return Path(game["launch"]).stem if game.get("launch") else None
