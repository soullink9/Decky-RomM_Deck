# Changelog

## 0.5.3 (2026-11-13)

Initial release: the first public beta of RomM Deck, a Decky Loader plugin for RomM and EmuDeck. The
[documentation](README.md#documentation) covers every feature below.

### Install

- Install from a link: Decky's **Install plugin from URL** with the address in the
  [installation guide](docs/Installation.md), which always gets the newest release, or the address in a
  release's notes for that version.
- Every `romm-deck.zip` is checked the way Decky's installer reads it before it's published.

### Library and downloads

- Browse your RomM server by platform, collection (regular and smart) or search, from the Quick Access menu.
- Download a game into the right `Emulation/roms` folder, with a Steam card, RomM's cover art and the
  same Steam collection Steam ROM Manager uses. Downloads keep going with the menu closed, and show
  on the home page with a progress bar.
- Switch updates and DLC download into the folder Ryujinx loads them from, not `roms/switch`.
- Games already in `Emulation/roms` are recognised (same file, same name in another format, Switch
  title id, or a matching name, only when exactly one file fits), including PS3 games kept as folders.
- Games whose RomM entry was deleted are moved to the RomM entry that matches their file, with their
  Steam card and save history.
- BIOS and firmware download from RomM into `Emulation/bios` (Switch keys also go to Ryujinx).

### Saves and save states

- Saves and save states sync with RomM: pulled before a game starts, pushed after it closes, plus
  Sync, Push to RomM and Pull from RomM on each game, and "Sync all saves now".
- Works however the game is closed, including Steam's "Exit game", a crash or a power-off.
- No version of a save is ever lost: conflicts and replaced copies are kept on RomM as
  `conflict-…` and `backup-…` files.
- Existing EmuDeck cards can sync saves too: the plugin takes them over and runs their original
  command, keeping names, artwork and playtime.
- Remove from this PC (one game, or several at once) only deletes anything once RomM holds an
  identical copy of every save. Shared memory cards are never deleted, and every deleted file is logged.
- Turn off "load the last state on start" in every emulator that has it.
- Popups in Game Mode when saves sync and when a controller preset goes on and off.

### Steam game pages

- For games with a RomM Deck card, Steam's game page shows RomM's description, developer, publisher,
  release date, rating, feature icons and every other detail RomM has.
- RomM's screenshots in the Screenshots section.
- An Activity list: your RomM notes, RetroAchievements unlocks and awards, saves and states in RomM,
  last played, and the last save sync.
- Game Info buttons link to the game in RomM, RetroAchievements, HowLongToBeat and its trailer.
- One switch on the home page turns all of it off.

### Controller presets

- Motion (gyro and tilt) from the ROG Ally / Xbox Ally's own sensor for Switch (Ryujinx), Wii U (Cemu)
  and 3DS (Azahar), served to the emulator while the game runs, with a one-time calibration.
- "Use my real Wii Remotes" for Wii (Dolphin), on any device, over Bluetooth or a Mayflash DolphinBar in mode 4.
  The setting goes on Dolphin's command line, which wins over EmuDeck's controller auto-mapping and changes
  nothing in Dolphin's files. A popup when the game starts says whether a Wii Remote sensor is usable, and a
  second one, half a minute in, says what the running Dolphin has: the setting, the sensor, another program
  holding it, and what Dolphin itself reported about Wii Remotes.
- Every setting a preset changes in a file is put back after the game, also after a crash, and changes you
  make in the emulator meanwhile are kept. Switching a preset during a game takes effect at the next launch.

### Panel

- Opens on the game whose Steam page you're on, or the one you're playing.
- Cover art in every list, status lines for downloads and saves.

### Repository

- Documentation under `docs/`, an [architecture overview](ARCHITECTURE.md), a [contributor guide](CONTRIBUTING.md)
  and a [code of conduct](CODE_OF_CONDUCT.md).
- Tests that run without Steam or Decky: the whole backend against a fake RomM server, the motion server, the
  frontend's Steam card handling, and the release scripts.
- Self-hosted first: a Gitea runner tests every push and publishes releases with nothing downloaded from GitHub
  (`.gitea/workflows/`), and the same release is published on GitHub when its tag arrives there.
- A Decky plugin store on the `store` branch: every release plus the official Decky store's listing, refreshed
  every six hours, for a Decky that uses a self-hosted store. See
  [CONTRIBUTING](CONTRIBUTING.md#a-decky-store-on-gitea).
- A bug-report form and a brand icon (`assets/brand/`).

### Known limitations

- Ally motion aiming can feel slow or reversed in some games; the axis mapping for handheld
  orientation is still being worked on.
- Real Wii Remotes started from Game Mode don't connect on some setups, although choosing "Real Wii Remote" in
  Dolphin's own window works; the popups and `launch.log` help find out why.
- Steam game page features rely on Steam's internal UI, which can change with a Steam update; the
  plugin falls back to Steam's own page if anything doesn't match.
- RetroAchievements unlocks need a RomM API token with the `me.read` permission.
