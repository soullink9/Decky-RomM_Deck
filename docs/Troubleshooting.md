# Troubleshooting

## Logs

| Log | What's in it |
|---|---|
| Decky's log for RomM Deck: `~/homebrew/logs/romm-deck/` (the newest `.log` file) | The plugin itself: pairing, downloads, syncs from the panel, Steam page details |
| `~/homebrew/logs/romm-deck/launch.log` | Every game start: the save pull and push, the exact command run, and the emulator's own messages |
| `~/homebrew/logs/romm-deck/motion.log` | The motion server, while a motion preset is on |
| `~/homebrew/logs/romm-deck/removed.log` | Every file the plugin has ever deleted, with the time |

Before sharing a log, remove your RomM address and anything else private.

## Common questions

**The panel only says "RomM Deck didn't start".**
The plugin's Python side didn't load. Restart the handheld (which restarts Decky), or reinstall the
plugin. The reason is in Decky's log for RomM Deck.

**"Couldn't reach RomM" or a connection error.**
Check the handheld can reach RomM's address (open it in Steam's browser). Use the address exactly as you'd type
it in a browser, including `http://` and the port if RomM isn't on 443. Pairing codes expire after 60 seconds:
make a new one if pairing fails.

**A game I already have doesn't show as on this PC.**
Run **On this PC → Find games already on this PC**. If it still isn't found, the file's name is too different
from RomM's, or two files could be the same game, in which case the plugin won't guess. Rename the file to
RomM's file name. See [Library and Downloads](Library-and-Downloads.md#games-already-on-the-pc).

**A game doesn't start from its card.**
`launch.log` shows the command and what the emulator said. The most common reasons are an emulator not
installed in EmuDeck, or missing BIOS files (**Get <platform> BIOS** on the game's page).

**My saves didn't sync.**
The game page says when the last sync was and why it failed. "Saves not synced yet" means the game hasn't been
played through RomM Deck yet: start it from its card once. Saves for Xbox games aren't synced (see
[Platforms and Emulators](Platforms-and-Emulators.md)).

**"RomM's saves for this game are from …, which this PC doesn't use".**
RomM has saves for this game from a different emulator (another device or app). They're left alone; nothing is
overwritten.

**Remove says a save "didn't reach RomM".**
Nothing was deleted. Press **Sync** on the game's page, then try again. If it keeps happening, check that the
token has the `assets.write` permission.

**A game loads an old save state instead of my save.**
Press **Turn off auto-load states** on the home page. See
[Saves and States](Saves-and-States.md#auto-load-states).

**Motion doesn't work, or "Controller preset not applied".**
The popup when the game starts says why. Usually it's **Calibrate motion** (on the game's page) that's needed.
If another program is using the motion port, the popup says so too. See
[Controller Presets](Controller-Presets.md).

**Wii: the game uses an emulated Wii Remote, not my real ones.**
"Use my real Wii Remotes" works for Wii games started from a RomM Deck card (or an EmuDeck card RomM Deck has
taken over, as long as it runs EmuDeck's Dolphin launcher), and only while it's turned on in that game's page.
In version 0.5.0 and earlier, EmuDeck's launcher undid it every time; update RomM Deck. The popup when the game starts, and the line
under the preset on the game page, say what Dolphin can see:

- *a DolphinBar has to be in mode 4*: no Wii Remote sensor in Wii Remote mode is plugged in. On a Mayflash
  DolphinBar, press its mode button until the LED for mode 4 lights. In modes 1 to 3 the DolphinBar turns the
  remote into a mouse, keyboard or gamepad, so the game gets an emulated remote moved by it instead.
- *on the USB sensor*: Dolphin can use the DolphinBar; press 1+2 (or the DolphinBar's sync button) on each remote.
- *Dolphin isn't allowed to open the Wii Remote sensor on USB*: the system doesn't give apps access to the
  DolphinBar's Wii Remote slots, so remotes on it can't connect. Remotes over Bluetooth still can.

If there's no "Controller preset on" popup when the game starts, the preset wasn't used for that launch.

About half a minute into the game, a second popup says what RomM Deck found in the Dolphin that's running:

- *Dolphin is using real Wii Remotes and has the USB sensor open*: everything is in place; press 1+2 on a remote.
- *…hasn't opened the USB sensor yet*: Dolphin is set up but hasn't connected to the sensor; press 1+2 on a
  remote or the sensor's sync button, and check the DolphinBar is in mode 4.
- *…but steam also has the Wii Remote sensor open*: another program is using the sensor too, and can take the
  remotes' signals before Dolphin does.
- *Dolphin was started without the real Wii Remote setting*: the card started Dolphin some other way than
  EmuDeck's Dolphin launcher, so the setting couldn't be passed on. Start the game from its RomM Deck card.

Turning the preset on or off during a game takes effect the next time the game starts. The launch log (Decky's
logs for RomM Deck) lists Dolphin's command line and which programs had each sensor slot open.

**Installing from a URL stops at "Parsing zip file".**
Decky got something that isn't the plugin's zip. Use the address in
[Installation](Installation.md#installing-the-plugin), which ends in `/romm-deck.zip`; the address of a
release's page doesn't work. A pre-release isn't the latest release, so use the address in its release notes.

**My EmuDeck card went back to its old command.**
Steam ROM Manager puts its own commands back when it runs. RomM Deck takes the card back the next time it loads,
or press **Sync saves on all my Steam cards**.

## Steam game pages

If RomM's details, buttons or Activity don't show on a game's page:

1. Check **RomM details on Steam game pages** is on (home page).
2. The details arrive in the background the first time: close and reopen the page after a few seconds.
3. Check the card is a RomM Deck card (the game's panel page shows it as on this PC).
4. Look in Decky's log for RomM Deck for a line starting with `Steam page:`. It describes what the plugin found
   on Steam's page when it couldn't find its place; include it when you report the problem.

## Known issues

- **Gyro aiming** can feel slow or reversed in some games. See
  [Controller Presets](Controller-Presets.md#known-limitations).
- **Steam updates** can change Steam's internal page code. The Steam page features then fall back to Steam's
  normal page until the plugin is updated.

## Reporting a problem

[Open an issue](https://github.com/soullink9/Decky-RomM_Deck/issues/new/choose) and fill in the form. Include
your device, Decky Loader, RomM and RomM Deck versions, and the relevant log lines.
