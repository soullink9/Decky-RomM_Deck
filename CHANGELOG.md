# Changelog

## 0.5.9 (2026-11-25)

### Maintenance

Build and CI updates only; the plugin itself is unchanged.

- Tests, builds and releases run on Node 26 (the current LTS) instead of Node 22.
- The Gitea workflows' images move from Debian bookworm to trixie (`python:3.10-trixie`, `node:26-trixie`). The
  backend is still tested on Python 3.10, the version Decky runs it on.
- GitHub's release workflow uses `actions/checkout` v7.0.1, `actions/setup-python` v7.1.0 and
  `actions/setup-node` v7.1.0, still pinned to exact commits.
- esbuild stays at 0.28.2, already the newest release.

## 0.5.8 (2026-11-22)

### Security

Fixes from a security review. Nothing changes in how the plugin is used: plain `http` RomM servers on the home
network keep working, and Steam launch options of taken-over cards still run exactly as Steam would run them.

- The RomM token only goes to your RomM server. If RomM redirects a request to another host or port, the
  request goes there without it. Redirects to anything but `http`/`https` are refused.
- File names from RomM (games, Switch updates and DLC, BIOS files, single saves) must be plain names, with no
  folders in them.
- Zips from RomM are checked before anything is unpacked: absolute paths, `..`, links and special files, names
  that appear twice, and anything that would land outside the game's folder stop the download. Zipped saves are
  checked the same way before any of their files is used.
- Downloads stop when they wouldn't fit on the disk (512 MB is always left free), and a zip must fit once
  unpacked. JSON answers, cover art and screenshots, and save downloads have size limits.
- The same game can't download twice at once.
- The plugin's settings files (`settings.json` holds the token) are readable by your user only. Files written
  by an older version are made private when the plugin starts.
- Settings files and emulator settings are flushed to the disk before they replace the old ones, so a power
  loss can't leave an empty file. An emulator's settings file keeps its permissions.
- Saves are compared by SHA-256 instead of SHA-1. Saves synced by an older version aren't seen as changed: their
  SHA-1 is still recognised, and replaced at their next sync.
- Steam game page buttons open only your RomM server's pages, RetroAchievements, HowLongToBeat and YouTube, and
  RomM's ids in those links are escaped.
- The motion server ignores anything that doesn't come from the handheld itself.
- The pairing code (or token) is cleared from the setup page once it's been used.

### Development

- GitHub's release workflow pins its actions to exact commits. Gitea's workflows use no actions.
- esbuild is pinned to an exact version (0.28.2).
- New frontend test: `tests/test_links.mjs`.

## 0.5.7 (2026-11-16)

### Controller presets

- "Use my real Wii Remotes" also turns off Dolphin's Bluetooth passthrough for that game, since with passthrough
  on Dolphin ignores the real Wii Remote setting. Like the rest of the preset, it's on Dolphin's command line
  and leaves Dolphin's files alone.
- A game's own Dolphin settings (its Properties in Dolphin) that pick emulated Wii Remotes win over the preset.
  The popup now names such games, and `launch.log` has what they set.

## 0.5.6 (2026-11-15)

### Development

- The tests use free ports for the fake RomM server and the motion server, so the test and release workflows
  can run at once on a runner with host networking. The v0.5.5 release failed because both bound 127.0.0.1:8765.

## 0.5.5 (2026-11-15)

### Install

- The self-hosted Decky store names only GitHub: every download link and icon on the `store` branch is
  GitHub's, and Gitea's address is never written there, since Gitea's push mirror copies that branch to
  GitHub too. A new version appears in the store once its GitHub release has the zip (checked every hour),
  instead of linking to the Gitea release until then. The `PUBLIC_GITEA_URL` variable is gone, and the store
  no longer asks Gitea for its public address.
- The `store` branch is now a single commit, replaced (force-pushed) on every update, so links from earlier
  versions of the store don't stay in its history. A branch that still has history is replaced at the next
  hourly refresh.

## 0.5.4 (2026-11-14)

### Install

- The self-hosted Decky store sends the handheld to GitHub for downloads: each version links to its GitHub
  release as soon as GitHub has it (checked every hour), and to the Gitea release until then. The store list
  itself stays on Gitea, since GitHub can't serve one to Decky.
- The store is never published without the official Decky store's listing, so the handheld can't lose the
  official plugins or their updates. The official store is asked with its own user agent.
- `romm-deck.zip` is now byte-for-byte reproducible, so Gitea's and GitHub's builds of a release are identical.
- The store branch has a README saying what it is.
- The store's Gitea links use the address Gitea is published at, asked of Gitea itself, instead of the
  runner's internal address; no variable needed.

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
  regularly, for a Decky that uses a self-hosted store. See
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
