"""Keeps a Decky Loader plugin store as files on the repository's `store` branch: this project's releases plus
the official Decky store's listing, so a Decky using it as its custom store loses nothing.

Used by scripts/update_decky_store.sh, from two Gitea workflows:
    python3 scripts/decky_store.py add <store folder> <tag> <zip> <owner/repo on Gitea>      (release.yml)
    python3 scripts/decky_store.py build <store folder> <Gitea's public address> <owner/repo on GitHub>
                                                                       (both, after add / on a schedule)

The store itself is served by Gitea (GitHub can't serve a Decky store: see CONTRIBUTING.md), but the handheld
downloads each version from its GitHub release once GitHub has it, and from Gitea's release until then.

Decky's store (Decky settings → General → Plugin Store → Custom) asks for two addresses:
  <store address>            the plugin list: every plugin with its versions, newest first. Each version has the
                             zip's SHA-256 (Decky refuses a zip that doesn't match) and, for ours, its address
                             (official plugins have none: Decky downloads those from the official store by hash)
  <store address>/versions   for update checks (Decky 3.3.1 and newer): {plugin name: [version, hash(, address)]}
They're plugins.json and plugins/versions.json here. A plain file host can't answer both addresses (one is a
folder of the other), so the web server maps them; CONTRIBUTING.md has the Traefik rule.

The store folder holds:
  own.json                   this project's plugins and releases, without addresses (the source of truth),
                             with each version's GitHub zip hash once it's been seen there
  README.md                  what the branch is, for anyone opening it
  official/plugins.json,     the official store's listing as last fetched, used when it can't be reached
  official/versions.json
  plugins.json, plugins/versions.json   what Decky reads, rebuilt by `build`

Addresses are worked out by `build` each time, never stored, so after moving Gitea to another domain the next
build (the scheduled one, at the latest) points every Gitea link at the new one.

If the official store can't be read and there's no copy from before, nothing is written: a store without the
official plugins would take them, and their updates, away from the handheld.
"""
import hashlib
import http.client
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = "https://plugins.deckbrew.xyz/plugins"  # the store Decky uses by default
ASSET = "romm-deck.zip"
ICON = "assets/brand/icon@2x.png"
FIRST_OWN_ID = 100000  # far above the official store's ids, so ours never clash with one of theirs


def _load(path, default):
    """JSON from a file, or `default` when it's missing, unreadable or the wrong shape."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _save(path, data):
    """Write JSON, making the folder if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def add_release(store, tag, zip_path, repository, plugin=None):
    """Record a release of this project in own.json: its version (the tag without its "v"), the zip's SHA-256
    and where it lives (repository and tag). Releasing a version again replaces its entry; earlier versions stay,
    so Decky can still install them. Returns the plugin's entry."""
    plugin = plugin or json.loads((ROOT / "plugin.json").read_text())
    publish = plugin.get("publish", {})
    own_file = Path(store) / "own.json"
    own = _load(own_file, [])
    entry = next((p for p in own if p.get("name") == plugin["name"]), None)
    if entry is None:
        entry = {"name": plugin["name"], "versions": []}
        own.append(entry)
    entry.update({
        "author": plugin.get("author", ""),
        "description": publish.get("description", ""),
        "tags": publish.get("tags", []),
        "repository": repository,
        "asset": ASSET,
        "icon": ICON,
    })
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    release = {"name": version, "tag": tag, "hash": hashlib.sha256(Path(zip_path).read_bytes()).hexdigest(),
               "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    entry["versions"] = [release] + [v for v in entry["versions"] if v.get("name") != version]
    _save(own_file, own)
    return entry


USER_AGENT = "RomM-Deck-store-sync (+https://github.com/soullink9/Decky-RomM_Deck)"  # some hosts refuse Python's default


class NoOfficialListing(Exception):
    """The official store couldn't be reached and there's no copy from before: publishing now would leave every
    official plugin out of the store, and with it their updates."""


def fetch_official(store, url=OFFICIAL):
    """The official store's (list, versions), fetched now and kept in the store folder; the kept copy when the
    official store can't be reached, so a build never drops the official plugins over a passing outage. Raises
    NoOfficialListing when there's neither."""
    folder = Path(store) / "official"
    try:
        listing = _get_json(url)
        versions = _get_json(url + "/versions")
        if not isinstance(listing, list) or not isinstance(versions, dict):
            raise ValueError("unexpected answer")
        _save(folder / "plugins.json", listing)
        _save(folder / "versions.json", versions)
        print(f"Official store: {len(listing)} plugins")
    except (OSError, ValueError, urllib.error.URLError) as e:
        listing, versions = _load(folder / "plugins.json", []), _load(folder / "versions.json", {})
        if not listing:
            raise NoOfficialListing(f"The official store ({url}) couldn't be read: {e}") from None
        print(f"Official store not reached ({e}); using the copy from last time ({len(listing)} plugins)")
    return listing, versions


def _get_json(url):
    """GET a JSON document, the way Decky asks for it."""
    headers = {"X-Decky-Version": "store-sync", "Accept": "application/json", "User-Agent": USER_AGENT}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as reply:
        return json.loads(reply.read())


def _download(url):
    """The bytes at `url`, or None if it can't be fetched (not published yet, or the host is down)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=120) as reply:
            return reply.read()
    except (OSError, ValueError, http.client.HTTPException):  # (URLError is an OSError)
        return None


def _github_copy(version, entry, github_repo, download):
    """The SHA-256 of this version's zip on its GitHub release, or None if GitHub doesn't have it (yet).

    Each version's GitHub zip is downloaded once and its hash kept in own.json ("github_hash"), so the store
    lists exactly the bytes GitHub serves (Decky refuses a zip whose hash doesn't match). GitHub's release
    workflow builds the same commit with the same reproducible build (scripts/build_zip.py), so the hash is
    normally the same as Gitea's, but keeping GitHub's own means a difference could never break an install."""
    if version.get("github_hash"):
        return version["github_hash"]
    data = download(_github_zip(github_repo, version, entry))
    if not data:
        return None
    version["github_hash"] = hashlib.sha256(data).hexdigest()
    return version["github_hash"]


def _github_zip(github_repo, version, entry):
    """Where a version's zip is on GitHub (the release GitHub's workflow publishes when the tag arrives)."""
    return f"https://github.com/{github_repo}/releases/download/{version['tag']}/{entry['asset']}"


def build(store, gitea_url, github_repo=None, official=None, download=_download):
    """Write plugins.json and plugins/versions.json: our plugins first, then the official store's, leaving out
    any official plugin with one of our names.

    Each of our versions is downloaded from GitHub when its GitHub release has the zip (github_repo: owner/repo
    there), and from Gitea's release otherwise: until GitHub's release is published, or if there's no GitHub
    copy. Gitea's links use `gitea_url`, the address the handheld reaches Gitea at. Every build checks again,
    so a version moves to GitHub's link at the next build after its GitHub release appears."""
    store = Path(store)
    official_list, official_versions = official if official is not None else fetch_official(store)
    gitea_url = gitea_url.rstrip("/")
    own = _load(store / "own.json", [])
    names = {p["name"] for p in own}
    used_ids = {p.get("id") for p in official_list}

    listing, versions = [], {}
    next_id = FIRST_OWN_ID
    for entry in own:
        if not entry.get("versions"):
            continue
        while next_id in used_ids:
            next_id += 1
        gitea_base = f"{gitea_url}/{entry['repository']}"
        plugin_versions = []
        for version in entry["versions"]:
            github_hash = _github_copy(version, entry, github_repo, download) if github_repo else None
            if github_hash:
                artifact, sha = _github_zip(github_repo, version, entry), github_hash
            else:
                artifact, sha = f"{gitea_base}/releases/download/{version['tag']}/{entry['asset']}", version["hash"]
            plugin_versions.append({"name": version["name"], "hash": sha, "created": version.get("created"),
                                    "artifact": artifact})
        newest = entry["versions"][0]
        if newest.get("github_hash"):
            image = f"https://raw.githubusercontent.com/{github_repo}/{newest['tag']}/{entry['icon']}"
        else:
            image = f"{gitea_base}/raw/tag/{newest['tag']}/{entry['icon']}"
        listing.append({
            "id": next_id, "name": entry["name"], "author": entry.get("author", ""),
            "description": entry.get("description", ""), "tags": entry.get("tags", []),
            "image_url": image, "visible": True, "versions": plugin_versions,
        })
        newest_listed = plugin_versions[0]
        versions[entry["name"]] = [newest_listed["name"], newest_listed["hash"], newest_listed["artifact"]]
        used_ids.add(next_id)

    listing += [p for p in official_list if p.get("name") not in names]
    versions = {**{k: v for k, v in official_versions.items() if k not in names}, **versions}
    _save(store / "own.json", own)  # with any GitHub hashes found this time, so they're fetched only once
    _save(store / "plugins.json", listing)
    _save(store / "plugins" / "versions.json", versions)
    (store / "README.md").write_text(STORE_README)
    print(f"Store: {len(listing)} plugins, {len(own)} from this repository")
    return listing, versions


STORE_README = """# Decky store

This branch is a Decky Loader plugin store, written by the release workflows (scripts/decky_store.py on the main
branch); don't edit it by hand. It lists RomM Deck's releases, downloaded from GitHub (or from Gitea until a
release is on GitHub), followed by the official Decky store's plugins.

- `plugins.json`: the plugin list Decky shows. `plugins/versions.json`: what Decky checks for updates.
- `own.json`: RomM Deck's releases. `official/`: the official store's listing as last fetched.

Decky reads it through a web address that answers both `<store>` and `<store>/versions`; CONTRIBUTING.md on the
main branch explains how to serve it.
"""


def gitea_public_url(server, repository, token):
    """Gitea's public address (its ROOT_URL), asked of Gitea itself, or None if it can't be asked.

    A runner registered with Gitea's internal address (http://gitea-server:3000, say) is told that address,
    which the handheld can't reach. Gitea's API gives every repository's web address built from ROOT_URL, the
    address Gitea is published at, so the store's Gitea links follow it, also after a move to a new domain,
    without a variable to keep up to date."""
    request = urllib.request.Request(f"{server.rstrip('/')}/api/v1/repos/{repository}",
                                     headers={"Authorization": f"token {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:
            web_address = json.loads(reply.read()).get("html_url", "")
    except (OSError, ValueError, http.client.HTTPException):
        return None
    suffix = "/" + repository
    if not web_address.lower().endswith(suffix.lower()):
        return None
    return web_address[: -len(suffix)]


def main():
    """`add` a release, `build` the files Decky reads, or print Gitea's `public-url`."""
    command, args = sys.argv[1], sys.argv[2:]
    if command == "add":
        store, tag, zip_path, repository = args
        entry = add_release(store, tag, zip_path, repository)
        print(f"Added {entry['name']} {tag} ({len(entry['versions'])} version(s))")
    elif command == "build":
        store, gitea_url = args[0], args[1]
        github_repo = args[2] if len(args) > 2 else None
        try:
            build(store, gitea_url, github_repo)
        except NoOfficialListing as e:
            sys.exit(f"{e}\nThe store was left as it was: without the official listing, a Decky using it would lose "
                     "every official plugin and their updates. It's tried again at the next refresh.")
    elif command == "public-url":
        server, repository, token = args[0], args[1], os.environ.get("TOKEN", "")
        address = gitea_public_url(server, repository, token)
        if not address:
            sys.exit(f"Couldn't ask {server} for its public address")
        print(address)
    else:
        sys.exit(f"unknown command {command}: use add, build or public-url")


if __name__ == "__main__":
    main()
