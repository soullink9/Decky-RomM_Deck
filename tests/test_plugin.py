"""End-to-end test of the plugin against the fake RomM, in a fake home folder."""
import asyncio, hashlib, json, os, shutil, subprocess, sys, tempfile, textwrap, time, types, zipfile, io
from pathlib import Path

SCRATCH = Path(__file__).parent  # this folder: the fake RomM and the motion client live here
sys.path.insert(0, str(SCRATCH))
import mock_romm as M

SRC = SCRATCH.parent  # the repository: copied into the fake home as if Decky had installed it
FAKE = Path(tempfile.mkdtemp(prefix="romm-deck-test-"))  # the fake home, thrown away each run
HOME = FAKE / "home/user"
PLUG = HOME / "homebrew/plugins/romm-deck"
EMU = HOME / "Games/EmuDeck/Emulation"

# --- plugin "installed" by Decky ---
shutil.copytree(SRC, PLUG, ignore=shutil.ignore_patterns(".git", "tests", "node_modules", "__pycache__", "build", "*.zip"))
(HOME / "homebrew/settings/romm-deck").mkdir(parents=True)
(HOME / "homebrew/logs/romm-deck").mkdir(parents=True)

# --- EmuDeck layout (mirrors the user's settings.sh) ---
(HOME / "emudeck").mkdir(parents=True)
(HOME / "emudeck/settings.sh").write_text(textwrap.dedent(f'''\
    emulationPath="{HOME}/Games/EmuDeck"/Emulation
    romsPath="{HOME}/Games/EmuDeck"/Emulation/roms
    biosPath="{HOME}/Games/EmuDeck"/Emulation/bios
    savesPath="{HOME}/Games/EmuDeck"/Emulation/saves
    storagePath="{HOME}/Games/EmuDeck"/Emulation/storage
'''))
def link(emu, name, target):
    target.mkdir(parents=True, exist_ok=True)
    (EMU / "saves" / emu).mkdir(parents=True, exist_ok=True)
    (EMU / "saves" / emu / name).symlink_to(target)
RA = HOME / ".var/app/org.libretro.RetroArch/config/retroarch"
DOL = HOME / ".var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu"
link("retroarch", "saves", RA / "saves"); link("retroarch", "states", RA / "states")
link("dolphin", "GC", DOL / "GC"); link("dolphin", "Wii", DOL / "Wii"); link("dolphin", "StateSaves", DOL / "StateSaves")
(DOL / "Wii/title").mkdir(parents=True); (DOL / "Wii/shared2").mkdir(parents=True)
(EMU / "saves/duckstation/saves").mkdir(parents=True); (EMU / "saves/duckstation/states").mkdir(parents=True)
link("ryujinx", "saves", HOME / ".config/Ryujinx/bis/user/save"); link("ryujinx", "system", HOME / ".config/Ryujinx/system")
RYU_FP = HOME / ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx"
(RYU_FP / "bis/user/save").mkdir(parents=True); (RYU_FP / "bis/user/saveMeta").mkdir(parents=True)

# Fake EmuDeck launchers: they "play" by writing save files, controlled by $PLAY
L = EMU / "tools/launchers"; L.mkdir(parents=True)
(L / "retroarch.sh").write_text(textwrap.dedent(f'''\
    #!/bin/bash
    echo "retroarch $@" >> "{FAKE}/calls.log"
    rom="${{@: -1}}"; base=$(basename "$rom"); base="${{base%.*}}"
    [ "$PLAY" = save ] && echo "srm-$SAVE" > "{RA}/saves/$base.srm" && echo "state-$SAVE" > "{RA}/states/$base.state1"
    if [ "$PLAY" = hold ]; then  # save, then keep playing until Steam closes the game
        echo "srm-$SAVE" > "{RA}/saves/$base.srm"; touch "{FAKE}/playing"
        sleep 30 & wait $!
    fi
    exit 0
'''))
(L / "dolphin-emu.sh").write_text(textwrap.dedent(f'''\
    #!/bin/bash
    echo "dolphin $vblank_mode $@" >> "{FAKE}/calls.log"
    mkdir -p "{DOL}/GC/USA/Card A" "{DOL}/Wii/title/00010000/475a4c45/data" "{DOL}/StateSaves"
    echo gci-$SAVE > "{DOL}/GC/USA/Card A/01-GZLE-gczelda.gci"
    echo wii-$SAVE > "{DOL}/Wii/title/00010000/475a4c45/data/banner.bin"
    echo sys > "{DOL}/Wii/shared2/sysconf"
    echo st-$SAVE > "{DOL}/StateSaves/GZLE01.s01"
'''))
(L / "ryujinx.sh").write_text(textwrap.dedent(f'''\
    #!/bin/bash
    echo "ryujinx $@" >> "{FAKE}/calls.log"
    mkdir -p "{RYU_FP}/bis/user/save/0000000000000002/0" "{RYU_FP}/bis/user/saveMeta/0000000000000002"
    echo sw-$SAVE > "{RYU_FP}/bis/user/save/0000000000000002/0/progress.dat"
    echo meta > "{RYU_FP}/bis/user/saveMeta/0000000000000002/00000001.meta"
    cp "{HOME}/.config/Ryujinx/Config.json" "{FAKE}/config-during-game.json" 2>/dev/null
    if [ -f "{FAKE}/server-active" ]; then echo yes > "{FAKE}/server-during-game"; else echo no > "{FAKE}/server-during-game"; fi
    "{sys.executable}" "{SCRATCH}/dsu_client.py" > "{FAKE}/motion-during-game.txt" 2>&1
'''))
(FAKE / "bin").mkdir(parents=True, exist_ok=True)  # a fake systemctl that just records what it was asked
(FAKE / "bin/systemctl").write_text(textwrap.dedent(f'''\
    #!/bin/bash
    echo "systemctl $@" >> "{FAKE}/systemctl.log"
    case "$2" in
      start) touch "{FAKE}/server-active" ;;
      stop) rm -f "{FAKE}/server-active" ;;
      disable) [ "$3" = --now ] && rm -f "{FAKE}/server-active" ;;
      is-active) [ -f "{FAKE}/server-active" ] && echo active || echo inactive ;;
    esac
    exit 0
'''))
(FAKE / "bin/systemctl").chmod(0o755)
os.environ["PATH"] = f"{FAKE}/bin:" + os.environ["PATH"]
# DuckStation ignores EmuDeck's folder and saves in its own; melonDS saves next to the game
(L / "duckstation.sh").write_text(textwrap.dedent(f'''\
    #!/bin/bash
    echo "duckstation $@" >> "{FAKE}/calls.log"
    mkdir -p "{HOME}/.local/share/duckstation/memcards"
    [ "$PLAY" = save ] && echo "mcd-$SAVE" > "{HOME}/.local/share/duckstation/memcards/Crash (USA)_1.mcd"
    exit 0
'''))
(L / "melonds.sh").write_text(textwrap.dedent(f'''\
    #!/bin/bash
    echo "melonds $@" >> "{FAKE}/calls.log"
    rom="$1"; [ "$PLAY" = save ] && echo "sav-$SAVE" > "${{rom%.*}}.sav"
    if [ "$PLAY" = busy ]; then  # meanwhile: another game arrives in the same folder, with its own save
        echo "sav-$SAVE" > "${{rom%.*}}.sav"
        echo rom > "$(dirname "$rom")/Another Game.nds"; echo other > "$(dirname "$rom")/Another Game.sav"
        echo sequel > "${{rom%.*}}_2.sav.bak"
    fi
    exit 0
'''))
(EMU / "saves/melonds/saves").mkdir(parents=True); (EMU / "saves/melonds/states").mkdir(parents=True)

for f in L.iterdir(): f.chmod(0o755)  # EmuDeck's launchers are executable

# A fake motion sensor (kernel IIO files), lying flat: 1 g on its z axis
IIO_DEV = FAKE / "iio/iio:device0"; IIO_DEV.mkdir(parents=True)
(IIO_DEV / "name").write_text("bmi323-imu\n")
for k, vals in (("accel", (0, 0, 16384)), ("anglvel", (0, 0, 0))):
    for axis, v in zip("xyz", vals): (IIO_DEV / f"in_{k}_{axis}_raw").write_text(f"{v}\n")
    (IIO_DEV / f"in_{k}_scale").write_text("0.000598550415\n" if k == "accel" else "0.001065264\n")
os.environ["ROMM_DECK_IIO"] = str(FAKE / "iio")
os.environ["ROMM_DECK_HIDRAW"] = str(FAKE / "no-hidraw")  # no Steam Deck-style controller here

# --- fake decky module, then load main.py the way Decky does ---
os.environ["HOME"] = str(HOME)
os.environ["DECKY_USER_HOME"] = str(HOME)
events = []
decky = types.ModuleType("decky")
import logging
logging.basicConfig(level=logging.INFO, format="   log: %(message)s")
log_records = []
class _Keep(logging.Handler):
    def emit(self, record): log_records.append(record)
logging.getLogger().addHandler(_Keep())
decky.logger = logging.getLogger("decky")
async def emit(*a): events.append(a)
decky.emit = emit
sys.modules["decky"] = decky
sys.path.insert(0, str(PLUG / "py_modules"))
sys.path.insert(0, str(PLUG))
import main
from romm_deck import config, library, metadata

srv = M.serve(8765)
URL = "http://127.0.0.1:8765"
P = main.Plugin()
run = asyncio.get_event_loop().run_until_complete if False else None

def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        global failures
        failures += 1
failures = 0

def launch(rom_id, play="none", save="1"):
    env = {**os.environ, "PLAY": play, "SAVE": save}
    r = subprocess.run([sys.executable, str(PLUG / "bin/romm_launch.py"), str(rom_id)], env=env, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
    return r.returncode

async def wait_downloads():
    while P.downloading:
        await asyncio.sleep(0.05)

async def test():
    import romm_deck
    version = json.loads((SRC / "package.json").read_text())["version"]
    check(romm_deck.__version__ == version, f"one version everywhere: backend {romm_deck.__version__}, package.json {version}")
    await P._main()
    check(config.SETTINGS_DIR == HOME / "homebrew/settings/romm-deck", f"settings dir resolved from plugin location ({config.SETTINGS_DIR})")
    r = await P.connect(URL, "WRONG-CODE"); check(not r["ok"] and "Invalid" in r["error"], f"bad pairing code rejected: {r}")
    r = await P.connect(URL, "abcd-1234"); check(r["ok"], "pairing code exchanged for token")
    check((await P.status())["connected"], "status connected")
    cols = await P.collections(); check([c["name"] for c in cols] == ["Favorites", "Recently added"], f"collections: {cols}")
    roms = await P.roms("collection", 10); check(len(roms) == 7 and not roms[0]["installed"], "collection roms listed")

    for rid in (1, 2, 3, 4, 5, 6, 7):
        await P.download(rid, "Pokemon Emerald" if rid == 1 else "")
    listed = await P.downloads()
    check(any(d["id"] == 1 and d["name"] == "Pokemon Emerald" for d in listed) and any(d["name"] == "RomM game #2" for d in listed),
          f"the home page can list what's downloading, with names: {[d['name'] for d in listed][:3]}")
    await wait_downloads()
    check(await P.downloads() == [], "…and nothing once they're done")
    done = {e[1]: e[2] for e in events if e[0] == "downloaded"}
    check(all(done[i]["ok"] for i in (1, 2, 3, 4, 5, 6, 7)), f"all downloads ok: {done}")
    check(any(e[0] == "progress" and e[2] == 100 for e in events), "progress reached 100%")
    games = config.load("installed")
    roms_dir = EMU / "roms"
    check((roms_dir / "gba/Pokemon Emerald (USA).gba").read_bytes() == M.CONTENT[1], "GBA rom in roms/gba")
    check(games["2"]["launch"].endswith("psx/Final Fantasy VII (USA)/Final Fantasy VII (USA).m3u"), f"multi-disc launches the m3u: {games['2']['launch']}")
    check(games["5"]["launch"].endswith("psx/Crash (USA)/Crash (USA).cue") and not (roms_dir / "psx/Crash (USA).zip").exists(), "zipped PSX game unpacked, launches the .cue")
    check(games["3"]["launch"].endswith("gc/Wind Waker (USA).rvz"), "GameCube rom in roms/gc")
    check(games["6"]["launch"] is None and (roms_dir / "pico8/game.p8").exists() and not done[6]["playable"], "unknown platform: downloaded to roms/<fs_slug>, no card")
    check(not list(roms_dir.rglob("*.part")), "no partial files left")

    card = await P.card(1)
    check(card["exe"] == "/usr/bin/python3" and card["options"] == f'"{PLUG}/bin/romm_launch.py" 1', f"card points at the launcher: {card}")
    check(await P.card(6) is None, "no card for download-only platform")
    check(card["collections"] == ["Nintendo Game Boy Advance"] and (await P.card(4))["collections"] == ["Nintendo Switch", "Nintendo Switch - Ryujinx"],
          "cards carry EmuDeck-style collection names")
    await P.set_app_id(1, 4000001); check((await P.game(1))["app_id"] == 4000001, "app id stored")
    cov = await P.cover(1); check(cov and cov["ext"] == "png", "cover art fetched")

    # ---- RetroArch: flat files, uploaded one by one ----
    launch(1, play="save", save="1")
    calls = (FAKE / "calls.log").read_text()
    check(f"-L {HOME}/.var/app/org.libretro.RetroArch/config/retroarch/cores/mgba_libretro.so {roms_dir}/gba/Pokemon Emerald (USA).gba" in calls, "RetroArch launched with mGBA core and the rom")
    names = sorted(a["file_name"] for k in ("saves", "states") for a in M.ASSETS[k] if a["rom_id"] == 1)
    check(names == ["Pokemon Emerald (USA).srm", "Pokemon Emerald (USA).state1"], f"srm + state uploaded as plain files: {names}")
    n = len(M.UPLOADS); launch(1, play="save", save="1"); check(len(M.UPLOADS) == n, "unchanged saves are not re-uploaded")
    launch(1, play="save", save="2"); check(len(M.UPLOADS) == n + 2, "changed saves uploaded again")

    # another device updates the save on RomM -> pulled before next launch
    srm = next(a for a in M.ASSETS["saves"] if a["rom_id"] == 1)
    srm.update(data=b"from-other-device\n", updated_at=M.tick())
    launch(1, play="none")
    check((RA / "saves/Pokemon Emerald (USA).srm").read_bytes() == b"from-other-device\n", "newer RomM save pulled before launch")
    n = len(M.UPLOADS); launch(1, play="none"); check(len(M.UPLOADS) == n, "a pulled save isn't bounced back up")

    # conflict: changed both here and on RomM; RomM copy is newer
    (RA / "saves/Pokemon Emerald (USA).srm").write_text("local-edit\n")
    os.utime(RA / "saves/Pokemon Emerald (USA).srm", (1, 1))  # local older
    srm.update(data=b"remote-edit\n", updated_at=M.tick())
    launch(1, play="none")
    conflicts = [a for a in M.ASSETS["saves"] if a["file_name"].startswith("conflict-")]
    check((RA / "saves/Pokemon Emerald (USA).srm").read_bytes() == b"remote-edit\n" and conflicts and conflicts[0]["data"] == b"local-edit\n",
          "conflict: newer RomM copy kept locally, local copy uploaded as conflict-…")
    # conflict where local is newer
    (RA / "saves/Pokemon Emerald (USA).srm").write_text("local-newer\n")
    srm.update(data=b"remote-older\n", updated_at="2020-01-01T00:00:00+00:00")
    launch(1, play="none")
    conflicts = [a["data"] for a in M.ASSETS["saves"] if a["file_name"].startswith("conflict-")]
    check((RA / "saves/Pokemon Emerald (USA).srm").read_text() == "local-newer\n" and srm["data"] == b"local-newer\n"
          and b"remote-older\n" in conflicts, "conflict: newer local copy kept and pushed; older RomM copy kept as conflict-…")
    # a save name RomM would rename (":") goes up zipped so it comes back with the exact name
    (RA / "saves/Zelda: Minish Cap.srm").write_text("x")
    from romm_deck import saves as S
    check(not S._is_flat(["saves/Zelda: Minish Cap.srm"], "saves") and S._is_flat(["saves/Pokemon Emerald (USA).srm"], "saves")
          and not S._is_flat(["rom-folder/x.sav"], "saves"), "names with : and files outside the main folder are zipped")

    # ---- Dolphin: nested folders, one zip per game ----
    launch(3, play="save", save="a")
    check("dolphin 0 -b -e" in (FAKE / "calls.log").read_text(), "Dolphin launched with vblank_mode=0 and -b -e")
    z = next(a for a in M.ASSETS["saves"] if a["rom_id"] == 3)
    with zipfile.ZipFile(io.BytesIO(z["data"])) as zf:
        members = sorted(zf.namelist())
    check(z["file_name"] == "dolphin-saves.romm.zip" and members == ["GC/USA/Card A/01-GZLE-gczelda.gci", "Wii/00010000/475a4c45/data/banner.bin"],
          f"Dolphin saves zipped, Wii system files left out: {z['file_name']} {members}")
    st = next(a for a in M.ASSETS["states"] if a["rom_id"] == 3)
    check(st["file_name"] == "StateSaves/GZLE01.s01" or st["file_name"] == "GZLE01.s01", f"Dolphin state uploaded: {st['file_name']}")

    # fresh device: saves wiped locally and no sync history -> restored from RomM
    shutil.rmtree(DOL / "GC/USA"); shutil.rmtree(DOL / "Wii/title/00010000")
    (config.SETTINGS_DIR / "sync.json").unlink()
    r = await P.sync_saves(3)
    check(r["done"] == 1 and (DOL / "GC/USA/Card A/01-GZLE-gczelda.gci").read_text() == "gci-a\n"
          and (DOL / "Wii/title/00010000/475a4c45/data/banner.bin").exists(), f"fresh device: Dolphin saves restored from the zip ({r})")

    # ---- Ryubing flatpak (not linked by EmuDeck) ----
    launch(4, play="save", save="x")
    z = next((a for a in M.ASSETS["saves"] if a["rom_id"] == 4), None)
    members = sorted(zipfile.ZipFile(io.BytesIO(z["data"])).namelist()) if z else []
    check(z and z["emulator"] == "ryujinx" and "ryubing-save/0000000000000002/0/progress.dat" in members
          and "ryubing-saveMeta/0000000000000002/00000001.meta" in members, f"Ryubing flatpak saves uploaded: {members}")

    # ---- emulator ignoring EmuDeck's folder: found in its own folder ----
    launch(5, play="save", save="p")
    z = next((a for a in M.ASSETS["saves"] if a["rom_id"] == 5), None)
    members = zipfile.ZipFile(io.BytesIO(z["data"])).namelist() if z else []
    check(members == ["duckstation-memcards/Crash (USA)_1.mcd"], f"DuckStation card found in ~/.local/share/duckstation: {members}")

    # ---- melonDS saving next to the game ----
    launch(7, play="save", save="n")
    z = next((a for a in M.ASSETS["saves"] if a["rom_id"] == 7), None)
    members = zipfile.ZipFile(io.BytesIO(z["data"])).namelist() if z else []
    check(members == ["rom-folder/Pokemon Platinum (USA).sav"], f"melonDS save next to the rom found: {members}")
    (roms_dir / "nds/Pokemon Platinum (USA).sav").unlink(); (config.SETTINGS_DIR / "sync.json").unlink()
    await P.sync_saves(7)
    check((roms_dir / "nds/Pokemon Platinum (USA).sav").read_text() == "sav-n\n", "melonDS save restored next to the rom")

    # ---- a folder this machine doesn't have: restored into the main one ----
    z["data"] = zipped = (lambda b: (zipfile.ZipFile(b, "w").writestr("some-other-pc/x.sav", "other") or b))(io.BytesIO())
    z["data"] = zipped.getvalue(); z["updated_at"] = M.tick()
    await P.sync_saves(7)
    check((EMU / "saves/melonds/saves/x.sav").read_text() == "other", "unknown folder falls back to the emulator's main save folder")

    # ---- the same folder linked twice is only watched once ----
    from romm_deck import saves as S2
    labels = [l for _, l, _ in S2.roots(config.load("installed")["3"])]
    check("dolphin-gc" not in labels and labels[:3] == ["GC", "StateSaves", "Wii"], f"Dolphin folders not doubled: {labels}")

    # ---- BIOS ----
    r = await P.bios(4)
    check(r["ok"] and (EMU / "bios/prod.keys").exists() and (RYU_FP / "system/prod.keys").exists(), "Switch keys go to bios and Ryubing's system folder")

    # ---- RomM's details for Steam game pages ----
    rich = {  # shaped like RomM 5.4.1's /api/roms/{id}
        "id": 1, "summary": "Catch Pokémon in Hoenn.", "platform_display_name": "GBA",
        "fs_name": "Pokemon Emerald (USA).gba", "fs_size_bytes": 16 * 1024 * 1024, "regions": ["USA"], "languages": ["En"],
        "tags": ["Rev 1"], "revision": "1", "alternative_names": ["Pocket Monsters Emerald"],
        "metadatum": {"genres": ["RPG", "Adventure"], "franchises": ["Pokémon"], "collections": ["Pokémon Gen III"],
                      "companies": ["Game Freak", "Nintendo"], "developers": ["Game Freak"], "publishers": ["Nintendo"],
                      "game_modes": ["Single player", "Multiplayer"], "age_ratings": ["E"], "player_count": "1-4",
                      "first_release_date": 1095724800000, "average_rating": 85.4, "rating_count": 1234},
        "igdb_metadata": {"themes": ["Fantasy"], "player_perspectives": ["Bird view / Isometric"], "keywords": ["pokemon", "monsters"]},
        "hltb_metadata": {"main_story": 120600, "main_plus_extra": 165600, "completionist": 543600},
        "merged_ra_metadata": {"achievements": [{"points": 10, "badge_id": "b1", "title": "First Badge", "description": "Win at Rustboro", "badge_url": "https://media.retroachievements.org/Badge/b1.png"},
                                                {"points": 25, "badge_id": "b2", "title": "Champion"}, {"points": 5, "badge_id": "b3"}]},
        "rom_user": {"status": "now_playing", "completion": 40, "rating": 9, "now_playing": True, "backlogged": False, "last_played": "2026-10-20T18:30:00.123456Z"},
        "ra_id": 515, "hltb_id": 77, "youtube_video_id": "a b",
        "merged_screenshots": ["/assets/romm/resources/roms/1/screenshots/0.jpg", "/assets/romm/resources/roms/1/screenshots/1.png"],
        "all_user_notes": [{"title": "Where I am", "content": "Before Sootopolis.\nNeed HM07.", "updated_at": "2026-10-01T10:00:00+00:00", "username": "me"},
                           {"title": "", "content": "x" * 1500, "created_at": "2026-09-01T10:00:00", "username": "friend"}],
        "user_saves": [{"file_name": "Pokemon Emerald (USA).srm", "emulator": "mgba", "updated_at": "2026-10-20T19:00:00Z"}],
        "user_states": [{"file_name": "Pokemon Emerald (USA).state1", "emulator": "mgba", "updated_at": "2026-10-19T19:00:00Z"}],
    }
    d = metadata.details(rich)
    facts = dict(d["facts"])
    check(d["description"] == "Catch Pokémon in Hoenn." and d["developers"] == ["Game Freak"] and d["publishers"] == ["Nintendo"]
          and d["release_date"] == 1095724800 and d["rating"] == 85 and d["features"] == [1, 2],
          f"Steam's own fields from RomM: developer, publisher, date (ms -> s), rating, feature icons: {[d[k] for k in ('developers', 'publishers', 'release_date', 'rating', 'features')]}")
    check(facts.get("Genres") == "RPG, Adventure" and facts.get("Players") == "1-4" and facts.get("Franchise") == "Pokémon"
          and facts.get("Rating") == "85/100 (1,234 ratings)" and facts.get("How long to beat") == "Main 34 h · Main + extras 46 h · Completionist 151 h"
          and facts.get("RetroAchievements") == "3 achievements, 40 points" and facts.get("File") == "Pokemon Emerald (USA).gba · 16 MB"
          and facts.get("In your RomM") == "Now playing, 40% complete, rated 9/10, now playing" and facts.get("RomM game") == "#1",
          f"every other RomM fact as a row ({len(facts)}): {list(facts)}")
    check(metadata.details({"summary": None, "igdb_metadata": {"companies": [{"name": "Retro Studios"}], "first_release_date": 1631836800, "total_rating": "8.9"}})
          | {"facts": []} == {"description": "", "developers": ["Retro Studios"], "publishers": [], "release_date": 1631836800, "rating": 89, "features": [], "facts": [],
                              "links": [], "activity": []},
          "IGDB's fields when RomM's own are missing (and a 0-10 score scaled to 100)")
    check(metadata.details({}) == {"description": "", "developers": [], "publishers": [], "release_date": None, "rating": None, "features": [], "facts": [],
                                  "links": [], "activity": []},
          "a game with no metadata: nothing, no error")
    # the Game Info buttons and the Activity list
    check(metadata.links(rich, "http://romm.lan:8080/") == [["RomM", "http://romm.lan:8080/rom/1"], ["RetroAchievements", "https://retroachievements.org/game/515"],
                                                         ["HowLongToBeat", "https://howlongtobeat.com/game/77"], ["Trailer", "https://www.youtube.com/watch?v=a%20b"]],
          f"Game Info buttons: the game in RomM, plus the sites RomM matched it to: {metadata.links(rich, 'http://romm.lan:8080/')}")
    progress = {"total": 2, "results": [
        {"rom_ra_id": 999, "earned_achievements": [{"id": "b1", "date": "2026-01-01 00:00:00"}]},  # another game's
        {"rom_ra_id": 515, "num_awarded": 2, "max_possible": 3, "highest_award_kind": "beaten-hardcore", "most_recent_awarded_date": "2026-10-10 12:00:00",
         "earned_achievements": [{"id": "b1", "date": "2026-10-02 08:00:00"}, {"id": "b2", "date": "2026-10-10 12:00:00", "date_hardcore": "2026-10-10 12:00:00"}]}]}
    acts = metadata.activity(rich, progress)
    kinds = [a["kind"] for a in acts]
    check(kinds == ["save", "played", "state", "achievement", "award", "achievement", "note", "note"],
          f"Activity, newest first: saves, states, last played, achievements, notes: {kinds}")
    first = next(a for a in acts if a["title"] == "First Badge")
    check(first["at"] == 1790928000 and first["body"] == "Win at Rustboro · 10 points" and first["image"].endswith("b1.png"),
          f"an unlock: its title, description, points and badge, at its time (UTC): {first}")
    champ = next(a for a in acts if a["title"] == "Champion")
    check(champ["body"] == "25 points · hardcore", f"hardcore unlocks say so: {champ['body']!r}")
    check(not any(a["at"] == metadata._when("2026-01-01 00:00:00") for a in acts), "another game's unlocks aren't listed")
    note = next(a for a in acts if a["title"] == "Where I am")
    long_note = next(a for a in acts if a["kind"] == "note" and a["by"] == "friend")
    check(note["body"] == "Before Sootopolis.\nNeed HM07." and note["by"] == "me" and long_note["title"] == "Note" and len(long_note["body"]) == 1201,
          "notes: title, text (long ones shortened), and who wrote them")
    check(metadata._when("2026-10-20T18:30:00.123456Z") == metadata._when("2026-10-20 18:30:00") == 1792521000 and metadata._when(1792521000000) == 1792521000
          and metadata._when("nonsense") is None and metadata._when(None) is None, "RomM's and RetroAchievements' times understood (and nonsense ignored)")
    check(metadata.activity(rich)[0]["kind"] == "save" and not any(a["kind"] == "achievement" for a in metadata.activity(rich)),
          "no RetroAchievements progress (not linked, or no permission): the rest still shows")
    M.ROMS[1].update(rich)
    events[:] = [e for e in events if e[0] != "steam_details"]
    first = await P.steam_details()
    for _ in range(100):
        if any(e[0] == "steam_details" for e in events):
            break
        await asyncio.sleep(0.05)
    sent = next((e[1] for e in events if e[0] == "steam_details"), {})
    check(first == {} and sent.get("4000001", {}).get("developers") == ["Game Freak"] and len(sent["4000001"]["facts"]) >= 15,
          "Steam page details: fetched from RomM in the background, then sent to Steam")
    shots = sent["4000001"].get("screenshots") or []
    check(shots == [f"shots/1/{hashlib.sha1(p.encode()).hexdigest()[:12]}{p[-4:]}" for p in rich["merged_screenshots"]]
          and all((config.DATA_DIR / s).read_bytes() == b"\x89PNG fake" for s in shots),
          f"RomM's screenshots copied to the folder Decky serves to Steam's pages: {shots}")
    check(sent["4000001"]["links"][0] == ["RomM", URL.rstrip("/") + "/rom/1"] and any(a["kind"] == "note" for a in sent["4000001"]["activity"]),
          "…plus the RomM link and the Activity list")

    async def next_details():
        events[:] = [e for e in events if e[0] != "steam_details"]
        for _ in range(100):
            if any(e[0] == "steam_details" for e in events):
                return next(e[1] for e in events if e[0] == "steam_details")
            await asyncio.sleep(0.05)
        return None
    M.ME["ra_progression"] = progress
    await P.page_opened(4000001)
    check(await next_details() is None, "page opened again soon: nothing asked of RomM (it caught up minutes ago)")
    kept = config.load("steam-details"); kept["1"]["at"] -= 20 * 60; config.save("steam-details", kept)
    await P.page_opened(4000001)
    got = await next_details()
    check(got and [a["title"] for a in got["4000001"]["activity"] if a["kind"] == "achievement"] == ["Champion", "First Badge"],
          "page opened 20 minutes later: catches up, with your RetroAchievements unlocks (from RomM's /users/me)")
    await P.page_opened(123456)
    check(await next_details() is None, "another app's page: nothing")
    M.ROMS[1]["user_saves"] = [{"file_name": "Pokemon Emerald (USA).srm", "emulator": "mgba", "updated_at": "2026-10-25T09:00:00Z"}]
    await P.game_closed(4000001)
    got = await next_details()
    check(got and any(a["kind"] == "save" and a["at"] == metadata._when("2026-10-25T09:00:00Z") for a in got["4000001"]["activity"]), "a game closed: its page catches up (the save it just pushed)")
    from romm_deck import saves as S4
    S4._mark(1, False, "Couldn't reach RomM")
    top = (await P.steam_details())["4000001"]["activity"][0]
    check(top["kind"] == "sync-failed" and top["body"] == "Couldn't reach RomM", f"the last save sync on this PC is in Activity too: {top}")
    S4._mark(1, True)
    M.ME["ra_progression"] = None
    kept = config.load("steam-details")
    check("1" in kept and (await P.steam_details())["4000001"]["rating"] == 85, "…kept on the PC, so they're there straight away next time")
    events[:] = []
    kept["1"]["at"] -= 8 * 86400; config.save("steam-details", kept)
    await P.steam_details()
    for _ in range(100):
        if any(e[0] == "steam_details" for e in events):
            break
        await asyncio.sleep(0.05)
    check(config.load("steam-details")["1"]["at"] > time.time() - 60, "…and refreshed from RomM once they're a week old")
    with_cards = {str(g["app_id"]) for g in library.installed().values() if g.get("app_id")}
    check(set(await P.steam_details()) <= with_cards, "only games with a Steam card")
    check((await P.options())["steam_pages"] is True, "on by default")
    await P.set_option("steam_pages", False); check((await P.options())["steam_pages"] is False, "the off switch is remembered")
    await P.set_option("steam_pages", True)
    g1 = await P.game(1)
    check(g1["about"] == {"developers": ["Game Freak"], "release_date": 1095724800} and "description" not in g1["about"],
          "the plugin's own game page: just developer and year, no description")

    # ---- the panel's look: covers, counts, save status ----
    listed = {r["id"]: r for r in await P.roms("collection", 10)}
    t = await P.thumb(1, listed[1]["cover"])
    url = t["data"]
    covers = config.SETTINGS_DIR / "covers"
    check(url.startswith("data:image/png;base64,") and len(list(covers.glob("1-*"))) == 1, f"a game's cover for the panel, saved on the PC: {url[:40]}…")
    check(t["url"] == URL + listed[1]["cover"], f"…plus RomM's own address for it, in case Steam won't show the saved copy: {t['url']}")
    good = config.load("settings"); config.save("settings", {**good, "url": "http://127.0.0.1:9"})
    check((await P.thumb(1, listed[1]["cover"]))["data"] == url and (await P.thumb(1, ""))["data"] == url,
          "…shown again without asking RomM (also from the On this PC list, which has no cover path)")
    t3 = await P.thumb(3, listed[3]["cover"])
    check(t3["data"] == "" and t3["url"].endswith(listed[3]["cover"]), f"RomM unreachable and no saved cover: no error, RomM's address to try: {t3}")
    check(await P.thumb(3, "") == {"data": "", "url": ""}, "…and with no path known either: nothing (the placeholder shows)")
    check(any("No cover for rom 3" in r.getMessage() for r in log_records), "a cover that couldn't be fetched is logged, with the reason")
    config.save("settings", good)
    M.ROMS[1]["path_cover_large"] = "/assets/romm/resources/roms/1/cover/big.png?ts=2"  # changed in RomM
    url2 = (await P.thumb(1, M.ROMS[1]["path_cover_large"]))["data"]
    check(url2.startswith("data:image/") and len(list(covers.glob("1-*"))) == 1, "a cover changed in RomM replaces the saved one")
    M.ROMS[6]["path_cover_large"] = None
    check(await P.thumb(6, "") == {"data": "", "url": ""}, "a game with no cover in RomM: none")
    s_ = await P.summary()
    check(s_["on_pc"] == len(library.installed()) and s_["platforms"] >= 1 and "collections" in s_, f"home page counts: {s_}")
    g1 = await P.game(1)
    check(g1["syncs"] and g1["saves"] and g1["saves"]["ok"] and time.time() - g1["saves"]["at"] < 600, f"game page: when its saves last synced ({g1['saves']})")
    g6 = await P.game(6)
    check(not g6["syncs"] and g6["saves"] is None, "a game whose saves aren't synced has no save status line")

    # ---- sync all + remove ----
    r = await P.sync_saves(); check(not r["failed"], f"sync all: {r}")
    installed = await P.installed(); check([g["id"] for g in installed] == [5, 2, 1, 7, 6, 3, 4], f"installed list: {[g['name'] for g in installed]}")

    config.save("settings", {"url": "http://127.0.0.1:9", "token": "rmm_x"})
    before = (FAKE / "calls.log").read_text().count("dolphin")
    rc = launch(3, play="save", save="b")
    check(rc == 0 and (FAKE / "calls.log").read_text().count("dolphin") == before + 1, "RomM unreachable: game still launches")
    log = (HOME / "homebrew/logs/romm-deck/launch.log").read_text()
    check("Can't reach RomM" in log, "launcher logs the failed sync to launch.log")
    st3 = config.load("sync-status").get("3", {})
    check(st3.get("ok") is False and "reach" in st3.get("error", "").lower(), f"…and the game page will say the last sync failed: {st3}")
    # ---- games put on the PC before the plugin ----
    await P.connect(URL, M.TOKEN)
    (roms_dir / "gba/Metroid Fusion (USA).gba").write_bytes(b"x")
    (roms_dir / "psx/Spyro (USA).chd").write_bytes(b"x")  # converted from .cue
    plats = await P.platforms()
    check([p["name"] for p in plats] == ["GBA", "NDS", "NGC", "PICO", "PSX", "SWITCH"], f"platforms listed: {[p['name'] for p in plats]}")
    gba = await P.roms("platform", 1)
    check({r["name"]: r["installed"] for r in gba} == {"Pokemon Emerald": True, "Metroid Fusion": True, "Not On PC": False},
          f"browsing a platform marks games already on the PC: {gba}")
    hits = await P.roms("search", "spyro")
    check(len(hits) == 1 and hits[0]["installed"], f"search works and finds the converted .chd copy: {hits}")
    g = await P.game(51)
    check(g["installed"] and g["playable"] and not g["app_id"], "existing game can get a RomM Deck card")
    check(config.load("installed")["51"]["launch"].endswith("psx/Spyro (USA).chd"), "existing game launches its own file")
    games = config.load("installed"); del games["50"], games["51"]; config.save("installed", games)
    r = await P.scan()
    check(r["found"] == 2, f"scan finds games already on the PC: {r}")

    # ---- opening the panel on a Steam card ----
    check(await P.match_app(4000001, "", "") == 1, "RomM Deck card matched by app id (1)")
    await P.set_app_id(3, 4000003)
    check(await P.match_app(4000003, "/usr/bin/python3", '"x/romm_launch.py" 3') == 3, "RomM Deck card matched by app id")
    ww = config.load("installed")["3"]["launch"]
    check(await P.match_app(5000001, f'"{L}/dolphin-emu.sh"', f'-b -e "{ww}"') == 3, "Steam ROM Manager card matched by its game file")
    (roms_dir / "gba/Metroid Fusion (USA).gba").exists() or (roms_dir / "gba/Metroid Fusion (USA).gba").write_bytes(b"x")
    games = config.load("installed"); games.pop("50", None); config.save("installed", games)
    mf = roms_dir / "gba/Metroid Fusion (USA).gba"
    check(await P.match_app(5000002, '"/x/retroarch.sh"', f'-L /cores/mgba_libretro.so "{mf}"') == 50 and "50" in config.load("installed"),
          "unknown SRM card: found in RomM by searching its file name, and added")
    check(await P.match_app(5000003, '"/usr/bin/steam"', "") is None, "a normal Steam game doesn't match")

    # ---- saves of a game started from an SRM card (not our launcher) ----
    (RA / "saves/Metroid Fusion (USA).srm").write_text("srm-mf")
    (RA / "states/Metroid Fusion (USA).state.auto").write_text("st-mf")
    (RA / "saves/Metroid Fusion (USA) (Rev 1).srm").write_text("other game")
    r = await P.sync_saves(50)
    up = sorted(a["file_name"] for k in ("saves", "states") for a in M.ASSETS[k] if a["rom_id"] == 50)
    check(up == ["Metroid Fusion (USA).srm", "Metroid Fusion (USA).state.auto"], f"saves found by game file name: {up}")

    # ---- Use RomM's saves ----
    srm = next(a for a in M.ASSETS["saves"] if a["rom_id"] == 50)
    srm.update(data=b"romm-good", updated_at="2020-01-01T00:00:00+00:00")  # older than local
    (RA / "saves/Metroid Fusion (USA).srm").write_text("local-bad")
    r = await P.game_saves(50, "pull")
    backups = [a for a in M.ASSETS["saves"] if a["rom_id"] == 50 and a["file_name"].startswith("backup-")]
    check(r["ok"] and (RA / "saves/Metroid Fusion (USA).srm").read_bytes() == b"romm-good"
          and backups and backups[0]["data"] == b"local-bad", "Use RomM's saves: RomM copy wins, PC copy backed up")
    n = len(M.UPLOADS); await P.game_saves(50, "pull")
    check(len(M.UPLOADS) == n, "Use RomM's saves again: nothing to back up when they already match")
    r = await P.sync_saves(50)
    check(srm["data"] == b"romm-good" and not any(a["file_name"].startswith("backup-") for a in []), "normal sync afterwards doesn't re-upload")

    # ---- Push ----
    (RA / "saves/Metroid Fusion (USA).srm").write_text("pc-version")
    srm.update(data=b"romm-newer", updated_at=M.tick())  # RomM has something newer; push anyway
    r = await P.game_saves(50, "push")
    backups = [a["data"] for a in M.ASSETS["saves"] if a["rom_id"] == 50 and a["file_name"].startswith("backup-")]
    check(r["ok"] and srm["data"] == b"pc-version\n"[:-1] + b"" or srm["data"] == b"pc-version", f"Push: PC copy replaces RomM's ({srm['data']}, {r})")
    check(b"romm-newer" in backups, "Push: RomM's old copy kept as backup-…")
    n = len(M.UPLOADS); r = await P.game_saves(50, "push")
    check(len(M.UPLOADS) == n + 2 and r["up"] == 2, f"Push again re-uploads (no backup when identical): {r}")
    r = await P.game_saves(50, "sync"); check(r["ok"] and r["down"] == 0 and r["up"] == 0, f"Sync after push: nothing to do {r}")
    r = await P.game_saves(6, "push"); check(not r["ok"], "no save buttons for download-only platforms")

    # ---- auto-load states ----
    racfg = RA / "retroarch.cfg"; racfg.write_text('video_driver = "vulkan"\nsavestate_auto_load = "true"\nsavestate_auto_save = "true"\n')
    (RA / "config/mGBA").mkdir(parents=True); (RA / "config/mGBA/mGBA.cfg").write_text('savestate_auto_load = "true"\n')
    (RA / "config/Snes9x").mkdir(parents=True); (RA / "config/Snes9x/Snes9x.cfg").write_text('video_smooth = "true"\n')
    pp = HOME / ".var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP/SYSTEM"; pp.mkdir(parents=True)
    (pp / "ppsspp.ini").write_bytes("\ufeff[General]\nFirstRun = False\nAutoLoadSaveState = 2\n\n[CPU]\nFast = True\n".encode())
    ds = HOME / ".local/share/duckstation"; ds.mkdir(parents=True, exist_ok=True)
    (ds / "settings.ini").write_text("[Main]\nSettingsVersion = 3\n\n[Display]\nVSync = false\n")
    px = HOME / ".config/PCSX2/inis"; px.mkdir(parents=True); (px / "PCSX2.ini").write_text("[UI]\nTheme = dark\n\n[EmuCore]\nSaveStateOnShutdown = true\n")
    (HOME / "emudeck/settings.sh").write_text((HOME / "emudeck/settings.sh").read_text() + "RAautoSave=true\n")
    st = await P.autoload_status()
    check(st == ["RetroArch", "PPSSPP", "DuckStation", "PCSX2", "RetroArch (mGBA)"], f"status lists emulators with auto-load on: {st}")
    ch = await P.autoload_off()
    check(set(ch) == {"RetroArch", "PPSSPP", "DuckStation", "PCSX2", "RetroArch (mGBA)"}, f"turned off: {ch}")
    check(racfg.read_text() == 'video_driver = "vulkan"\nsavestate_auto_load = "false"\nsavestate_auto_save = "true"\n', "RetroArch: only auto-load changed")
    check((RA / "config/mGBA/mGBA.cfg").read_text() == 'savestate_auto_load = "false"\n', "RetroArch core override fixed too")
    check((RA / "config/Snes9x/Snes9x.cfg").read_text() == 'video_smooth = "true"\n', "core configs without the setting untouched")
    ppt = (pp / "ppsspp.ini").read_bytes()
    check(ppt.startswith(b"\xef\xbb\xbf") and b"AutoLoadSaveState = 0\n" in ppt and b"[CPU]\nFast = True" in ppt, "PPSSPP set to 0, BOM kept")
    check((ds / "settings.ini").read_text() == "[Main]\nSettingsVersion = 3\nSaveStateOnExit = false\n\n[Display]\nVSync = false\n", "DuckStation key added in [Main]")
    check((px / "PCSX2.ini").read_text() == "[UI]\nTheme = dark\n\n[EmuCore]\nSaveStateOnShutdown = false\n", "PCSX2 switched off")
    from romm_deck import ini as INI0
    t = HOME / "t.ini"; t.write_text("[UI]\nTheme = dark\n"); INI0.set_value(t, "EmuCore", "X", "1")
    check(t.read_text() == "[UI]\nTheme = dark\n\n[EmuCore]\nX = 1\n", "missing section gets added")
    INI0.set_value(t, "EmuCore", "X", None)
    check(t.read_text() == "[UI]\nTheme = dark\n", "…and removing its only key takes the added section away again: the file as it was")
    cfg = HOME / "t.cfg"; cfg.write_text('a = "1"\n'); INI0.set_value(cfg, None, "b", '"2"')
    check(cfg.read_text() == 'a = "1"\nb = "2"\n' and INI0.get_value(cfg, None, "b") == '"2"', "a file without sections (RetroArch's .cfg): key added at the end")
    check("RAautoSave=false" in (HOME / "emudeck/settings.sh").read_text(), "EmuDeck told not to turn RetroArch's back on")
    check(await P.autoload_status() == [] and await P.autoload_off() == [], "everything off; running again changes nothing")

    # ---- saves from RomM's web player (EmulatorJS: emulator "mgba", time-tagged names) ----
    def web(kind, rid, emu, name, data):
        M.NEXT_ID[0] += 1
        M.ASSETS[kind].append(dict(id=M.NEXT_ID[0], rom_id=rid, emulator=emu, file_name=name, updated_at=M.tick(), data=data))
    web("saves", 1, "mgba", "Pokemon Emerald (USA) [2026-10-25_14-00-00].srm", b"web-srm")
    web("states", 1, "mgba", "Pokemon Emerald (USA) [2026-10-25 14-00-00-000].state", b"web-state")
    r = await P.game_saves(1, "pull")
    check(r["ok"] and r["down"] == 3 and (RA / "saves/Pokemon Emerald (USA).srm").read_bytes() == b"web-srm"
          and (RA / "states/Pokemon Emerald (USA).state").read_bytes() == b"web-state", f"Pull uses RomM web player saves for RetroArch games: {r}")
    r = await P.game_saves(1, "sync"); check(r["down"] == 0, f"…and doesn't pull them again: {r}")
    web("saves", 3, "some-other-app", "GZLE.raw", b"x")
    for a in M.ASSETS["saves"] + M.ASSETS["states"]:  # pretend this PC never uploaded Wind Waker's
        if a["rom_id"] == 3 and a["emulator"] == "dolphin": a["emulator"] = "elsewhere"
    r = await P.game_saves(3, "pull")
    check(r["ok"] and r["down"] == 0 and r["other"] == ["elsewhere", "some-other-app"], f"unusable saves are reported: {r}")
    for a in M.ASSETS["saves"] + M.ASSETS["states"]:
        if a["rom_id"] == 3 and a["emulator"] == "elsewhere": a["emulator"] = "dolphin"

    # ---- Switch: save folder found from Ryujinx's save index, without a session ----
    import struct
    def imen(program, save_type, save_id):
        key = struct.pack("<Q", program) + b"\0" * 24 + bytes([save_type]) + b"\0" * 31
        value = struct.pack("<Q", save_id) + b"\0" * 56
        return b"IMEN" + struct.pack("<II", len(key), len(value)) + key + value
    idx = RYU_FP / "bis/system/save/8000000000000000/0"; idx.mkdir(parents=True, exist_ok=True)
    entries = [imen(0x0100F4700B2E0000, 1, 0x13), imen(0x01007EF00011E000, 1, 0x14), imen(0x0100F4700B2E0000, 0, 0x15)]
    (idx / "imkvdb.arc").write_bytes(b"IMKV" + struct.pack("<II", 0, len(entries)) + b"".join(entries))
    for sid, text in (("0000000000000013", "totk-progress"), ("0000000000000014", "other-game"), ("0000000000000015", "system")):
        (RYU_FP / f"bis/user/save/{sid}/0").mkdir(parents=True, exist_ok=True)
        (RYU_FP / f"bis/user/save/{sid}/0/progress.dat").write_text(text)
    (RYU_FP / "bis/user/saveMeta/0000000000000013").mkdir(parents=True, exist_ok=True)
    (RYU_FP / "bis/user/saveMeta/0000000000000013/00000001.meta").write_text("meta")
    sync = config.load("sync"); sync.pop("4", None); config.save("sync", sync)  # as if never played via RomM Deck
    games = config.load("installed"); games["4"].pop("title_id", None); config.save("installed", games)
    r = await P.game_saves(4, "push")
    z = [a for a in M.ASSETS["saves"] if a["rom_id"] == 4 and a["file_name"] == "ryujinx-saves.romm.zip"][-1]
    members = sorted(zipfile.ZipFile(io.BytesIO(z["data"])).namelist())
    check(r["ok"] and members == ["ryubing-save/0000000000000013/0/progress.dat", "ryubing-saveMeta/0000000000000013/00000001.meta"],
          f"Switch push finds the game's folder from Ryujinx's index (not others'): {members}")
    check(config.load("installed")["4"]["title_id"] == "0100F4700B2E0000", "title id fetched from RomM and remembered")

    # ---- taking over an EmuDeck / Steam ROM Manager card ----
    ww = config.load("installed")["3"]
    srm_exe, srm_opts = f'"{L}/dolphin-emu.sh"', f'vblank_mode=0 %command% -b -e "{ww["launch"]}"'
    games = config.load("installed"); games["3"]["app_id"] = None; config.save("installed", games)
    cmd = await P.take_over(3, 6000003, srm_exe, srm_opts, f'"{L}"')
    check(cmd["exe"] == "/usr/bin/python3" and cmd["options"].endswith('romm_launch.py" 3'), f"take over returns RomM Deck's command: {cmd}")
    check(config.load("installed")["3"]["original"]["options"] == srm_opts and await P.taken_over() == [{"rom_id": 3, "app_id": 6000003}], "original command kept")
    await P.take_over(3, 6000003, "/usr/bin/python3", cmd["options"], "")  # applying it twice
    check(config.load("installed")["3"]["original"]["exe"] == srm_exe, "taking over twice doesn't lose the original")
    check(await P.match_app(6000099, '"/usr/bin/python3"', cmd["options"]) == 3, "a RomM Deck card is recognised by its command")
    (FAKE / "calls.log").write_text("")
    launch(3, play="save", save="takeover")
    calls = (FAKE / "calls.log").read_text()
    check(calls.strip() == f'dolphin 0 -b -e {ww["launch"]}', f"taken-over card runs its original command, env and all: {calls!r}")
    z = next(a for a in M.ASSETS["saves"] if a["rom_id"] == 3 and a["file_name"] == "dolphin-saves.romm.zip")
    check(b"gci-takeover" in zipfile.ZipFile(io.BytesIO(z["data"])).read("GC/USA/Card A/01-GZLE-gczelda.gci"), "…and its saves were pushed after playing")

    # ---- Remove from this PC ----
    r = await P.uninstall(2)
    check(r["ok"] and not (roms_dir / "psx/Final Fantasy VII (USA)").exists() and "2" not in config.load("installed"),
          f"remove: game folder deleted ({r})")

    srm_path = RA / "saves/Pokemon Emerald (USA).srm"
    srm_path.write_text("unsynced progress!")  # played since the last sync
    M.FAIL_UPLOADS[0] = True
    r = await P.uninstall(1)
    M.FAIL_UPLOADS[0] = False
    check(not r["ok"] and srm_path.read_text() == "unsynced progress!" and (roms_dir / "gba/Pokemon Emerald (USA).gba").exists()
          and "1" in config.load("installed"), f"upload fails: nothing deleted ({r.get('error')})")

    from romm_deck import saves as S3
    with S3._locked() as st:  # a file on RomM that differs (e.g. the last upload was cut off)
        pass
    r = await P.uninstall(1)
    on_romm = next(a for a in M.ASSETS["saves"] if a["rom_id"] == 1 and a["file_name"] == "Pokemon Emerald (USA).srm")
    check(r["ok"] and r["app_id"] == 4000001 and on_romm["data"] == b"unsynced progress!"
          and not srm_path.exists() and not (RA / "states/Pokemon Emerald (USA).state1").exists()
          and not (roms_dir / "gba/Pokemon Emerald (USA).gba").exists() and "1" not in config.load("sync"),
          f"remove: final push, then saves, states, game and sync history deleted ({r})")
    check(not (config.DATA_DIR / "shots/1").exists(), "…and its Steam page's screenshot copies")

    # shared memory card used by another game stays
    shared = HOME / ".local/share/duckstation/memcards/shared_card_1.mcd"; shared.write_text("all PS1 games")
    sync = config.load("sync"); sync["5"]["files"]["saves"].append("duckstation-memcards/shared_card_1.mcd"); config.save("sync", sync)
    r = await P.uninstall(5)
    check(r["ok"] and shared.exists() and r["kept"] == ["shared_card_1.mcd"]
          and not (HOME / ".local/share/duckstation/memcards/Crash (USA)_1.mcd").exists(), f"shared memory card kept: {r}")
    check(any(a["file_name"] == "duckstation-saves.romm.zip" and a["rom_id"] == 5 for a in M.ASSETS["saves"]), "…and its saves are on RomM")

    # RomM unreachable: nothing deleted
    good = config.load("settings"); config.save("settings", {"url": "http://127.0.0.1:9", "token": "rmm_x"})
    r = await P.uninstall(3)
    config.save("settings", good)
    check(not r["ok"] and "3" in config.load("installed") and (DOL / "GC/USA/Card A/01-GZLE-gczelda.gci").exists(), f"RomM offline: nothing deleted ({r['error'][:40]})")
    # the Wii save folder left empty is tidied, GC/Wii roots kept
    r = await P.uninstall(3)
    check(r["ok"] and r["app_id"] == 6000003 and not (DOL / "Wii/title/00010000").exists() and (DOL / "Wii/title").exists() and (DOL / "GC").exists(),
          f"Dolphin: emptied save folders removed, emulator folders kept ({r['deleted']})")
    check(await P.match_app(4000001, "", "") is None, "removed game's card no longer matches")
    # ---- a game's RomM entry deleted (duplicate with a broken file); the right one has another id ----
    await P.set_app_id(4, 7000004)
    M.ROMS[60] = {**M.ROMS[4], "id": 60}; M.CONTENT[60] = M.CONTENT[4]; del M.ROMS[4]
    g = await P.game(4)
    check(g.get("id") == 60 and g["installed"] and g["app_id"] == 7000004, f"opening the game relinks it to the RomM entry with the same file: {g}")
    inst = config.load("installed")
    check("4" not in inst and inst["60"]["app_id"] == 7000004 and config.load("moved") == {"4": "60"}, "card, settings and id moved over")
    check(await P.match_app(7000004, "", "") == 60 and await P.match_app(1, "/usr/bin/python3", '"x/romm_launch.py" 4') == 60,
          "the Steam card (still saying 4) now opens the new entry")
    launch(4, play="save", save="relinked")
    z = [a for a in M.ASSETS["saves"] if a["rom_id"] == 60 and a["file_name"] == "ryujinx-saves.romm.zip"]
    check(z and "ryubing-save/0000000000000013/0/progress.dat" in zipfile.ZipFile(io.BytesIO(z[-1]["data"])).namelist(),
          "launching the old card pushes every save to the new entry (nothing skipped as 'already synced')")

    # found by a scan instead; and one with no replacement
    M.ROMS[61] = {**M.ROMS[7], "id": 61}; del M.ROMS[7]
    del M.ROMS[6]
    r = await P.scan()
    check(r["relinked"] == ["Pokemon Platinum"] and r["lost"] == ["Some Pico Game"] and "61" in config.load("installed"),
          f"scan relinks moved games and reports ones RomM no longer has: {r}")
    g = await P.game(6)
    check("error" in g and "no longer has" in g["error"], f"a game RomM lost says so plainly: {g}")

    # ---- Switch games RomM keeps as base + update + DLC files ----
    def sw(id, name, base, upd, dlc):
        files = [dict(file_name=base, category="game"), dict(file_name=upd, category="update"), dict(file_name=dlc, category="dlc")]
        r = {**M.rom(id, name, "switch", "switch", name, "", multi=True), "files": files, "title_id": None}
        M.ROMS[id] = r
        M.CONTENT[id] = M.zipped({base: b"base", upd: b"update", dlc: b"dlc", f"{name}.m3u": "\n".join([base, upd, dlc]).encode()})
    sw(70, "Super Mario Odyssey", "Super Mario Odyssey [0100000000010000][v0].nsp",
       "Super Mario Odyssey [0100000000010800][v262144].nsp", "Super Mario Odyssey (DLC) [0100000000011001].nsp")
    sw(71, "Kirby", "Kirby [01004D300C5AE000][v0].nsp", "Kirby [01004D300C5AE800][v65536].nsp", "Kirby (Expansion) [01004D300C5AF001].nsp")
    sdir = roms_dir / "switch"
    (sdir / "Super Mario Odyssey [0100000000010000][v0].nsp").write_bytes(b"base")      # as EmuDeck users keep them:
    (sdir / "Super Mario Odyssey [0100000000010800][v262144].nsp").write_bytes(b"upd")  # loose files side by side
    games = config.load("installed"); games.pop("70", None); config.save("installed", games)
    upd = sdir / "Super Mario Odyssey [0100000000010800][v262144].nsp"
    rid = await P.match_app(8000070, f'"{L}/ryujinx.sh"', f'--fullscreen "{upd}"')
    g = config.load("installed").get("70", {})
    check(rid == 70 and g.get("launch", "").endswith("[0100000000010000][v0].nsp"),
          f"a card pointing at the update file is matched to the game, which launches the base file ({rid}, {g.get('launch')})")
    plat = {r["name"]: r["installed"] for r in await P.roms("platform", 4)}
    check(plat.get("Super Mario Odyssey") is True and plat.get("Kirby") is False, f"platform list knows it's on the PC: {plat}")
    # saves found via the base title id taken from the file name
    entries = [imen(0x0100000000010000, 1, 0x30)]
    (idx / "imkvdb.arc").write_bytes(b"IMKV" + struct.pack("<II", 0, 1) + b"".join(entries))
    (RYU_FP / "bis/user/save/0000000000000030/0").mkdir(parents=True); (RYU_FP / "bis/user/save/0000000000000030/0/game.bin").write_text("odyssey")
    r = await P.game_saves(70, "push")
    z = [a for a in M.ASSETS["saves"] if a["rom_id"] == 70]
    check(r["ok"] and z and "ryubing-save/0000000000000030/0/game.bin" in zipfile.ZipFile(io.BytesIO(z[-1]["data"])).namelist(),
          f"Switch saves found from the file name's title id ({r})")
    await P.download(71); await wait_downloads()
    g = config.load("installed")["71"]
    check(g["launch"].endswith("Kirby/Kirby [01004D300C5AE000][v0].nsp"), f"downloaded multi-file game launches the base game, not DLC: {g['launch']}")

    # ---- named differently on the PC than in RomM ----
    M.ROMS[80] = {**M.rom(80, "Pokémon Scarlet", "switch", "switch", "Pokemon Scarlet (USA).xci", "xci"), "title_id": "0100A3D008C5C000"}
    M.ROMS[81] = {**M.rom(81, "The Legend of Zelda: Echoes of Wisdom", "switch", "switch", "zelda-eow.nsp", "nsp"), "title_id": None}
    M.ROMS[82] = {**M.rom(82, "Mario Kart 8", "switch", "switch", "MK8.nsp", "nsp"), "title_id": None}
    (sdir / "Pokemon Violet-Scarlet whatever [0100A3D008C5C800][v65536].nsp").write_bytes(b"x")  # only the title id matches
    (sdir / "Legend of Zelda - Echoes of Wisdom, The [01008CF01BAAC000][v0].nsp").write_bytes(b"x")
    (sdir / "Mario Kart 8 (USA).nsp").write_bytes(b"x"); (sdir / "Mario Kart 8 (EUR).nsp").write_bytes(b"x")  # two fit: don't guess
    M.ROMS[83] = {**M.rom(83, "Metroid Dread", "switch", "switch", "dread.xci", "xci"), "title_id": "010093801237C000"}
    (sdir / "MD [010093801237C000][v0].nsp").write_bytes(b"x"); (sdir / "MD [010093801237C800][v3].nsp").write_bytes(b"x")
    plat = {r["name"]: r["installed"] for r in await P.roms("platform", 4)}
    check(config.load("installed")["83"]["launch"].endswith("MD [010093801237C000][v0].nsp"), "with base + update tagged, the base file is picked")
    check(plat["Pokémon Scarlet"] and plat["The Legend of Zelda: Echoes of Wisdom"] and not plat["Mario Kart 8"],
          f"loose matches by title id and simplified name, never a guess between two: {plat}")

    # ======== deletion safety ========
    removed_log = HOME / "homebrew/logs/romm-deck/removed.log"
    nds = roms_dir / "nds"
    M.ROMS[91] = M.rom(91, "Safety DS", "nds", "nds", "Safety DS.nds", "nds"); M.CONTENT[91] = b"SAFE"
    await P.download(91); await wait_downloads()
    launch(91, play="busy", save="s1")
    files = config.load("sync")["91"]["files"]["saves"]
    check(files == ["rom-folder/Safety DS.sav"], f"a session only claims the game's own save, not another game's ROM or save: {files}")
    r = await P.uninstall(91)
    check(r["ok"] and not (nds / "Safety DS.nds").exists() and not (nds / "Safety DS.sav").exists()
          and (nds / "Another Game.nds").exists() and (nds / "Another Game.sav").exists() and (nds / "Safety DS_2.sav.bak").exists(),
          f"removing it deletes only its ROM and its save; the other game's files stay ({r})")
    log = removed_log.read_text()
    check("Safety DS.nds" in log and "Safety DS.sav" in log and "Another Game" not in log, "every deleted file is in removed.log")

    # the same file claimed by two RomM entries (a duplicate in RomM)
    gba = roms_dir / "gba"; (gba / "Dup Game.gba").write_bytes(b"x")
    M.ROMS[92] = M.rom(92, "Dup Game", "gba", "gba", "Dup Game.gba", "gba")
    M.ROMS[93] = M.rom(93, "Dup Game", "gba", "gba", "Dup Game.gba", "gba")
    listed = {r["id"]: r["installed"] for r in await P.roms("platform", 1) if r["name"] == "Dup Game"}
    check(sorted(listed.values()) == [False, True], f"a file is linked to only one of two duplicate RomM entries: {listed}")
    owner = [k for k, v in listed.items() if v][0]; other = [k for k, v in listed.items() if not v][0]
    games = config.load("installed"); games[str(other)] = {**games[str(owner)]}; config.save("installed", games)  # (a hand-edited or damaged installed.json)
    r = await P.uninstall(other)
    check(not r["ok"] and "also holds" in r["error"] and (gba / "Dup Game.gba").exists(), f"…and if both claim it, Remove refuses: {r.get('error')}")
    games = config.load("installed"); del games[str(other)]; config.save("installed", games)

    # a game recorded as a whole platform folder (should never happen; must still be harmless)
    games = config.load("installed"); games["94"] = {**games[str(owner)], "name": "Broken", "path": str(gba), "launch": str(gba / "Dup Game.gba")}
    config.save("installed", games)
    M.ROMS[94] = M.rom(94, "Broken", "gba", "gba", "gba", "")
    r = await P.uninstall(94)
    check(not r["ok"] and "platform folder" in r["error"] and (gba / "Dup Game.gba").exists() and (gba / "Metroid Fusion (USA).gba").exists(),
          f"a platform folder is never deleted: {r.get('error')}")
    check(await P.match_app(9999, '"/x/retroarch.sh"', f'-L c.so "{gba / "Metroid Fusion (USA).gba"}"') != 94,
          "a card inside that folder isn't mistaken for it")
    games = config.load("installed"); del games["94"]; config.save("installed", games)

    from romm_deck import saves as S4
    check(not S4._named_after("Sonic_2.srm", {"path": "/r/Sonic.gba", "launch": "/r/Sonic.gba"})
          and S4._named_after("Sonic.srm", {"path": "/r/Sonic.gba", "launch": "/r/Sonic.gba"})
          and S4._named_after("Sonic_1.mcd", {"path": "/r/Sonic.cue", "launch": "/r/Sonic.cue"}), "'Sonic' doesn't claim 'Sonic_2.srm'")

    # linking: a game kept in a sub-folder
    (sdir / "Sub Folder").mkdir(); (sdir / "Sub Folder" / "Bayonetta 3.nsp").write_bytes(b"x")
    M.ROMS[95] = {**M.rom(95, "Bayonetta 3", "switch", "switch", "Bayonetta 3.nsp", "nsp"), "title_id": None}
    plat = {r["name"]: r["installed"] for r in await P.roms("platform", 4)}
    check(plat["Bayonetta 3"], "a game in a sub-folder of roms/switch is found")

    # ======== Switch updates & DLC in their own folder ========
    extras = HOME / "Games/SwitchExtras"
    (RYU_FP / "Config.json").write_text(json.dumps({"autoload_dirs": [str(extras)], "game_dirs": []}))
    o = await P.options()
    check(o == {"steam_pages": True, "switch_extras_dir": str(extras), "switch_extras_dir_from_ryujinx": True}, f"folder found in Ryujinx's settings: {o}")
    def sw2(id, name, files):  # files: [(file name, category, bytes)]
        fl = []
        for i, (fname, cat, data) in enumerate(files):
            fid = id * 100 + i; M.FILES[fid] = data
            fl.append(dict(id=fid, file_name=fname, category=cat, file_size_bytes=len(data)))
        M.ROMS[id] = {**M.rom(id, name, "switch", "switch", name, "", multi=True), "files": fl, "title_id": None}
    sw2(100, "Splatoon 3", [("Splatoon 3 [0100C2500FC20000][v0].nsp", "game", b"B" * 3000),
                            ("Splatoon 3 [0100C2500FC20800][v9].nsp", "update", b"U" * 2000),
                            ("Splatoon 3 Expansion [0100C2500FC21001].nsp", "dlc", b"D" * 1000)])
    events.clear(); M.FILE_REQUESTS.clear()
    await P.download(100); await wait_downloads()
    g = config.load("installed")["100"]
    check((sdir / "Splatoon 3 [0100C2500FC20000][v0].nsp").read_bytes() == b"B" * 3000 and not (sdir / "Splatoon 3").exists()
          and g["launch"].endswith("Splatoon 3 [0100C2500FC20000][v0].nsp"), "base game goes straight into roms/switch")
    check(sorted(p.name for p in extras.iterdir()) == ["Splatoon 3 Expansion [0100C2500FC21001].nsp", "Splatoon 3 [0100C2500FC20800][v9].nsp"]
          and len(g["extras"]) == 2, "update and DLC go into the Ryujinx folder")
    pcts = [e[2] for e in events if e[0] == "progress"]
    check(pcts == sorted(pcts) and pcts[-1] == 100 and any(40 < p < 60 for p in pcts), f"one progress bar across all three files: {pcts[:3]}…{pcts[-3:]}")
    done = [e for e in events if e[0] == "downloaded"][-1][2]
    check(done["ok"] and done["extras"] == 2, f"download reports the extras: {done}")
    gp = await P.game(100)
    check(gp["extras"] == 2 and gp["extras_on_pc"] == 2 and gp["extras_dir"] == str(extras), f"game page knows: {gp}")
    # a game already on the PC: just its updates & DLC
    sw2(101, "Pikmin 4", [("Pikmin 4 [0100B7C00933A000][v0].nsp", "game", b"P"), ("Pikmin 4 [0100B7C00933A800][v2].nsp", "update", b"UU")])
    (sdir / "Pikmin 4 [0100B7C00933A000][v0].nsp").write_bytes(b"P")
    await P.game(101)  # links it
    M.FILE_REQUESTS.clear()
    await P.download_extras(101); await wait_downloads()
    check(M.FILE_REQUESTS == ["Pikmin 4 [0100B7C00933A800][v2].nsp"] and (extras / "Pikmin 4 [0100B7C00933A800][v2].nsp").exists(),
          "Download updates & DLC fetches only those, for a game already here")
    M.FILE_REQUESTS.clear(); await P.download_extras(101); await wait_downloads()
    check(M.FILE_REQUESTS == [], "…and skips ones already there")
    # Remove cleans up only its own updates & DLC
    (extras / "Someone else's update.nsp").write_bytes(b"x")
    r = await P.uninstall(100)
    left = sorted(p.name for p in extras.iterdir())
    check(r["ok"] and left == ["Pikmin 4 [0100B7C00933A800][v2].nsp", "Someone else's update.nsp"]
          and not (sdir / "Splatoon 3 [0100C2500FC20000][v0].nsp").exists(), f"Remove deletes its own update & DLC only: {left}")
    check("update/DLC of Splatoon 3" in removed_log.read_text(), "…and logs them")
    # the setting: change it, and it survives re-pairing
    await P.set_option("switch_extras_dir", str(HOME / "Mine"))
    await P.connect(URL, M.TOKEN)
    o = await P.options()
    check(o == {"steam_pages": True, "switch_extras_dir": str(HOME / "Mine"), "switch_extras_dir_from_ryujinx": False}, f"your own folder wins, and survives re-pairing: {o}")

    # ======== a game RomM keeps in its own folder (one file inside, entry named after the folder) ========
    M.ROMS[110] = {**M.rom(110, "Astral Chain", "switch", "switch", "Astral Chain", ""), "title_id": None,
                   "files": [dict(id=11000, file_name="Astral Chain [01007300020FA000][v0].nsp", category="game", file_size_bytes=4)]}
    M.CONTENT[110] = b"NSP!"
    await P.download(110); await wait_downloads()
    g = config.load("installed")["110"]
    check(g["launch"].endswith("roms/switch/Astral Chain [01007300020FA000][v0].nsp") and not (sdir / "Astral Chain").exists(),
          f"downloaded under its real file name, with the extension: {g['launch']}")

    # ======== device controller preset (Switch on a ROG Ally) ========
    from romm_deck import presets as PR, motion as MO, ini as INI
    async def popups():
        await asyncio.sleep(0.8)  # the backend passes them on every half second
        got = [(e[1], e[2]) for e in events if e[0] == "notify"]
        events[:] = [e for e in events if e[0] != "notify"]
        return got
    dmi = FAKE / "dmi"; dmi.mkdir()
    (dmi / "sys_vendor").write_text("ASUSTeK COMPUTER INC.\n"); (dmi / "product_name").write_text("ROG Xbox Ally X RC73XA\n")
    PR.DMI = dmi
    mine = {"motion_backend": "GamepadDriver", "sensitivity": 100, "gyro_deadzone": 1, "enable_motion": True}
    p2 = {"player_index": "Player2", "motion": {"motion_backend": "GamepadDriver"}, "id": "p2"}
    ryu_cfg = HOME / ".config/Ryujinx/Config.json"; ryu_cfg.parent.mkdir(parents=True, exist_ok=True)
    original = {"game_dirs": ["x"], "input_config": [{"player_index": "Player1", "motion": dict(mine), "id": "ally"}, p2,
                                                      {"player_index": "Handheld", "motion": dict(mine), "id": "ally"}]}
    ryu_cfg.write_text(json.dumps(original))
    g = await P.game(70)
    check(g["preset"] and g["preset"]["label"] == "Ally motion (gyro & tilt) for Switch" and g["preset"]["on"] is False
          and g["preset"]["calibrated"] is False, f"the Ally preset shows on a Switch game page, off, not calibrated: {g['preset']}")
    check((await P.game(3))["preset"] is None, "no preset on platforms that don't have one (GameCube)")
    launch(70)
    check(json.loads(ryu_cfg.read_text()) == original, "preset off: Ryujinx settings untouched")

    r = await P.set_preset("switch", True)
    check(r["ok"] and (await P.game(70))["preset"]["on"], "turning it on: nothing to download or install")

    # not calibrated yet: the game starts normally, settings untouched, and you're told why
    await popups()
    launch(70)
    got = await popups()
    check(json.loads(ryu_cfg.read_text()) == original and ("Controller preset not applied", "Not calibrated yet: press Calibrate motion on the game's page") in got,
          f"not calibrated: nothing changed, and a popup says what to do: {[x for x in got if 'ontroller' in x[0]]}")

    # calibration from the game page: steps go to the panel, the result is kept
    real_cal = MO.calibrate
    def fake_cal(progress, **kw):
        progress("Lay it flat on a table, screen up, and let go"); progress("Calibrated")
        config.save(MO.CALIBRATION, {"sensor": "bmi323-imu", "rows": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]})
    MO.calibrate = fake_cal
    events[:] = []
    r = await P.calibrate_motion(); await asyncio.sleep(0.05)
    steps = [e[1] for e in events if e[0] == "calibration"]
    check(r["ok"] and steps[0].startswith("Lay it flat") and (await P.game(70))["preset"]["calibrated"], f"calibrate: steps shown, then calibrated ({steps})")
    def bad_cal(progress, **kw): raise MO.SensorError("Didn't see it being stood up. Try again")
    MO.calibrate = bad_cal
    r = await P.calibrate_motion()
    check(not r["ok"] and "stood up" in r["error"] and MO.calibrated(), "a failed calibration says why and keeps the previous one")
    MO.calibrate = real_cal

    # playing: Ryujinx reads motion from the plugin's own server, which reads the sensor
    launch(70)
    motion_seen = (FAKE / "motion-during-game.txt").read_text().split()
    check(len(motion_seen) == 6 and [round(float(v), 2) for v in motion_seen[:3]] == [0.0, -1.0, 0.0],
          f"during the game Ryujinx gets the sensor's motion from 127.0.0.1:26760 (lying flat: 1 g down): {motion_seen}")
    during = json.loads((FAKE / "config-during-game.json").read_text())["input_config"]
    check(during[0]["motion"] == PR.DSU_MOTION and during[2]["motion"] == PR.DSU_MOTION and during[1] == p2,
          "while playing: player 1 and handheld read motion from the plugin; player 2 untouched")
    check(json.loads(ryu_cfg.read_text()) == original and config.load("controller-backup") == {}, "after the game: your settings are back exactly")
    time.sleep(0.3)
    check(not [p for p in Path("/proc").iterdir() if p.name.isdigit() and b"romm_motion.py" in (p / "cmdline").read_bytes()],
          "the motion server is gone after the game")
    st = (await P.game(70))["preset"]
    check(st["last"] == "Last game: reading the Ally's motion", f"the game page shows how the last game went: {st['last']}")

    # a crash mid-game leaves the preset applied: the next launch of anything puts it back first
    PR.apply(config.load("installed")["70"])
    check(json.loads(ryu_cfg.read_text())["input_config"][0]["motion"] == PR.DSU_MOTION, "(simulated crash: preset still applied)")
    await P.set_preset("switch", False)
    check(json.loads(ryu_cfg.read_text()) == original and config.load("controller-backup") == {}, "turning it off puts your settings back right away")
    launch(70)
    check(json.loads(ryu_cfg.read_text()) == original, "and the next launch leaves them alone")
    # a change you make in Ryujinx during the game is kept
    await P.set_preset("switch", True)
    PR.apply(config.load("installed")["70"])
    cfg = json.loads(ryu_cfg.read_text()); cfg["input_config"][0]["motion"]["sensitivity"] = 150; ryu_cfg.write_text(json.dumps(cfg))
    PR.restore()
    after = json.loads(ryu_cfg.read_text())["input_config"]
    check(after[0]["motion"]["sensitivity"] == 150 and after[2]["motion"] == mine, "a motion change you made in Ryujinx meanwhile is kept")
    ryu_cfg.write_text(json.dumps(original))

    # EmuDeck's own motion server running (not ours): paused for the game (it would hold the port), then back
    (FAKE / "server-active").write_text("")
    launch(70)
    check((FAKE / "server-during-game").read_text().strip() == "no" and (FAKE / "server-active").exists()
          and len((FAKE / "motion-during-game.txt").read_text().split()) == 6,
          "a motion server you had running is paused during the game and started again after")
    (FAKE / "server-active").unlink()
    # something else holding the port: the game still starts, settings untouched, you're told
    blocker = __import__("socket").socket(2, 2); blocker.bind(("127.0.0.1", 26760))
    await popups(); launch(70)
    got = await popups(); blocker.close()
    check(json.loads(ryu_cfg.read_text()) == original and any(t == "Controller preset not applied" and "port" in b for t, b in got),
          f"port taken by something else: not applied, and you're told: {[x for x in got if 'ontroller' in x[0]]}")
    # the sensor can't be read (e.g. a future InputPlumber streams from it): same, with the reason
    (IIO_DEV / "in_accel_x_raw").write_text("busy\n")
    await popups(); launch(70)
    got = await popups(); (IIO_DEV / "in_accel_x_raw").write_text("0\n")
    check(json.loads(ryu_cfg.read_text()) == original and any(t == "Controller preset not applied" and "motion sensor" in b for t, b in got),
          f"sensor unreadable: not applied, and you're told: {[x for x in got if 'ontroller' in x[0]]}")
    # ======== PS3 folder games (e.g. homebrew), started by EmuDeck's card via the EBOOT.BIN inside ========
    ps3 = roms_dir / "ps3"
    def ps3_game(folder):
        usr = ps3 / folder / "PS3_GAME/USRDIR"; usr.mkdir(parents=True)
        (usr / "EBOOT.BIN").write_bytes(b"SCE"); (ps3 / folder / "PS3_GAME/PARAM.SFO").write_bytes(b"PSF")
        return usr / "EBOOT.BIN"
    def ps3_rom(id, name, folder):
        files = [{"id": id * 10 + i, "file_name": n, "file_path": f"ps3/{folder}/{p}", "file_size_bytes": 3, "category": None}
                 for i, (p, n) in enumerate([("PS3_GAME/USRDIR", "EBOOT.BIN"), ("PS3_GAME", "PARAM.SFO")])]
        M.ROMS[id] = {**M.rom(id, name, "ps3", "ps3", folder, "", multi=True), "files": files}
    eboot = ps3_game("Homebrew Thing"); ps3_rom(130, "Homebrew Thing", "Homebrew Thing")
    card = (f'"{L}/rpcs3.sh"', f'--no-gui "{eboot}"')
    rid = await P.match_app(6000130, *card)
    g = config.load("installed").get("130", {})
    check(rid == 130 and g.get("path") == str(ps3 / "Homebrew Thing") and g.get("launch") == str(eboot),
          f"EmuDeck's PS3 card (starts the EBOOT.BIN deep inside the folder) is matched to the game: {rid}, {g.get('launch')}")
    check(await P.match_app(6000130, *card) == 130, "…and found straight away next time")
    # named a bit differently on the PC (tags, ".ps3" folder): still found, when only one folder fits
    ps3_game("Another Homebrew (v1.2) [Homebrew].ps3"); ps3_rom(131, "Another Homebrew", "Another Homebrew")
    found = await asyncio.to_thread(library.find_existing, [M.ROMS[131]])
    g = config.load("installed").get("131", {})
    check(131 in found and g.get("path", "").endswith("Another Homebrew (v1.2) [Homebrew].ps3") and g.get("launch", "").endswith("EBOOT.BIN"),
          f"a PS3 game folder named differently on the PC is found and launches its EBOOT.BIN: {g.get('path')}")
    ps3_game("Another Homebrew (Copy)")
    library._listings.clear()
    games = config.load("installed"); games.pop("131"); config.save("installed", games)
    found = await asyncio.to_thread(library.find_existing, [M.ROMS[131]])
    check(131 not in found, "…but with two folders that could both be it, it doesn't guess")

    # ======== Wii U (Cemu) and 3DS (Azahar): the same motion, EmuDeck's configs ========
    def dsu_reading():
        r = subprocess.run([sys.executable, str(SCRATCH / "dsu_client.py")], capture_output=True, text=True)
        return r.stdout.split()
    cemu = HOME / ".config/Cemu/controllerProfiles/controller0.xml"; cemu.parent.mkdir(parents=True)
    emudeck_cemu = (SCRATCH / "fixtures/cemu-controller0.xml").read_bytes(); cemu.write_bytes(emudeck_cemu)
    wiiu = {"system": "wiiu", "name": "Splatoon"}
    check(P._preset_info("wiiu")["label"] == "Ally motion (gyro) for Wii U" and P._preset_info("wiiu")["motion"], "Wii U preset offered on the Ally")
    await P.set_preset("wiiu", True)
    ok, text = PR.apply(wiiu, os.getpid())
    reading = dsu_reading()
    check(ok and cemu.read_bytes() == emudeck_cemu and len(reading) == 6, f"Wii U, EmuDeck's Cemu profile already reads 127.0.0.1:26760: unchanged, motion served ({text}, {reading})")
    PR.restore()
    check(cemu.read_bytes() == emudeck_cemu and dsu_reading()[0] == "no-motion", "…and after the game: still unchanged, motion server stopped")
    own = emudeck_cemu.replace(b"<api>DSUController</api>", b"<api>SDLController</api>", 1)  # someone's own profile, no motion
    cemu.write_bytes(own)
    PR.apply(wiiu, os.getpid())
    during = cemu.read_text()
    check(PR._cemu_has_dsu(cemu) and "RomM Deck motion" in during and __import__("xml.etree.ElementTree").etree.ElementTree.fromstring(during) is not None,
          "a Cemu profile without motion gets a motion source for the game (still valid XML)")
    PR.restore()
    check(cemu.read_bytes() == own, "…removed after, the file exactly as it was")
    await P.set_preset("wiiu", False)

    azahar = HOME / ".config/azahar-emu/qt-config.ini"; azahar.parent.mkdir(parents=True)
    emudeck_azahar = (SCRATCH / "fixtures/azahar-qt-config.ini").read_bytes(); azahar.write_bytes(emudeck_azahar)
    n3ds = {"system": "3ds", "name": "Ocarina 3D"}
    await P.set_preset("3ds", True)
    ok, text = PR.apply(n3ds, os.getpid())
    check(ok and azahar.read_bytes() == emudeck_azahar and len(dsu_reading()) == 6, f"3DS, EmuDeck's Azahar config already reads 127.0.0.1:26760: unchanged, motion served ({text})")
    PR.restore()
    mouse = emudeck_azahar.replace(b"profiles\\1\\motion_device=engine:cemuhookudp", b"profiles\\1\\motion_device=engine:motion_emu,update_period:100")
    mouse = mouse.replace(b"profiles\\1\\motion_device\\default=false", b"profiles\\1\\motion_device\\default=true")
    check(mouse != emudeck_azahar, "(test setup: Azahar profile 1 set to mouse motion)")
    azahar.write_bytes(mouse)
    PR.apply(n3ds, os.getpid())
    lines = azahar.read_text().splitlines()
    check("profiles\\1\\motion_device=engine:cemuhookudp" in lines and "profiles\\1\\motion_device\\default=false" in lines
          and "profiles\\2\\motion_device=engine:cemuhookudp" in lines, "an Azahar profile using mouse motion reads the Ally's motion during the game (Qt's 'default' flag cleared too)")
    PR.restore()
    check(azahar.read_bytes() == mouse, "…and goes back exactly after")
    await P.set_preset("3ds", False)

    # ======== Wii (Dolphin): real Wii Remotes, on any device ========
    dol = HOME / ".var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu"; dol.mkdir(parents=True)
    wm, core = dol / "WiimoteNew.ini", dol / "Dolphin.ini"
    emudeck_wm, emudeck_core = (SCRATCH / "fixtures/dolphin-WiimoteNew.ini").read_bytes(), (SCRATCH / "fixtures/dolphin-Dolphin.ini").read_bytes()
    wm.write_bytes(emudeck_wm); core.write_bytes(emudeck_core)
    wii = {"system": "wii", "name": "Mario Kart Wii"}
    info = P._preset_info("wii")
    check(info and info["label"] == "Use my real Wii Remotes" and info["motion"] is False, f"Wii preset offered: {info and info['label']}")
    await P.set_preset("wii", True)
    calibration = config.load(MO.CALIBRATION); config.save(MO.CALIBRATION, {})  # (doesn't need motion calibrated)
    # raw HID devices: a fake /sys/class/hidraw and /dev, with a gamepad on USB and a Wii Remote on Bluetooth
    hidraw, dev = FAKE / "hidraw", FAKE / "dev"; dev.mkdir()
    PR.HIDRAW, PR.DEV = hidraw, dev
    def hid_device(name, hid_id, openable=True):
        (hidraw / name / "device").mkdir(parents=True)
        (hidraw / name / "device/uevent").write_text(f"DRIVER=hid-generic\nHID_ID={hid_id}\nHID_NAME=test\n")
        if openable:
            (dev / name).write_text("")
    hid_device("hidraw0", "0003:0000045E:0000028E")  # a USB gamepad
    hid_device("hidraw1", "0005:0000057E:00000306")  # a Wii Remote paired over Bluetooth: Dolphin finds those itself
    real = ["-C", "Wiimote.Wiimote1.Source=2", "-C", "Wiimote.Wiimote2.Source=2", "-C", "Wiimote.Wiimote3.Source=2",
            "-C", "Wiimote.Wiimote4.Source=2", "-C", "Dolphin.Core.WiimoteContinuousScanning=True"]
    ok, text = PR.apply(wii, os.getpid())
    check(ok and PR.launch_args(wii) == real and dsu_reading()[0] == "no-motion",
          f"during a Wii game: Dolphin is told on its command line to use four real Wii Remotes and keep looking for them, no motion server ({text})")
    check(wm.read_bytes() == emudeck_wm and core.read_bytes() == emudeck_core,
          "…and Dolphin's settings files aren't touched")
    # EmuDeck's launcher (its controller AutoMap) sets every remote back to emulated in WiimoteNew.ini right
    # before Dolphin starts, which is what undid this preset when it changed that file. -C ranks above the file.
    INI.set_value(wm, "Wiimote1", "Source", "1")
    check(PR.launch_args(wii) == real, "EmuDeck setting the remotes to emulated in WiimoteNew.ini doesn't change what Dolphin is told")
    wm.write_bytes(emudeck_wm)
    check("DolphinBar has to be in mode 4" in text and "mode 4" in config.load(PR.STATUS)["wii"],
          f"no Wii Remote sensor on USB: the popup and the game page say a DolphinBar needs mode 4 ({text})")
    PR.restore()
    hid_device("hidraw2", "0003:0000057e:00000306")  # a DolphinBar in mode 4 (ids in either case)
    hid_device("hidraw3", "0003:0000057E:00000330")
    ok, text = PR.apply(wii, os.getpid())
    check(ok and "on the USB sensor" in text, f"a DolphinBar in mode 4 that Dolphin can open: said so ({text})")
    PR.restore()
    hid_device("hidraw4", "0003:0000057E:00000306", openable=False)  # a slot Dolphin isn't allowed to open
    ok, text = PR.apply(wii, os.getpid())
    check(ok and "isn't allowed to open the Wii Remote sensor" in text and PR.launch_args(wii) == real,
          f"a sensor Dolphin can't open: the preset still applies, and says why remotes on it won't connect ({text})")
    shutil.rmtree(hidraw); PR.HIDRAW = hidraw  # no raw HID devices at all
    ok, text = PR.apply(wii, os.getpid())
    check(ok and "mode 4" in text, f"no raw HID devices at all: no error ({text})")
    PR.restore()
    check(wm.read_bytes() == emudeck_wm and core.read_bytes() == emudeck_core and config.load("controller-backup") == {},
          "after the game: nothing to put back, both Dolphin files exactly as they were")

    # the arguments reach Dolphin through EmuDeck's launcher, before the game's own
    wii_game = {"system": "wii", "name": "Mario Kart Wii", "launch": str(HOME / "Emulation/roms/wii/Mario Kart Wii.rvz")}
    cmd, env, cwd = library.launch_command(wii_game, real)
    check(cmd == ["bash", str(L / "dolphin-emu.sh"), *real, "-b", "-e", wii_game["launch"]], f"RomM Deck card: {cmd}")
    (FAKE / "calls.log").write_text("")
    subprocess.run(cmd, env=env)
    check((FAKE / "calls.log").read_text().strip() == f"dolphin 0 {' '.join(real)} -b -e {wii_game['launch']}",
          f"…and EmuDeck's launcher passes them on: {(FAKE / 'calls.log').read_text()!r}")
    taken = {**wii_game, "original": {"exe": f'"{L}/dolphin-emu.sh"', "options": f'vblank_mode=0 %command% -b -e "{wii_game["launch"]}"', "start_dir": f'"{L}"'}}
    cmd, env, cwd = library.launch_command(taken, real)
    check(cmd[2] == f'vblank_mode=0 "{L}/dolphin-emu.sh" {" ".join(real)} -b -e "{wii_game["launch"]}"',
          f"taken-over EmuDeck card: the arguments go right after its launcher: {cmd[2]}")
    other = {**wii_game, "original": {"exe": '"/usr/bin/es-de"', "options": "", "start_dir": ""}}
    check(library.launch_command(other, real)[0][2] == '"/usr/bin/es-de" ', "a card running something else is left as it is")
    check(library.launch_command(wii_game)[0] == ["bash", str(L / "dolphin-emu.sh"), "-b", "-e", wii_game["launch"]],
          "preset off: Dolphin started as before")
    # a backup left by an earlier version, which changed WiimoteNew.ini, is still put back
    INI.set_value(wm, "Wiimote1", "Source", "2")
    config.save("controller-backup", {"_changes": [{"kind": "ini", "path": str(wm), "key": ["Wiimote1", "Source"], "before": None, "ours": "2"}]})
    PR.apply(wii, os.getpid()); PR.restore()
    check(wm.read_bytes() == emudeck_wm, "an earlier version's change to WiimoteNew.ini is put back at the next launch")
    PR.apply(wii, os.getpid())
    await P.set_preset("wii", False)
    check(wm.read_bytes() == emudeck_wm and PR.launch_args(wii) == [], "turned off: nothing added to Dolphin's command")
    config.save(MO.CALIBRATION, calibration)
    (dmi / "sys_vendor").write_text("Valve\n"); (dmi / "product_name").write_text("Jupiter\n")
    check(P._preset_info("wii") and P._preset_info("wiiu") is None and P._preset_info("3ds") is None,
          "on another device: the Wii preset is still offered, the Ally motion ones aren't")
    (dmi / "sys_vendor").write_text("ASUSTeK COMPUTER INC.\n"); (dmi / "product_name").write_text("ROG Xbox Ally X RC73XA\n")

    await P.set_preset("switch", False)
    # other devices
    (dmi / "sys_vendor").write_text("Valve\n"); (dmi / "product_name").write_text("Jupiter\n")
    check((await P.game(70))["preset"] is None, "no Ally preset on other devices")

    # ---- closing a game with Steam's "Exit game" (it signals the game's whole process tree) ----
    import signal
    from romm_deck import session as SES
    if "1" not in config.load("installed"):  # (removed by an earlier test)
        await P.download(1); await wait_downloads()
    def start_game(save):
        (FAKE / "playing").unlink(missing_ok=True)
        env = {**os.environ, "PLAY": "hold", "SAVE": save}
        proc = subprocess.Popen([sys.executable, str(PLUG / "bin/romm_launch.py"), "1"], env=env, start_new_session=True)
        for _ in range(200):
            if (FAKE / "playing").exists() and SES.pending():
                break
            time.sleep(0.05)
        return proc
    srm = RA / "saves/Pokemon Emerald (USA).srm"

    async def popups():
        await asyncio.sleep(0.8)  # the backend passes them on every half second
        got = [(e[1], e[2]) for e in events if e[0] == "notify"]
        events[:] = [e for e in events if e[0] != "notify"]
        return got
    await popups()
    n = len(M.UPLOADS); proc = start_game("exit1")
    check(SES.finish() == 0 and SES.pending(), "while the game runs, nothing finishes it early")
    os.killpg(proc.pid, signal.SIGTERM)  # Steam: "Exit game"
    rc = proc.wait(timeout=30)
    check(len(M.UPLOADS) > n and not SES.pending(), f"Exit game: the emulator closes, the launcher still pushes the save ({len(M.UPLOADS) - n} up)")
    check(srm.read_text().strip() == "srm-exit1" and any(u[3].endswith(".srm") for u in M.UPLOADS[n:]),
          "…and it's the save from this session")
    got = await popups()
    check([t for t, _ in got] == ["Saves synced", "Saves synced"] and "Pokemon Emerald" in got[0][1]
          and "pushed 1 save file to RomM" in got[1][1], f"popups when the game starts and after it closes: {got}")

    n = len(M.UPLOADS); proc = start_game("exit2")
    os.killpg(proc.pid, signal.SIGKILL)  # Steam gives up waiting and kills everything, launcher included
    proc.wait(timeout=30)
    check(len(M.UPLOADS) == n and SES.pending(), "(launcher killed before it could push: the session is still waiting)")
    await P.game_closed(4000001)  # the panel hears from Steam that the game stopped
    check(len(M.UPLOADS) > n and not SES.pending(), "the plugin pushes the save when Steam reports the game stopped")
    got = await popups()
    check(len(got) == 2 and "pushed 1 save file" in got[1][1], f"…with the same popup: {got}")

    n = len(M.UPLOADS); proc = start_game("exit3")
    os.killpg(proc.pid, signal.SIGKILL); proc.wait(timeout=30)
    await P._main()  # power-off / Decky restart: the plugin finishes it when it starts
    for _ in range(100):
        if not SES.pending():
            break
        await asyncio.sleep(0.05)
    check(len(M.UPLOADS) > n and not SES.pending(), "a game left unfinished (crash, power-off) is finished when the plugin starts")
    await popups()
    n = len(M.UPLOADS); launch(1, play="none")
    check(len(M.UPLOADS) == n and not SES.pending(), "a normal launch after that: nothing re-uploaded, nothing left over")
    got = await popups()
    check(got == [("Saves synced", "Pokemon Emerald: already up to date with RomM"),
                  ("Saves synced", "Pokemon Emerald: RomM already has your latest saves")], f"nothing to sync still says so: {got}")
    # RomM down: the popups say so
    real_url = config.load("settings")["url"]; st = config.load("settings"); st["url"] = "http://127.0.0.1:9"; config.save("settings", st)
    launch(1, play="save", save="offline")
    got = await popups()
    check([t for t, _ in got] == ["Saves not synced", "Saves not pushed"] and "safe on this PC" in got[1][1], f"RomM unreachable: {got}")
    st["url"] = real_url; config.save("settings", st)
    # the controller preset says when it goes on and off
    (dmi / "sys_vendor").write_text("ASUSTeK COMPUTER INC.\n"); (dmi / "product_name").write_text("ROG Ally X RC72LA\n")
    await P.set_preset("switch", True)
    launch(70)
    got = await popups()
    titles = [t for t, _ in got]
    check("Controller preset on" in titles and "Controller preset off" in titles
          and titles.index("Controller preset on") < titles.index("Controller preset off")
          and any(t == "Controller preset on" and b.endswith("reading the Ally's motion") for t, b in got),
          f"controller preset popups at start and stop: {got}")
    await P.set_preset("switch", False)
    launch(70)
    got = await popups()
    check(not any(t.startswith("Controller") for t, _ in got), f"preset off: no controller popups: {got}")
    # popups left from while the plugin wasn't running aren't shown later
    config.notify("Old", "x"); old = sorted((config.SETTINGS_DIR / "notify").glob("*.json"))[-1]
    os.utime(old, (1, 1))
    check(await popups() == [] and not old.exists(), "stale popups are dropped, not shown late")
    # a game that's running can't be removed (single or several at once)
    playing = subprocess.Popen(["sleep", "30"])
    SES.start("1", config.load("installed")["1"], {}, [playing.pid])
    r = await P.uninstall(1)
    check(not r["ok"] and "running" in r["error"] and "1" in config.load("installed"), f"removing a game while it runs is refused: {r.get('error')}")
    playing.kill(); playing.wait()
    check(SES.finish() == 1, "(game closed)")
    await popups()
    # after a reboot, a different program may have the old launcher's process number: not "still running"
    other = subprocess.Popen(["sleep", "30"])
    g1 = config.load("installed")["1"]
    SES.start("1", g1, SES_before := {}, [other.pid])
    check(SES.finish() == 0, "(the game's process is still running: wait)")
    s1 = config.load("session-1"); s1["pids"][0][1] -= 1; config.save("session-1", s1)  # same number, different process
    check(SES.finish() == 1 and not SES.pending(), "a reused process number after a reboot doesn't block the session forever")
    other.kill(); other.wait(); await popups()

    await P.disconnect(); check(not (await P.status())["connected"], "disconnect")
    e = await P.collections(); check("error" in e, f"calls without connection return an error: {e}")

asyncio.run(test())
print(f"\n{failures} failures")
if failures:
    print(f"(the fake home is kept for a look: {FAKE})")
else:
    shutil.rmtree(FAKE, ignore_errors=True)
sys.exit(1 if failures else 0)
