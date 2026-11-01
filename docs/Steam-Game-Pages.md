# Steam Game Pages

For games with a RomM Deck card, Steam's own game page in Game Mode shows what RomM knows about the game.
It's on by default; **RomM details on Steam game pages** on the plugin's home page turns all of it off at once.

## Game Info

- **Description, developer, publisher, release date, rating** and **feature icons** (single player,
  multiplayer, co-op, split screen) in Steam's own places.
- A **details block** under the description with everything else RomM has: genres, themes, game modes,
  players, perspective, franchise, series, age rating, How Long To Beat, RetroAchievements, other names,
  keywords, regions, languages, revision, tags, platform, file, and your RomM status (playing, completion,
  rating).
- **Buttons** under Game Info link to the game in **RomM**'s web UI, and to **RetroAchievements**,
  **HowLongToBeat** and its **trailer** when RomM has them. They replace Steam's store and community links,
  which lead nowhere for these games, and open in Steam's own browser.

## Screenshots

RomM's screenshots of the game (up to 10), after any you took yourself with Steam. The plugin keeps copies
on the PC and Decky shows them to Steam: Steam's pages can't load pictures straight from a RomM server on
plain http or with a self-signed certificate.

## Activity

A list of what's happened with the game, newest first:

- your **RomM notes**, and other players' public notes, with who wrote them;
- your **RetroAchievements** unlocks (with badges, points and hardcore) and awards such as "Beaten", if your
  RetroAchievements account is linked in RomM and the token has the `me.read` permission (see
  [Installation](Installation.md#the-romm-token));
- **saves and save states** in RomM, and when you **last played**;
- how the **last save sync** on this PC went.

Steam's own Activity content, if it shows any, stays above the list. Pressing a note opens the game in RomM.

## Keeping it current

The details are kept on the PC, so pages show them straight away. They're fetched again in the background:

- when they're more than a week old,
- when you open the game's page and they're more than 15 minutes old,
- when you close the game (so new saves and "last played" show up).

## How it works, and what it doesn't do

Steam only draws a game's info section for games it believes are Steam games. So while a RomM Deck card's
own page is open, Steam is told that game isn't a shortcut; everywhere else it gets the truth, and Play and
launching always see the real card. Nothing is written to Steam's files, and every change is
undone when the plugin unloads or the switch is turned off.

This is the same approach as the [MetaDeck](https://github.com/EmuDeck/MetaDeck) and
[Decky Metadata](https://github.com/beallio/Decky-Metadata) plugins. Don't use them on the same games as
RomM Deck: they would fight over the same page.

Because this uses Steam's internal page code, a Steam update can change what's needed. If something doesn't
match, the plugin falls back to Steam's normal page, and writes a line starting with `Steam page:` to its
log describing what it found ([Troubleshooting](Troubleshooting.md#steam-game-pages)).
