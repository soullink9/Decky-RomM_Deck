# Contributing

Thanks for helping. This page is for anyone changing the code: the rules it keeps, how to check a change, and
how to release one. [ARCHITECTURE.md](ARCHITECTURE.md) explains how the plugin is built and how data flows
through it. Start there if you're new to the code.

## Ground rules

These two come before any feature.

- **Game data is never lost.** Nothing deletes a save, a save state or a game unless RomM holds an identical
  copy first. Any change to an emulator's settings is recorded before it's made, so it can be put back, also
  after a crash or a power loss. A change that could put a save at risk needs a test showing it doesn't.
- **Nobody has to type a command.** Installing, removing, turning a feature on or off and recovering from a
  crash all happen from the Quick Access panel. Turning something off puts the system back exactly as it was.

And for the code:

- **No dependencies.** The backend uses only Python's standard library: Decky runs it on its own bundled Python,
  where packages can't be installed. The frontend uses only what Decky Loader and Steam provide, plus esbuild
  for the build.
- **Python 3.10.** Decky's bundled Python is older than the newest releases, and newer-only syntax stops the
  backend from loading at all.
- **Steam's internals are fragile.** Anything that patches Steam's UI (`src/steampage.tsx`) falls back to
  Steam's own behaviour on any error, and is fully undone when the plugin unloads.

## How the repository is laid out

```
src/                     the frontend (TypeScript): panel, Steam cards, Steam game pages
main.py                  the backend's entry point, the class Decky loads
py_modules/romm_deck/    the backend's modules, shared with the game launcher
bin/                     the game launcher every card runs, and the motion server
assets/brand/            the plugin's icon (icon.svg, and the PNGs exported from it)
docs/                    the documentation pages (the README is the front page)
tests/                   the tests, a fake RomM server and emulator config fixtures
scripts/                 release helpers both CI systems use: version check and notes, zip check, Gitea publish
.gitea/                  the test and release workflows for the Gitea runner (the main copy)
.github/                 the bug-report form and GitHub's release workflow (the public copy)
```

[ARCHITECTURE.md](ARCHITECTURE.md#repository-layout) describes every file.

## Checking a change

You need Node.js and Python 3.10 or newer.

| Command | When |
|---|---|
| `npm install` | once (installs esbuild) |
| `npm run build` | builds `dist/index.js` |
| `npm test` | every change: runs every suite below |
| `python3.10 tests/test_plugin.py` | every backend change, on Decky's Python version |
| `npm run package` | builds `romm-deck.zip`, to try a change on a real handheld, and checks Decky can install it |

`npm test` runs:

- `tests/test_plugin.py`: the whole backend against a fake RomM server (`tests/mock_romm.py`), in a throwaway
  fake home folder with a fake EmuDeck install and fake emulators. It downloads, launches, syncs, removes and
  restores, and checks the files on disk at each step.
- `tests/test_motion.py`: the motion sensor, calibration and the motion server.
- `tests/test_release.py`: the release scripts: the version check and notes, the Decky install check, and
  publishing on Gitea against a fake Gitea server.
- `tests/test_cards.mjs`, `tests/test_current.mjs`: the frontend's Steam card handling, against a stand-in for
  Steam.

On Gitea, every push runs the same suites (`.gitea/workflows/test.yml`): the backend on Python 3.10, the frontend
and the zip on Node 22.

The tests can't prove the plugin works inside real Steam and Decky, so try a change on a handheld too.
See [tests/README.md](tests/README.md).

## Standards for every change

- **Readable over clever.** Write code a newcomer can follow on the first read. Prefer a few plain lines with
  a named variable to a dense one-liner, a nested conditional expression, or a trick that needs a comment to
  decode.
- **Comment the why.** Every function and class has a docstring or comment. Comments explain why the code does
  something non-obvious (a Steam quirk, an emulator's file format, a safety check), not what each line does.
- **Keep names consistent.** Follow the names already used: the same words for the same things, `snake_case`
  for Python, `camelCase` for TypeScript functions and `PascalCase` for components and types. A RomM game is a
  "rom" with a `rom_id` in the backend and a `romId` in the frontend.
- **Keep the docs in step.** When you change a function, class or behaviour, update its docstring, its comments,
  and the pages under `docs/` (and ARCHITECTURE.md) that describe it, in the same commit.
- **Keep the tests green.** Every change keeps existing behaviour and passes every test. When you fix a bug, add
  the situation that caused it to the tests so it stays fixed.
- **No new dependencies without approval.** Don't add a library (to `package.json`, the backend or the tests)
  without asking in an issue first.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): a type, an optional scope, then a short
summary in the imperative.

```
feat(steampage): show RomM's screenshots on Steam game pages
fix(saves): keep both copies when a save changes in both places
refactor(library): split matching out of find_existing
docs: describe the motion calibration steps
test(saves): cover a sync that's cut off halfway
chore: set version to 0.5.1-beta
```

Use the module's name as the scope when a change touches one part, and leave the scope off when it touches the
repository as a whole. One logical change per commit.

## Releasing

1. Change the version in `package.json` and `py_modules/romm_deck/__init__.py`. They must match (a test checks
   this). The project is in beta (`0.x`); version 1.0 is the maintainer's decision only.
2. Add the release to [CHANGELOG.md](CHANGELOG.md), under a heading `## X.Y.Z-beta (date)`.
3. Run `npm test`, and `python3.10 tests/test_plugin.py`.
4. Commit and push to Gitea, then publish with Gitea's **Release** workflow (`.gitea/workflows/release.yml`),
   either way:
   - **Actions → Release → Run workflow**, and enter the version without the `v` (for example `0.5.2`). It
     creates the tag `v0.5.2` on the commit it releases.
   - or push a version tag: `git tag v0.5.2 && git push origin v0.5.2`.

   The workflow checks the version matches `package.json`, the backend and `CHANGELOG.md`, runs every test (the
   backend on Python 3.10), builds `romm-deck.zip` and checks Decky can install it (`scripts/check_package.py`,
   the same rules Decky's installer applies), and publishes the release on Gitea with the zip and that version's
   changelog section as its notes (`scripts/publish_gitea_release.py`). A version with a suffix (`-beta`) is
   published as a pre-release. If any check fails, nothing is published. Running it again for the same version
   updates the release and replaces its zip.

5. Gitea's push mirror then sends the commits and the new tag to GitHub, where the tag starts GitHub's own
   **Release** workflow (`.github/workflows/release.yml`), which runs the same checks and publishes the same
   release there. That's the copy people install from, so the notes always link to GitHub. If GitHub is down,
   the mirror catches up later; the Gitea release is already done.

The Gitea workflows use no actions (`actions/checkout` and the like download from GitHub): each job runs in a
plain image from Docker Hub (`python:3.10-bookworm`, `node:22-bookworm`) and fetches the code from Gitea with git,
so testing and releasing keep working when GitHub can't be reached. When the runner's jobs can't reach Gitea at its
public address (a runner on the same Docker network as Gitea, say), set an Actions variable `GITEA_INTERNAL_URL`
to the address they can reach (`http://gitea-server:3000`); both workflows and the publish script use it.

## A Decky store on Gitea

Each release made on Gitea also goes into the repository's `store` branch (`scripts/decky_store.py`):
`plugins.json`, the plugin list with every version's zip address and SHA-256, and `plugins/versions.json`, what
Decky 3.3.1 and newer use to check for updates. Decky can use it as its custom store: Decky settings → General →
Plugin Store → **Custom**, and the store address below.

Decky asks for `<store address>` and `<store address>/versions`. A plain file host can't answer both (one would
be a folder of the other), so the web server in front of Gitea maps them to the two files. With Traefik v3, add
to Gitea's container labels (change the host, owner and repository to yours; `$$` is how a compose file writes `$`):

```yaml
      - "traefik.http.routers.decky-store.rule=Host(`gitea.example.com`) && PathRegexp(`^/decky-store/plugins(/versions)?$$`)"
      - "traefik.http.routers.decky-store.entrypoints=https"
      - "traefik.http.routers.decky-store.tls.certresolver=letsencrypt"
      - "traefik.http.routers.decky-store.service=gitea"
      - "traefik.http.routers.decky-store.middlewares=decky-store-files,decky-store-cors"
      - "traefik.http.middlewares.decky-store-files.replacepathregex.regex=^/decky-store/plugins(/versions)?$$"
      - "traefik.http.middlewares.decky-store-files.replacepathregex.replacement=/soullink9/decky-romm_deck/raw/branch/store/plugins$${1}.json"
      - "traefik.http.middlewares.decky-store-cors.headers.accesscontrolalloworiginlist=*"
      - "traefik.http.middlewares.decky-store-cors.headers.accesscontrolallowmethods=GET,OPTIONS"
      - "traefik.http.middlewares.decky-store-cors.headers.accesscontrolallowheaders=X-Decky-Version"
```

The store address is then `https://gitea.example.com/decky-store/plugins`. Decky reads the store from Steam's
interface, which needs the CORS headers; downloads come straight from the Gitea release. The repository has to be
readable without signing in.

Decky has one store at a time: with the custom store chosen, it lists and updates only what's in it.

## Reporting bugs

[Open an issue](https://github.com/soullink9/Decky-RomM_Deck/issues/new/choose) and fill in the form. Please
follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing you agree that your contribution is licensed under the project's
[BSD 3-Clause License](LICENSE).
