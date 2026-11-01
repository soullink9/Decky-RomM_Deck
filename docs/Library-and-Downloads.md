# Library and Downloads

## Browsing

The home page leads to your library four ways:

- **On this PC**: every game the plugin knows is downloaded, with **Find games already on this PC** and
  **Remove several games** at the top.
- **Platforms** and **Collections** (regular and smart): RomM's own lists, with how many games each holds.
- **Search RomM**: by name.

Games already on the PC show a ✓ in every list. Opening a game shows its page: cover, platform, year, size,
developer, whether it's on the PC, and when its saves last synced.

**Opens on the game you're on.** Open the Quick Access menu while you're on a game's Steam page, or while
playing it, and the panel jumps straight to that game. This works for cards Steam ROM Manager made, too. It
only checks when the menu opens, never while it's open, so nothing moves under you. Open the menu
somewhere else later and the panel goes back to where you were.

## Downloading

Press **Download** on a game's page. The download runs in the background: you can close the menu, and the
home page shows everything that's downloading with a progress bar.

When it's done the game is in its platform's folder under `Emulation/roms` (see
[Platforms and Emulators](Platforms-and-Emulators.md)), and gets a **Steam card** with RomM's cover art, in
the same Steam collection Steam ROM Manager uses (for example "Nintendo Game Boy Advance"), so it sits with
your other games. A popup says when it's done.

- Games RomM keeps as several files (multi-disc games, PS3 games) arrive as a folder, with the right file
  chosen for the emulator to open (an `.m3u` playlist, for example).
- A zipped game is unpacked, unless its emulator reads zips itself.
- A platform with no emulator set up still downloads; it just gets no Steam card.
- If a file with the same name is already there and belongs to another game, nothing is overwritten.

## Switch updates and DLC

RomM labels each file of a Switch game as the game, an update or DLC. The game goes into `roms/switch`,
and updates and DLC go into their own folder, the one Ryujinx loads them from automatically. The plugin
finds that folder in Ryujinx's settings; if Ryujinx has none, set one on the home page (**Switch updates &
DLC folder**).

Games already on the PC get a **Download updates & DLC** button on their page. Remove deletes only the
update and DLC files the plugin downloaded, and only from that folder.

## Games already on the PC

Games you copied into `Emulation/roms` yourself (or that another tool put there) are recognised when they
show up in a list, or all at once with **On this PC → Find games already on this PC**. A file counts as a
RomM game when it has:

1. the same file name as in RomM, or
2. the same name with another file type the emulator opens (a `.cue`/`.bin` game you converted to `.chd`), or
3. for a game RomM keeps as several files (a Switch game with its update and DLC), the main game file on its
   own, or
4. a Switch title ID in its name (`[0100…]`), or the same name once tags like `(USA)` or `[v0]`, punctuation,
   capitals and "The" are ignored, **only when exactly one file fits**.

PS3 games kept as a folder (`roms/ps3/<game>/PS3_GAME/USRDIR/EBOOT.BIN`) are recognised by the folder's name.

The matching never guesses: if two files could be the same game, neither is used. A file is linked to only
one RomM entry, even if RomM has duplicates.

**Moved or deleted RomM entries.** If RomM no longer has a game (you deleted a duplicate, say), opening the
game or running **Find games already on this PC** moves it to the RomM entry with the same file, with its
Steam card and save history. Cards keep working, because old RomM ids are forwarded.

## Your existing Steam cards

Cards EmuDeck made with Steam ROM Manager can sync saves too:

- **Sync saves on all my Steam cards** (home page) checks every non-Steam card, and takes over the ones that
  start a game RomM has.
- **Sync saves automatically with this card** does it for one card. It shows on a game's page when you
  opened the menu from that card's Steam page.

Taking over a card changes only the command it runs: the card then starts RomM Deck's launcher, which runs
the card's original command exactly as Steam did, with a save sync before and after. The card's name, artwork,
playtime and collections stay. Steam ROM Manager puts its own command back when you run it again; the plugin
notices when it next loads and takes the card back.

## BIOS files

**Get <platform> BIOS** on a game's page downloads every BIOS and firmware file RomM has for that platform
into `Emulation/bios`. Switch keys (`.keys` files) also go into Ryujinx's own `system` folder.

## Removing games

See [Saves and States](Saves-and-States.md#removing-a-game): a game is only removed once its saves are safe on
RomM.
