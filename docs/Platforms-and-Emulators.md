# Platforms and Emulators

Each RomM platform below has a folder under `Emulation/roms`, an emulator and a Steam collection, following
EmuDeck's own Steam ROM Manager setup, so a game RomM Deck downloads starts the same way your other EmuDeck
games do (through EmuDeck's launcher scripts in `Emulation/tools/launchers`).

Platforms not listed still download (into `roms/<RomM's folder name>`); they just get no Steam card and no save
sync.

| RomM platform | Folder | Emulator | Saves synced | Steam collection |
|---|---|---|---|---|
| `nes`, `famicom`, `fds` | `nes`, `famicom`, `fds` | RetroArch (Mesen) | yes | Nintendo Entertainment System |
| `snes`, `sfam` | `snes`, `sfc` | RetroArch (Snes9x) | yes | Nintendo SNES (Super Nintendo) |
| `n64` | `n64` | RetroArch (Mupen64Plus-Next) | yes | Nintendo 64 |
| `gb` | `gb` | RetroArch (Gambatte) | yes | Nintendo Game Boy |
| `gbc` | `gbc` | RetroArch (Gambatte) | yes | Nintendo Game Boy Color |
| `gba` | `gba` | RetroArch (mGBA) | yes | Nintendo Game Boy Advance |
| `virtualboy` | `virtualboy` | RetroArch (Beetle VB) | yes | Nintendo Virtual Boy |
| `nds` | `nds` | melonDS | yes | Nintendo DS |
| `3ds` | `n3ds` | Azahar | yes | Nintendo 3DS |
| `ngc` | `gc` | Dolphin | yes | Nintendo GameCube |
| `wii` | `wii` | Dolphin | yes | Nintendo Wii |
| `wiiu` | `wiiu/roms` | Cemu | yes | Nintendo Wii U |
| `switch` | `switch` | Ryujinx | yes | Nintendo Switch |
| `psx` | `psx` | DuckStation | yes | Sony PlayStation |
| `ps2` | `ps2` | PCSX2 | yes | Sony PlayStation 2 |
| `ps3` | `ps3` | RPCS3 | yes | Sony PlayStation 3 |
| `psp` | `psp` | PPSSPP | yes | Sony PlayStation Portable |
| `sg1000` | `sg-1000` | RetroArch (Genesis Plus GX) | yes | Sega SG-1000 |
| `sms` | `mastersystem` | RetroArch (Genesis Plus GX) | yes | Sega Master System |
| `genesis` | `genesis` | RetroArch (Genesis Plus GX) | yes | Sega Genesis/Mega Drive |
| `gamegear` | `gamegear` | RetroArch (Genesis Plus GX) | yes | Sega Game Gear |
| `segacd` | `segacd` | RetroArch (Genesis Plus GX) | yes | Sega CD/Mega CD |
| `sega32` | `sega32x` | RetroArch (PicoDrive) | yes | Sega 32X |
| `saturn` | `saturn` | RetroArch (Beetle Saturn) | yes | Sega Saturn |
| `dc` | `dreamcast` | RetroArch (Flycast) | yes | Sega Dreamcast |
| `tg16` | `pcengine` | RetroArch (Beetle PCE) | yes | NEC PC Engine/TurboGrafx 16 |
| `turbografx-cd` | `pcenginecd` | RetroArch (Beetle PCE) | yes | NEC PC Engine/TurboGrafx 16 CD |
| `atari2600` | `atari2600` | RetroArch (Stella) | yes | Atari 2600 |
| `lynx` | `atarilynx` | RetroArch (Beetle Lynx) | yes | Atari Lynx |
| `neo-geo-pocket` | `ngp` | RetroArch (Beetle NeoPop) | yes | SNK Neo Geo Pocket |
| `neo-geo-pocket-color` | `ngpc` | RetroArch (Beetle NeoPop) | yes | SNK Neo Geo Pocket Color |
| `wonderswan` | `wonderswan` | RetroArch (Beetle WonderSwan) | yes | Bandai WonderSwan |
| `wonderswan-color` | `wonderswancolor` | RetroArch (Beetle WonderSwan) | yes | Bandai WonderSwan Color |
| `arcade` | `arcade` | RetroArch (MAME) | yes | Arcade |
| `dos` | `dos` | RetroArch (DOSBox Pure) | yes | DOS |
| `xbox` | `xbox` | xemu | no (see below) | Microsoft Xbox |

Where a platform has a second EmuDeck collection name (for example "Nintendo Switch - Ryujinx"), the card goes
into whichever of the two already exists in your Steam library, or a new collection with the first name if
neither does.

**Xbox saves aren't synced.** xemu keeps every game's saves inside one virtual hard drive, which can't be split
per game.

## Where saves are looked for

Besides `Emulation/saves/<emulator>` (EmuDeck's folders), each emulator's own save folders are watched, whichever
exist on your PC:

| Emulator | Folders |
|---|---|
| RetroArch | flatpak and native `saves` and `states`; `Emulation/bios/dc` (Flycast's Dreamcast VMU saves) |
| Dolphin | flatpak and native `GC`, `Wii/title` (game saves only, not the whole Wii NAND) and `StateSaves` |
| Ryujinx | Ryubing flatpak, native and portable `bis/user/save` and `bis/user/saveMeta` |
| Azahar | native and flatpak `sdmc` and `states` |
| Cemu | `~/.local/share/Cemu/mlc01/usr/save` |
| DuckStation | `memcards` and `savestates` |
| PCSX2 | native and flatpak `memcards` and `sstates` |
| RPCS3 | `dev_hdd0/home/00000001/savedata` and `savestates` |
| PPSSPP | flatpak and native `PSP/SAVEDATA` and `PSP/PPSSPP_STATE` |
| melonDS | the game's own folder in `roms/nds` (only files named after the game) |

The exact paths are `DEFAULT_ROOTS` in [`saves.py`](../py_modules/romm_deck/saves.py).

## Changing an emulator

Each platform is one line in [`systems.py`](../py_modules/romm_deck/systems.py): its folder, emulator, launcher
script, arguments and file types. Edit that line to use another emulator or core, then reinstall the plugin.
Collections are in `COLLECTIONS` in the same file.
