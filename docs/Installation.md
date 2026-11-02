# Installation

**Needs:**

- A handheld or PC running **Bazzite** or **SteamOS** in Game Mode, with
  [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) installed. Developed and tested on a
  ROG Xbox Ally X with Bazzite.
- **[EmuDeck](https://www.emudeck.com/)**, set up as usual. The plugin reads EmuDeck's own settings to find your
  `Emulation` folder, wherever it is (internal storage or an SD card).
- A **[RomM](https://github.com/rommapp/romm)** server the handheld can reach. Developed against RomM 5.4.1.

## Installing the plugin

1. In Game Mode, open Decky's settings (the cog in the Decky tab of the Quick Access menu) and turn on
   **Developer mode**.
2. Go to **Developer → Install plugin from URL**, enter this address and confirm:

   ```
   https://github.com/soullink9/Decky-RomM_Deck/releases/latest/download/romm-deck.zip
   ```

3. **RomM Deck** appears in the Decky tab.

That address always gets the newest full release. For a specific version, or a pre-release (`-beta`), use the
address in that [release](https://github.com/soullink9/Decky-RomM_Deck/releases)'s notes: pre-releases don't
count as the latest. The address has to be the zip itself; a release page's address is a web page, and Decky
stops on it at "Parsing zip file".

Without a network on the handheld: download `romm-deck.zip` from a release, copy it over, and use
**Developer → Install plugin from ZIP** instead.

## The RomM token

RomM Deck signs in to RomM with a client API token. Create one in RomM's web UI under **Settings → Client API
Tokens**, with these permissions:

| Permission | Why |
|---|---|
| `roms.read` | Browse your library and download games |
| `collections.read` | Browse collections and smart collections |
| `assets.read` | Download your saves and save states |
| `assets.write` | Upload your saves and save states |
| `firmware.read` | Download BIOS files |
| `me.read` *(optional)* | Show your RetroAchievements unlocks in a game's [Activity](Steam-Game-Pages.md#activity) |

Without `me.read` everything else works; the Activity list just leaves out achievements.

## Pairing

1. In RomM's web UI, next to the token, choose **Pair device**. You get a short code that works for 60 seconds.
2. Open **RomM Deck** in the Quick Access menu, enter your RomM address (for example
   `https://romm.example.com`, or `http://192.168.1.10:8080` on your home network) and the code, and press
   **Connect**.

You can also paste the whole token (it starts with `rmm_`) instead of a code. The plugin checks the token
works before saving it.

## First steps

- **Already have games in `Emulation/roms`?** Open **On this PC → Find games already on this PC**. Games
  RomM also has are recognised, without downloading them again.
- **Already have EmuDeck cards in Steam?** Press **Sync saves on all my Steam cards** on the home page, so they
  sync saves too. See [Library and Downloads](Library-and-Downloads.md#your-existing-steam-cards).
- **Using RetroArch, PPSSPP, DuckStation, PCSX2 or Flycast?** Press **Turn off auto-load states**. See
  [Saves and States](Saves-and-States.md#auto-load-states) for why.

## Updating

Install it the same way: **Developer → Install plugin from URL** with the same address gets the newest
release. Your settings, games, cards and save history carry over. The [changelog](../CHANGELOG.md) lists what changed.

## Removing

1. **Put your EmuDeck cards back**, if you let RomM Deck take any over: run Steam ROM Manager (in EmuDeck)
   once. It puts its own commands back on the cards. Cards RomM Deck made itself would stop working without
   the plugin, so remove those games from the plugin first, or delete the cards in Steam.
2. In Decky's settings, uninstall **RomM Deck**.
3. Optionally delete its files (see [Privacy and Security](Privacy-and-Security.md#files-on-your-device)).
   Your games stay in `Emulation/roms` and your saves stay in the emulators' folders and on RomM.
