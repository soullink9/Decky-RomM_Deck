# Privacy and Security

There are no accounts beyond your own RomM, and no analytics, tracking or update checks. Nothing is stored
anywhere except your handheld and your RomM server.

## What leaves your handheld

| Sent to | What is sent | Why | When |
|---|---|---|---|
| Your RomM server | Your token, and requests for your library, games, covers, screenshots, saves and BIOS files; your save and state files | Everything the plugin does | When you browse, download, play, sync or open a game's Steam page |
| `media.retroachievements.org` | A request for an achievement badge image (Steam's page loads it) | Badges in a game's Activity list | When a page with unlocked achievements is shown |
| Sites you open from a game's Steam page (RomM, RetroAchievements, HowLongToBeat, YouTube) | Whatever that site asks for, in Steam's browser | The Game Info buttons | Only when you press one |

Like any web request, these see your public IP address (your RomM server sees your local one if it's on your
network). Nothing else about the handheld, its games or its sensors is sent anywhere. The motion server only
listens on the handheld itself (`127.0.0.1`), and ignores anything from elsewhere.

During a Wii game with **Use my real Wii Remotes** on, the plugin looks at the game's own processes on the
handheld: Dolphin's command line, and which programs have the Wii Remote sensor open (only programs running as
you). What it finds goes into a popup and `launch.log`, and nowhere else.

## The RomM token

- It's stored in `~/homebrew/settings/romm-deck/settings.json`, in plain text, like other Decky plugins'
  settings (SteamOS has no keyring Decky plugins can use). The file is readable by your user only, but
  anything running as your user can still read it.
- It's sent only to your RomM server, with each request. If RomM redirects a request to another address (a
  different host or port), the request goes there without the token. Plain `http` works, since most RomM
  servers are on the home network; use `https` if your RomM is reachable from the internet.
- The plugin never writes it to its logs. Check logs and screenshots for your RomM address anyway before
  sharing them.
- Give it only the permissions in [Installation](Installation.md#the-romm-token). **Disconnect** on the home page
  forgets it on the handheld; delete the token in RomM's web UI to revoke it completely.

## What the plugin can change on your handheld

- Games in `Emulation/roms`, BIOS files in `Emulation/bios`, Switch updates and DLC in their own folder.
- Save files in the emulators' save folders: pulled from RomM, and deleted only by **Remove** after the checks in
  [Saves and States](Saves-and-States.md#removing-a-game).
- Steam cards: ones it made, and the command of ones you let it take over.
- One setting per emulator for **Turn off auto-load states**, and, during a game, the settings a
  [controller preset](Controller-Presets.md) changes.

It never deletes anything outside `Emulation/roms`, a whole platform folder, or a file that belongs to another
game, and every file it deletes is listed in `~/homebrew/logs/romm-deck/removed.log`.

## What it accepts from RomM

The plugin trusts your RomM server with your library, but still checks what it sends before writing anything:

- File names (games, updates, BIOS files, single saves) must be plain names, with no folders in them.
- Zips (multi-disc games, zipped games, zipped saves) are checked entry by entry before anything is unpacked:
  no absolute paths, no `..`, no links or special files, no name twice, nothing landing outside the game's
  folder, and the unpacked size has to fit on the disk.
- Downloads stop if they wouldn't fit on the disk (with 512 MB to spare). Other answers have size limits too.
- One game downloads once at a time.
- Buttons on a Steam game page only open your RomM server's pages, RetroAchievements, HowLongToBeat and
  YouTube.

## Files on your device

| Where | What |
|---|---|
| `~/homebrew/settings/romm-deck/settings.json` | RomM address and token, preset switches and other options |
| `~/homebrew/settings/romm-deck/installed.json` | The games on this PC, their files and Steam cards |
| `~/homebrew/settings/romm-deck/moved.json` | Old RomM ids forwarded to new ones, so existing cards keep working |
| `~/homebrew/settings/romm-deck/sync.json` | Each game's save files and what was last synced |
| `~/homebrew/settings/romm-deck/sync-status.json` | How each game's last sync went |
| `~/homebrew/settings/romm-deck/steam-details.json` | RomM's details for Steam game pages |
| `~/homebrew/settings/romm-deck/motion-calibration.json` | The motion sensor's calibration |
| `~/homebrew/settings/romm-deck/controller-status.json` | How the last game with a controller preset went |
| `~/homebrew/settings/romm-deck/controller-backup.json`, `session-*.json` | A preset or game in progress (emptied or removed after the game) |
| `~/homebrew/settings/romm-deck/motion-ready.json` | Whether the motion server started, for the game's popup |
| `~/homebrew/settings/romm-deck/notify/` | Popups waiting to be shown in Game Mode (removed once shown) |
| `~/homebrew/settings/romm-deck/*.lock` | Keep two syncs or saves from writing the same file at once (empty) |
| `~/homebrew/settings/romm-deck/covers/` | Small cover art for the panel (safe to delete) |
| `~/homebrew/data/romm-deck/shots/` | Copies of RomM's screenshots for Steam pages (safe to delete) |
| `~/homebrew/logs/romm-deck/` | The logs (see [Troubleshooting](Troubleshooting.md#logs)) |

Your saves themselves live in the emulators' folders and on RomM, not in these files.
