# Changelog

## Unreleased

### Controller presets

- "Use my real Wii Remotes" now checks the Dolphin that actually started, about half a minute into the game,
  and says what it found in a second popup and on the game page: whether Dolphin got the real Wii Remote
  setting, whether it has the Wii Remote sensor open, and whether another program (Steam, say) has it open too.
  The details go into the launch log.
- Turning a preset on or off while a game runs now says it takes effect from the next launch: a running
  emulator has already read its settings.

### Install

- A Decky store on Gitea: each release made on Gitea is added to the repository's `store` branch, which Decky
  can use as a custom store (Decky settings → Plugin Store → Custom), for installs and update notifications.
  [CONTRIBUTING](CONTRIBUTING.md#a-decky-store-on-gitea) has the web server rule it needs.

### Repository

- Gitea is the main copy: its runner tests every push and publishes releases
  (`.gitea/workflows/`), with nothing downloaded from GitHub, so it keeps working when GitHub can't be reached.
  Gitea push-mirrors to GitHub, and a version tag arriving there publishes the same release on GitHub.
- The release helpers moved to `scripts/` (used by both), and `package.sh` zips with Python, so a runner needs
  nothing beyond Python and Node.

## 0.5.1 (2026-11-08)

### Install

- Install from a link: each release's notes give the zip's download address for Decky's **Install plugin
  from URL**, and the [installation guide](docs/Installation.md) has one that always gets the latest release.
- Every `romm-deck.zip` is checked the way Decky reads it before it's published, so a release can't stop at
  "Parsing zip file".

### Controller presets

- Fixed "Use my real Wii Remotes": Dolphin still used emulated remotes. EmuDeck's launcher sets every Wii
  Remote back to emulated in Dolphin's settings just before Dolphin starts, undoing the preset. The preset now
  tells Dolphin on its command line instead, which wins over its settings files and changes nothing in them.

### Repository

- A brand icon for RomM Deck, in `assets/brand/`.

## 0.5.0 (2026-11-01)

Initial release: the first public beta of RomM Deck, a Decky Loader plugin for RomM and EmuDeck. The
[documentation](README.md#documentation) covers every feature below.

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
  The popup says whether Dolphin can use a DolphinBar, and when it needs switching to mode 4.
- Every setting a preset changes is put back after the game, also after a crash, and changes you
  make in the emulator meanwhile are kept.

### Panel

- Opens on the game whose Steam page you're on, or the one you're playing.
- Cover art in every list, status lines for downloads and saves.

### Repository

- Documentation under `docs/`, an [architecture overview](ARCHITECTURE.md), a [contributor guide](CONTRIBUTING.md)
  and a [code of conduct](CODE_OF_CONDUCT.md).
- Tests that run without Steam or Decky: the whole backend against a fake RomM server, the motion server, and the
  frontend's Steam card handling.
- A bug-report form, and a release workflow: enter a version (or push a version tag) and it tests, builds and
  publishes the release.

### Known limitations

- Ally motion aiming can feel slow or reversed in some games; the axis mapping for handheld
  orientation is still being worked on.
- Steam game page features rely on Steam's internal UI, which can change with a Steam update; the
  plugin falls back to Steam's own page if anything doesn't match.
- RetroAchievements unlocks need a RomM API token with the `me.read` permission.

