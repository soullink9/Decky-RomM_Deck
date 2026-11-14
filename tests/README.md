# Tests

Run everything from the repository root with `npm test` (after `npm install` once). Each suite is a plain
script that prints `PASS` or `FAIL` per check and exits non-zero if anything failed.

| Script | What it checks |
|---|---|
| `test_plugin.py` | The whole backend, through the real `Plugin` class in `main.py` |
| `test_motion.py` | The motion sensor readers, calibration and the DSU motion server |
| `test_release.py` | The release scripts in `scripts/`: notes, zip check, the Decky store (merged with a fake official store), publishing to a fake Gitea server |
| `test_cards.mjs` | Making and taking over Steam cards (`src/cards.ts`) |
| `test_current.mjs` | Which game the panel opens on (`src/current.ts`) |

Helpers:

- `mock_romm.py`: a fake RomM server with a small library, collections, saves, states, firmware and the
  signed-in user. `test_plugin.py` starts it on `127.0.0.1:8765`.
- `dsu_client.py`: plays an emulator's part, asking the motion server for one reading.
- `load_source.mjs`: builds one `src/` module with esbuild for the frontend tests.
- `fixtures/`: short excerpts of EmuDeck's default emulator settings (Cemu, Azahar, Dolphin) that the controller
  presets change and must put back exactly.

`test_plugin.py` builds a throwaway fake home folder (EmuDeck's layout, fake emulators that write save files, a
fake `systemctl`), installs the plugin into it as Decky would, and runs downloads, launches, syncs, conflicts,
removals and presets, checking the files on disk at each step. For the Wii preset's in-game check it starts
stand-in processes named like Dolphin and Steam, holding a fake Wii Remote sensor open. The folder is deleted
afterwards, or kept and printed when something fails.

What this does and does not prove:

- It exercises the plugin's own code paths, including every safety check around saves.
- It does **not** run real Steam, Decky Loader or emulators, so it can't catch a change in Steam's internals or an
  emulator's behaviour. Try changes on a real handheld too.
