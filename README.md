# RomM Deck

> **Disclosure:** written with the help of Claude (Anthropic). Personal project; use at your own risk and back up your saves.
>
> **Beta (0.5.0).** Tested on a ROG Xbox Ally X with Bazzite, EmuDeck and RomM 5.4.1.

A Decky Loader plugin for a Bazzite/SteamOS machine running EmuDeck:

- Browse RomM by **platform**, **collection** (regular and smart) or **search** from the Quick Access menu
- Games already in `Emulation/roms` are recognised (same file name, or same name in another format like `.chd`). Games RomM keeps as several files (a Switch game with its update and DLC) are recognised from the base game file, and launch it rather than an update or DLC file. Files named differently from RomM are matched by the Switch title ID in the name, or by the game's name with tags, punctuation and "The" ignored, only when exactly one file fits
- **Relinks games whose RomM entry was deleted** (say, a duplicate): opening the game, or "Find games already on this PC", moves it to the RomM entry with the same file, with its Steam card and save tracking. Old ids are forwarded in `moved.json`, so existing cards keep working
- **Download** a game into the right `Emulation/roms/<system>` folder; it gets a **Steam card** with RomM's cover art, in the same platform collection Steam ROM Manager uses (e.g. "Nintendo Game Boy Advance"; names in `COLLECTIONS` in `systems.py`)
- **Switch updates & DLC** go to their own folder (the one Ryujinx auto-loads them from; found in Ryujinx's settings, or set it on the home page), not `roms/switch`. RomM labels each file of a game as game, update or DLC. Games already on the PC get a "Download updates & DLC" button. Remove deletes only the update/DLC files it downloaded
- **Remove from this PC**: syncs saves and states, checks RomM holds an identical copy of every one, then deletes the game, its saves and its Steam card. If any save isn't on RomM (or RomM can't be reached), nothing is deleted. Memory cards shared with other games (PS2 `Mcd001.ps2`, DuckStation `shared_card_1.mcd`, Dolphin `MemoryCardA.raw`) are never deleted. It also refuses to delete a platform folder, anything outside `Emulation/roms`, or a file/folder that holds another game, and every file it deletes is listed in `~/homebrew/logs/romm-deck/removed.log`
- **Works with your existing EmuDeck cards**: "Sync saves on all my Steam cards" (or one card at a time from its Steam page) makes each card start through RomM Deck, which runs the card's original command, so saves are pulled before and pushed after you play. Names, artwork and playtime stay. If Steam ROM Manager later puts its own command back, the plugin takes the card back when it loads
- **Opens on the game you're on**: open the menu while playing, or on a game's Steam page, and the panel jumps to that game (works for Steam ROM Manager cards too)
- **Saves and save states sync** with RomM: pulled before a game starts, pushed after it closes, plus **Sync** (newest wins), **Push to RomM** and **Pull from RomM** buttons on each game; Push and Pull keep the replaced copy on RomM as `backup-<time>-<name>`
- **Turn off auto-load states** in every emulator that has it (RetroArch and its core overrides, PPSSPP, Flycast, DuckStation, PCSX2) — see `autoload.py`
- **Popups in Game Mode** when a game starts and closes: saves synced (or why not), and the controller preset going on and off
- **RomM details on Steam game pages** (Game Mode, on by default; switch on the plugin's home page): for games with a RomM Deck card, Steam's own info section shows RomM's description, developer, publisher, release date, rating and feature icons (single player, multiplayer...), plus a details block with everything else RomM knows: genres, themes, game modes, players, perspective, franchise, series, age rating, How Long To Beat, RetroAchievements, other names, keywords, regions, languages, revision, tags, platform, file, your RomM status. Steam only shows that section for games it believes are Steam games, so while that game's own page is open Steam is told it isn't a shortcut; its launch and id lookups always get the truth, so Play works. The same approach as the MetaDeck and Decky Metadata plugins (don't run them on the same games). Nothing is written to Steam's files. See `src/steampage.tsx`. Also on those pages:
  - **Screenshots**: RomM's screenshots of the game (up to 10), after any you took with Steam. Copies are kept in `~/homebrew/data/romm-deck/shots/` and Decky shows them to Steam (Steam's pages can't load pictures from a plain-http RomM)
  - **Activity**: your RomM notes (and other players' public ones), RetroAchievements unlocks and awards (needs the `me.read` scope, see Install), saves and states in RomM, when you last played, and how the last save sync on this PC went. It catches up when you open the page (at most every 15 minutes) and after you play
  - **Buttons under Game Info**: RomM (the game in RomM's web UI), RetroAchievements, HowLongToBeat and the trailer, in place of Steam's store and community links, which lead nowhere for these games
- **Controller presets** (per platform, off by default, toggled on the game's page; every setting they change is put back after the game, also after a crash, and anything you change in the emulator meanwhile is kept):
  - **Ally motion** (ROG Ally / Xbox Ally) for **Switch** (Ryujinx), **Wii U** (Cemu) and **3DS** (Azahar): motion and tilt from the Ally's own sensor. EmuDeck's Steam Deck motion server can't see the Ally's motion under InputPlumber (and InputPlumber up to 0.81 sent the accelerometer wrong, [InputPlumber #715](https://github.com/ShadowBlip/InputPlumber/issues/715)), so the plugin reads it itself, from the sensor or, when InputPlumber 0.82+ is streaming from it, from InputPlumber's virtual Steam Deck controller, and serves it at 127.0.0.1:26760 while a game runs. EmuDeck already points Cemu and Azahar there; the preset only sets it where it isn't. Calibrate once from a game page (lay it flat, then stand it up facing you). Nothing is downloaded or installed
  - **Use my real Wii Remotes** for **Wii** (Dolphin, any device): all four players use real Wii Remotes instead of emulated ones, and Dolphin keeps looking for them, so pressing 1+2 on a remote connects it
  - See `presets.py` and `motion.py`
- **BIOS**: download a platform's firmware from RomM into `Emulation/bios` (Switch keys also go to Ryujinx)

## Install

1. Decky settings → Developer mode on → Developer → **Install plugin from ZIP** → `romm-deck.zip`
2. In the RomM web UI: Settings → **Client API Tokens** → create one with these scopes:
   `roms.read`, `collections.read`, `assets.read`, `assets.write`, `firmware.read`
   (and `me.read` if you want your RetroAchievements unlocks in a game's Steam Activity).
   Then choose **Pair device** to get a short code (valid for 60 seconds).
3. In the plugin, enter your RomM address and the pairing code (or paste the whole `rmm_…` token).

## How it works

[ARCHITECTURE.md](ARCHITECTURE.md) describes the code: its parts, how data moves between them, and the
files it keeps. In short:

Each RomM Deck card runs `python3 bin/romm_launch.py <rom id>`, which pulls saves, starts the game, then
pushes whatever save files changed. A taken-over card runs the command it had before (kept in
`installed.json` as `original`); a card the plugin made runs EmuDeck's launcher script. If RomM is
unreachable the game still starts.

**Closing a game**: use Steam's "Exit game" as usual. Steam closes the game's whole process tree,
launcher included, so the launcher doesn't rely on outliving the emulator: it leaves a note
(`session-<rom id>.json`) when the game starts, and the after-game work (push saves, put controller
settings back) is done once, by whichever notices first: the launcher (it ignores Steam's close
request so it can finish), the plugin when Steam reports the game stopped, or the plugin when it
next starts (after a crash or power-off). It waits until nothing is still running the game file,
so the emulator has finished writing its save. If you uninstall the plugin, run Steam ROM Manager to put the
EmuDeck commands back on taken-over cards.

**Saves**: EmuDeck doesn't always manage to point an emulator at `Emulation/saves`, so the launcher
watches up to three places for each game: `Emulation/saves/<emulator>` (EmuDeck), the emulator's own folders
(`DEFAULT_ROOTS` in `saves.py`, flatpak and AppImage locations), and, for emulators that save next to the
game (melonDS: `SAVES_NEXT_TO_GAME` in `systems.py`), the game's folder in `roms/`, where only files named
after the game that aren't game files count. It snapshots them before and after you play; changed files belong to
that game. Loose files in the emulator's main folder (RetroArch `.srm`/`.state`…) upload one by one;
anything else uploads as one `<emulator>-saves.romm.zip` per game, which remembers which folder each file
came from. If a save changed both here and on RomM, the newer copy is kept locally and the other is
uploaded as `conflict-<time>-<name>`. For games started from other cards (Steam ROM Manager), saves are
found by name instead: files named after the game file, like `<game>.srm` or `<game>_1.mcd`. Switch saves
are found from Ryujinx's own save index (`bis/system/save/8000000000000000/0/imkvdb.arc`), using the game's
title ID from RomM (or a `[0100…]` tag in the file name).

**Change an emulator**: edit that platform's line in `systems.py`.

## Files on the machine

- Settings and state: `~/homebrew/settings/romm-deck/` (`settings.json`, `installed.json`, `sync.json`, `moved.json`)
- Small cover art for the panel: `~/homebrew/settings/romm-deck/covers/` (fetched from RomM once; safe to delete)
- Last save sync per game, for the game page: `~/homebrew/settings/romm-deck/sync-status.json`
- RomM's details for Steam game pages: `~/homebrew/settings/romm-deck/steam-details.json` (refreshed weekly; safe to delete)
- Copies of RomM's screenshots for Steam game pages: `~/homebrew/data/romm-deck/shots/` (removed with the game; safe to delete)
- Logs: Decky's plugin log, `~/homebrew/logs/romm-deck/launch.log` for game launches, and `removed.log` for every file the plugin has deleted

## Build

```sh
npm install        # just esbuild
npm test           # every test suite
npm run package    # builds dist/index.js and romm-deck.zip
```

## Contributing, changes, license

- [CONTRIBUTING.md](CONTRIBUTING.md): how to report a problem, set up, test and send a change
- [CHANGELOG.md](CHANGELOG.md): what's in each release
- [LICENSE](LICENSE): BSD 3-Clause
