# Contributing to RomM Deck

Thanks for taking a look. RomM Deck is a small personal project, maintained by one person, so the
rules below are mostly about keeping it safe for people's saves and easy to read.

## The two promises the plugin makes

Every change has to keep these. They come before features.

1. **Game data is never lost.** Nothing deletes a save, a save state or a game unless RomM holds an
   identical copy first. Any change to an emulator's settings is recorded before it's made, so it can
   be put back, including after a crash or power loss. If a change could put a save at risk, it needs
   a test that shows it doesn't.
2. **Nobody has to type a command.** Installing, removing, turning a feature on or off, and recovering
   from a crash all happen from the Quick Access panel. Turning something off puts the system back
   exactly as it was.

## Reporting a problem

Open an issue with:

- your handheld, OS (Bazzite, SteamOS…), Decky Loader version and RomM version
- what you did, what you expected, and what happened
- the logs, if they're relevant: Decky's log for RomM Deck, plus `~/homebrew/logs/romm-deck/launch.log`
  (game launches) and `removed.log` (every file the plugin has deleted)

Please remove your RomM address and token from anything you paste.

## Setting up

You need Node.js (for the frontend build) and Python 3.10 or newer. Decky Loader runs the backend on its
own bundled Python, which is older than the newest releases, so the backend must work on 3.10.

```sh
npm install        # installs esbuild, the only dependency
npm run build      # builds dist/index.js
npm test           # runs every test (see below)
npm run package    # builds romm-deck.zip for Decky's "Install plugin from ZIP"
```

[ARCHITECTURE.md](ARCHITECTURE.md) explains how the pieces fit together. Read it first.

## Tests

`npm test` runs:

- `tests/test_plugin.py`: the whole backend against a fake RomM server (`tests/mock_romm.py`) in a
  throwaway fake home folder with a fake EmuDeck install. It downloads, launches, syncs, removes and
  restores, and checks the files on disk at each step.
- `tests/test_motion.py`: the motion sensor, calibration and the motion server.
- `tests/test_cards.mjs`, `tests/test_current.mjs`: the frontend's Steam card handling, against a
  stand-in for Steam.

All of them must pass before a change is merged. Run the Python tests on Python 3.10 as well as
your usual version: Decky's bundled Python is older, and newer-only syntax stops the backend from
loading at all.

## Code standards

- **Readability over cleverness.** Write code the next person can follow without running it. No dense
  one-liners or tricks that save a line at the cost of a minute's thought.
- **Comment the why.** Every function and class has a docstring or comment. Explain the reason
  behind anything non-obvious (a Steam quirk, an emulator's file format, a safety check), not a
  restatement of the code.
- **Keep docs in step with code.** When you change a function, update its comment, and update the
  README or ARCHITECTURE.md in the same commit if they describe it.
- **Consistent names.** Python uses `snake_case`, TypeScript uses `camelCase` for functions and
  `PascalCase` for components and types. A thing has one name everywhere (for example a RomM game is
  a "rom" with a `rom_id` in the backend and a `romId` in the frontend).
- **No new dependencies** without the maintainer's agreement. The backend uses only Python's standard
  library (Decky's Python can't install packages), and the frontend uses only what Decky Loader provides
  plus esbuild for the build.
- **Steam internals are fragile.** Anything that patches Steam's UI (see `src/steampage.tsx`) must fall
  back to Steam's own behaviour on any error, and must be fully undone when the plugin unloads.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: show RomM's screenshots on Steam game pages
fix: keep the panel on the current game after leaving a page
refactor: split save matching out of sync()
docs: describe the motion calibration steps
test: cover a save sync that's cut off halfway
chore: bump version to 0.5.1-beta
```

One logical change per commit.

## Versions

- The project is in beta (`0.x`). Version 1.0 is decided by the maintainer only.
- The version lives in `package.json` and `py_modules/romm_deck/__init__.py`. They must always match
  (a test checks this). Bump both in the same commit.
- Releases are tagged `vX.Y.Z-beta`, and every release has an entry in [CHANGELOG.md](CHANGELOG.md).

## License

By contributing you agree that your contribution is licensed under the project's
[BSD 3-Clause License](LICENSE).
