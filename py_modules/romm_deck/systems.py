"""RomM platform -> EmuDeck folder, emulator and launch command.

Launch commands mirror EmuDeck's own Steam ROM Manager parsers, and they all go
through EmuDeck's launcher scripts (Emulation/tools/launchers), so a game starts
the same way your existing cards do.

To change an emulator, edit the line for that platform. Keys are RomM platform
slugs. Platforms not listed here can still be downloaded (into roms/<folder name
in RomM>), they just don't get a Steam card.

Fields:
  folder    EmuDeck roms sub-folder
  emu       EmuDeck saves sub-folder for that emulator (Emulation/saves/<emu>)
  launcher  script in Emulation/tools/launchers
  args      arguments; {rom} is the game file, {cores} the RetroArch cores folder
  exts      file types the emulator opens, in order of preference
"""
from .config import HOME

CORES = HOME / ".var/app/org.libretro.RetroArch/config/retroarch/cores"
NO_VSYNC = {"vblank_mode": "0"}  # EmuDeck's parsers set this for Dolphin and Cemu


def ra(folder, core, exts):
    """A system run by a RetroArch core."""
    return dict(folder=folder, emu="retroarch", launcher="retroarch.sh",
                args=["-L", "{cores}/" + core + "_libretro.so", "{rom}"], exts=exts.split(),
                env={}, sync=True)


def app(folder, emu, launcher, args, exts, env=None, sync=True):
    """A system run by a standalone emulator."""
    return dict(folder=folder, emu=emu, launcher=launcher, args=args,
                exts=exts.split(), env=env or {}, sync=sync)


SYSTEMS = {
    # Nintendo
    "nes":        ra("nes", "mesen", "nes fds unf unif zip 7z"),
    "famicom":    ra("famicom", "mesen", "nes fds zip 7z"),
    "fds":        ra("fds", "mesen", "fds zip 7z"),
    "snes":       ra("snes", "snes9x", "sfc smc fig swc bs zip 7z"),
    "sfam":       ra("sfc", "snes9x", "sfc smc fig swc bs zip 7z"),
    "n64":        ra("n64", "mupen64plus_next", "z64 n64 v64 ndd bin zip 7z"),
    "gb":         ra("gb", "gambatte", "gb dmg zip 7z"),
    "gbc":        ra("gbc", "gambatte", "gbc gb zip 7z"),
    "gba":        ra("gba", "mgba", "gba zip 7z"),
    "virtualboy": ra("virtualboy", "mednafen_vb", "vb vboy bin zip 7z"),
    "nds":    app("nds", "melonds", "melonds.sh", ["{rom}", "-f"], "nds dsi app"),
    "3ds":    app("n3ds", "azahar", "azahar.sh", ["{rom}"], "3ds cci cia cxi 3dsx app axf elf"),
    "ngc":    app("gc", "dolphin", "dolphin-emu.sh", ["-b", "-e", "{rom}"], "m3u rvz iso gcm gcz ciso wia dol elf", NO_VSYNC),
    "wii":    app("wii", "dolphin", "dolphin-emu.sh", ["-b", "-e", "{rom}"], "m3u rvz wbfs iso wia gcz ciso wad dol elf", NO_VSYNC),
    "wiiu":   app("wiiu/roms", "Cemu", "cemu.sh", ["-f", "-g", "{rom}"], "wua wud wux rpx elf", NO_VSYNC),
    "switch": app("switch", "ryujinx", "ryujinx.sh", ["--fullscreen", "{rom}"], "nsp xci nsz xcz nca nro nso"),
    # PlayStation
    "psx": app("psx", "duckstation", "duckstation.sh", ["-batch", "-fullscreen", "-nogui", "{rom}"], "m3u chd cue pbp iso img ecm mds"),
    "ps2": app("ps2", "pcsx2", "pcsx2-qt.sh", ["-batch", "-fullscreen", "-nogui", "{rom}"], "chd iso cso bin gz img dump"),
    "ps3": app("ps3", "rpcs3", "rpcs3.sh", ["--no-gui", "{rom}"], "eboot.bin iso"),
    "psp": app("psp", "ppsspp", "ppsspp.sh", ["-f", "-g", "{rom}"], "iso cso chd pbp elf prx"),
    # Sega
    "sg1000":   ra("sg-1000", "genesis_plus_gx", "sg bin zip 7z"),
    "sms":      ra("mastersystem", "genesis_plus_gx", "sms zip 7z"),
    "genesis":  ra("genesis", "genesis_plus_gx", "md gen smd bin zip 7z"),
    "gamegear": ra("gamegear", "genesis_plus_gx", "gg zip 7z"),
    "segacd":   ra("segacd", "genesis_plus_gx", "m3u chd cue iso"),
    "sega32":   ra("sega32x", "picodrive", "32x bin zip 7z"),
    "saturn":   ra("saturn", "mednafen_saturn", "m3u chd cue iso"),
    "dc":       ra("dreamcast", "flycast", "m3u chd gdi cdi cue"),
    # Everything else
    "tg16":                 ra("pcengine", "mednafen_pce", "pce bin zip 7z"),
    "turbografx-cd":        ra("pcenginecd", "mednafen_pce", "m3u chd cue ccd iso"),
    "atari2600":            ra("atari2600", "stella", "a26 bin zip 7z"),
    "lynx":                 ra("atarilynx", "mednafen_lynx", "lnx zip 7z"),
    "neo-geo-pocket":       ra("ngp", "mednafen_ngp", "ngp zip 7z"),
    "neo-geo-pocket-color": ra("ngpc", "mednafen_ngp", "ngc ngp zip 7z"),
    "wonderswan":           ra("wonderswan", "mednafen_wswan", "ws zip 7z"),
    "wonderswan-color":     ra("wonderswancolor", "mednafen_wswan", "wsc zip 7z"),
    "arcade":               ra("arcade", "mame", "zip 7z"),
    "dos":                  ra("dos", "dosbox_pure", "zip 7z dosz"),
    # xemu keeps every save in one big virtual hard drive, so it is not synced
    "xbox": app("xbox", "xemu", "xemu-emu.sh", ["-full-screen", "-dvd_path", "{rom}"], "iso", sync=False),
}


# Steam collection each platform's cards go in, named like EmuDeck's Steam ROM Manager parsers so
# they join the collections you already have. The first name that already exists in Steam is used;
# if none does, the first one is created. Platforms not listed use RomM's platform name.
COLLECTIONS = {
    "nes": ["Nintendo Entertainment System"],
    "famicom": ["Nintendo Entertainment System"],
    "fds": ["Nintendo Entertainment System"],
    "snes": ["Nintendo SNES (Super Nintendo)"],
    "sfam": ["Nintendo SNES (Super Nintendo)"],
    "n64": ["Nintendo 64"],
    "gb": ["Nintendo Game Boy"],
    "gbc": ["Nintendo Game Boy Color"],
    "gba": ["Nintendo Game Boy Advance"],
    "virtualboy": ["Nintendo Virtual Boy"],
    "nds": ["Nintendo DS", "Nintendo DS - melonDS (Standalone)"],
    "3ds": ["Nintendo 3DS", "Nintendo 3DS - Azahar (Standalone)"],
    "ngc": ["Nintendo GameCube"],
    "wii": ["Nintendo Wii"],
    "wiiu": ["Nintendo Wii U", "Nintendo Wii U - Cemu Native"],
    "switch": ["Nintendo Switch", "Nintendo Switch - Ryujinx"],
    "psx": ["Sony PlayStation"],
    "ps2": ["Sony PlayStation 2"],
    "ps3": ["Sony PlayStation 3"],
    "psp": ["Sony PlayStation Portable"],
    "sg1000": ["Sega SG-1000"],
    "sms": ["Sega Master System"],
    "genesis": ["Sega Genesis/Mega Drive"],
    "gamegear": ["Sega Game Gear"],
    "segacd": ["Sega CD/Mega CD"],
    "sega32": ["Sega 32X"],
    "saturn": ["Sega Saturn"],
    "dc": ["Sega Dreamcast", "Sega Dreamcast - Flycast (Standalone)"],
    "tg16": ["NEC PC Engine/TurboGrafx 16"],
    "turbografx-cd": ["NEC PC Engine/TurboGrafx 16 CD"],
    "atari2600": ["Atari 2600"],
    "lynx": ["Atari Lynx"],
    "neo-geo-pocket": ["SNK Neo Geo Pocket"],
    "neo-geo-pocket-color": ["SNK Neo Geo Pocket Color"],
    "wonderswan": ["Bandai WonderSwan"],
    "wonderswan-color": ["Bandai WonderSwan Color"],
    "arcade": ["Arcade"],
    "dos": ["DOS"],
    "xbox": ["Microsoft Xbox"],
}


# Emulators that keep saves next to the game file (in Emulation/roms) instead of their own folder
SAVES_NEXT_TO_GAME = {"melonds"}

# Every file type that is a game, never a save: never claimed as a save, never deleted as one
GAME_EXTS = {e for s in SYSTEMS.values() for e in s["exts"]} | {
    "zip", "7z", "rar", "chd", "iso", "cue", "bin", "img", "m3u", "gdi", "cdi", "cso", "pbp", "rvz", "wbfs",
    "wia", "gcz", "nsp", "xci", "nsz", "xcz", "3ds", "cia", "nds", "gba", "gbc", "gb", "sfc", "smc", "nes",
    "n64", "z64", "v64", "md", "gen", "sms", "gg", "pce", "elf", "rpx", "wud", "wux", "wua", "pkg", "vpk",
}


def for_rom(rom):
    """The SYSTEMS entry for a RomM rom, or None if we only know how to download it."""
    return SYSTEMS.get(rom["platform_slug"]) or SYSTEMS.get(rom["platform_fs_slug"])
