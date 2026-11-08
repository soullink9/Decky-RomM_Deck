# Controller Presets

A preset changes a few emulator settings for the length of a game and puts them back when it closes. Presets
are per platform, **off** until you turn one on with the switch on any of that platform's game pages.

## Ally motion (ROG Ally and Xbox Ally)

**Switch** (Ryujinx), **Wii U** (Cemu) and **3DS** (Azahar) on a ROG Ally, ROG Ally X or Xbox Ally (X): motion
and tilt from the handheld's own sensor, for motion puzzles, gyro aiming and the like.

**Why it's needed.** Emulators read motion from a "DSU" motion server at `127.0.0.1:26760`. EmuDeck's motion
server only recognises a real Steam Deck, so it can't see the Ally's sensor under InputPlumber (Bazzite's
controller software). Steam Input's own gyro only moves the camera like a stick; it doesn't give the game real
motion data. So the plugin reads the sensor itself, either straight from the kernel or, when InputPlumber
0.82 or newer is using the sensor, from InputPlumber's virtual Steam Deck controller, and serves it while the
game runs. EmuDeck already points Cemu and Azahar at that address; the preset only sets it where it isn't.
Nothing is downloaded or installed.

### Calibrating

The sensor's axes differ between models, so calibrate once before the first game:

1. Turn the preset on, then press **Calibrate motion** on the game's page.
2. Lay the handheld **flat on a table, screen up**, and let go.
3. When asked, **stand it up on its bottom edge, screen facing you**, and hold still.

**Recalibrate motion** redoes it, for example if tilting goes the wrong way. If the plugin starts reading the
sensor a different way (after an InputPlumber update, say), the next game's popup asks you to calibrate again.

## Use my real Wii Remotes (any device)

**Wii** (Dolphin): all four players use real Wii Remotes instead of emulated ones, and Dolphin keeps looking
for them, so pressing **1+2** on a remote connects it at any time during the game.

RomM Deck tells Dolphin this when it starts the game, on Dolphin's command line, and doesn't change Dolphin's
settings files. That's because EmuDeck's launcher sets every Wii Remote back to emulated in those files just
before Dolphin starts (its controller AutoMap). Settings given on the command line win over the files and last
only until Dolphin closes, so there's nothing to put back.

Remotes can connect over Bluetooth or through a USB Wii Remote sensor such as a Mayflash DolphinBar (on the
handheld or its dock). A DolphinBar has to be in **mode 4**, its Wii Remote mode. When the game starts, the popup
says whether Dolphin can use a sensor on USB; [Troubleshooting](Troubleshooting.md) explains each message.

## How your settings are kept safe

- Settings given on the emulator's command line (the Wii preset) last only until it closes; Dolphin never saves
  them.
- Every setting a preset will change in a file is recorded first, so it's put back after the game, also after a
  crash or a power-off (at the next launch of any game).
- A setting is only put back if it still has the preset's value: anything you change in the emulator during the
  game is kept.
- Only the one line changes in each settings file; the rest of the file stays exactly as it was.
- Turning a preset off puts everything back immediately.
- If EmuDeck's own motion server is installed and running, it's paused for the game (it would hold the motion
  port) and started again afterwards.

The game page shows how the preset went for the last game of that platform, and a popup says when it goes on
and off.

## Known limitations

- **Gyro aiming can feel slow or reversed** in some games. Tilt works, but the way the handheld's orientation is
  reported for aiming is still being worked on. If a game lets you turn off motion aiming, Steam Input's gyro
  (as a joystick or mouse) is a good alternative for the camera meanwhile.
- The Ally motion presets are offered only on ASUS ROG Ally and Xbox Ally models.
