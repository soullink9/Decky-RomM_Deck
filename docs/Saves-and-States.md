# Saves and States

Your saves and save states live in RomM, and every game you play through RomM Deck keeps them in step:

- **Before a game starts**, newer saves are pulled from RomM.
- **After it closes**, whatever changed is pushed back.
- If RomM can't be reached, the game still starts with the saves on the PC, and they go up next time.

A popup in Game Mode says what happened each time ("Saves synced", or why not).

## The save buttons

Each game's page has three buttons under **Saves & states**:

| Button | What it does |
|---|---|
| **Sync** | Newest copy wins, here or on RomM. The same as what happens around a game. |
| **Push to RomM** | This PC's saves replace RomM's. RomM's old copy is kept as `backup-<time>-<name>`. |
| **Pull from RomM** | RomM's saves replace this PC's. This PC's copy goes to RomM first as `backup-<time>-<name>`. |

**Sync all saves now** on the home page syncs every downloaded game. The game page says when its saves last
synced, or that the last sync failed and why.

Quit a game before you **Pull**: an emulator may write its own save over it when it closes.

## Nothing is ever thrown away

- If a save changed **both** here and on RomM since the last sync, the newer copy is kept on the PC, and the
  other one is uploaded to RomM as `conflict-<time>-<name>`.
- Push and Pull keep the copy they replace on RomM as `backup-<time>-<name>`.
- You can see and download every one of these in RomM's web UI (**Open on RomM** on the game's page).

## How it finds your saves

EmuDeck doesn't always manage to point an emulator at `Emulation/saves`, so for each game the plugin watches
up to three places:

1. `Emulation/saves/<emulator>` (EmuDeck's folders and links),
2. the emulator's own save folders (flatpak and AppImage locations), in case EmuDeck didn't set it up,
3. for emulators that save next to the game (melonDS), the game's own folder in `roms/`, where only files
   named after the game, and that aren't game files, count.

It looks at those folders just before and just after you play: files that changed while the game ran belong to
that game. Files named after the game (like `<game>.srm` or `<game>_1.mcd`) are found too, for games you've
played from other cards, and Switch saves are found through Ryujinx's own save index using the game's title ID.
[Platforms and Emulators](Platforms-and-Emulators.md#where-saves-are-looked-for) lists every folder.

**How they're stored on RomM.** Emulators that keep one flat folder of files (RetroArch, melonDS) upload each
file as it is, so RomM's web player can use it too. Everything else (Switch, PS3, Wii...) uploads one zip per
game, `<emulator>-saves.romm.zip`, which remembers which folder each file came from. Saves from RomM's web
player are picked up for RetroArch games, under RetroArch's name for the game.

Files over 512 MB aren't synced (they're disk images, not saves).

## Closing a game

Use Steam's **Exit game** as usual. The plugin doesn't depend on its launcher surviving that:

- When a game starts, the launcher leaves a note that the game is running.
- The after-game work (push saves, put controller settings back) is done once, by whichever notices first
  that the game ended: the launcher itself, the plugin when Steam reports the game stopped, or the plugin when
  it next starts, after a crash or a power-off.
- It waits until nothing is still running the game file, so the emulator has finished writing its save.

## Removing a game

**Remove from this PC** on a game's page (or **Remove several games** on the On this PC list) needs two
presses. Then, for each game:

1. Its saves and states are synced with RomM.
2. RomM's copies are downloaded and compared with every save file on the PC. If any file isn't on RomM, or
   RomM can't be reached, **nothing is deleted**, and you're told which file.
3. The save files are deleted, then the game, its updates and DLC, and its Steam card.

Some files are never deleted:

- memory cards shared by every game (PS2 `Mcd001.ps2`, DuckStation `shared_card_1.mcd`, Dolphin
  `MemoryCardA.raw`), and any file another game also uses;
- anything outside `Emulation/roms`, a whole platform folder, or a folder that holds another game.

Every file the plugin deletes is listed in `~/homebrew/logs/romm-deck/removed.log`. A game that's running can't
be removed.

## Auto-load states

Several emulators can load the last save state automatically when a game starts. With synced saves that's a trap:
the state can be older than the save you just pulled, and loading it puts you back where you were. **Turn off
auto-load states** on the home page turns it off in every emulator that has it: RetroArch (and its per-core,
per-folder and per-game overrides), PPSSPP, Flycast, DuckStation and PCSX2. It also stops EmuDeck from turning
RetroArch's back on. Only that one setting changes in each file.
