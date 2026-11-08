"""Keeps a Decky Loader plugin store as files on the repository's `store` branch: this project's releases plus
the official Decky store's listing, so a Decky using it as its custom store loses nothing.

Used by scripts/update_decky_store.sh, from two Gitea workflows:
    python3 scripts/decky_store.py add <store folder> <tag> <zip> <owner/repo>   (release.yml, after a release)
    python3 scripts/decky_store.py build <store folder> <Gitea's public address> (both, after add / on a schedule)

Decky's store (Decky settings → General → Plugin Store → Custom) asks for two addresses:
  <store address>            the plugin list: every plugin with its versions, newest first. Each version has the
                             zip's SHA-256 (Decky refuses a zip that doesn't match) and, for ours, its address
                             (official plugins have none: Decky downloads those from the official store by hash)
  <store address>/versions   for update checks (Decky 3.3.1 and newer): {plugin name: [version, hash(, address)]}
They're plugins.json and plugins/versions.json here. A plain file host can't answer both addresses (one is a
folder of the other), so the web server maps them; CONTRIBUTING.md has the Traefik rule.

The store folder holds:
  own.json                   this project's plugins and releases, without addresses (the source of truth)
  official/plugins.json,     the official store's listing as last fetched, used when it can't be reached
  official/versions.json
  plugins.json, plugins/versions.json   what Decky reads, rebuilt by `build`

Addresses are worked out by `build` from Gitea's public address each time, never stored, so after moving Gitea
to another domain the next build (the scheduled one, at the latest) points every release at the new one.
"""
import hashlib
import json
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


def fetch_official(store, url=OFFICIAL):
    """The official store's (list, versions), fetched now and kept in the store folder; the kept copy when the
    official store can't be reached, so a build never drops the official plugins over a passing outage."""
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
        print(f"Official store not reached ({e}); using the copy from last time ({len(listing)} plugins)")
    return listing, versions


def _get_json(url):
    """GET a JSON document, the way Decky asks for it."""
    request = urllib.request.Request(url, headers={"X-Decky-Version": "store-sync", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        return json.loads(reply.read())


def build(store, public_url, official=None):
    """Write plugins.json and plugins/versions.json: our plugins first (with download and icon addresses on
    Gitea's public address), then the official store's, leaving out any official plugin with one of our names."""
    store = Path(store)
    official_list, official_versions = official if official is not None else fetch_official(store)
    public_url = public_url.rstrip("/")
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
        base = f"{public_url}/{entry['repository']}"
        newest = entry["versions"][0]
        plugin_versions = [{"name": v["name"], "hash": v["hash"], "created": v.get("created"),
                            "artifact": f"{base}/releases/download/{v['tag']}/{entry['asset']}"}
                           for v in entry["versions"]]
        listing.append({
            "id": next_id, "name": entry["name"], "author": entry.get("author", ""),
            "description": entry.get("description", ""), "tags": entry.get("tags", []),
            "image_url": f"{base}/raw/tag/{newest['tag']}/{entry['icon']}", "visible": True,
            "versions": plugin_versions,
        })
        versions[entry["name"]] = [newest["name"], newest["hash"], plugin_versions[0]["artifact"]]
        used_ids.add(next_id)

    listing += [p for p in official_list if p.get("name") not in names]
    versions = {**{k: v for k, v in official_versions.items() if k not in names}, **versions}
    _save(store / "plugins.json", listing)
    _save(store / "plugins" / "versions.json", versions)
    print(f"Store: {len(listing)} plugins, {len(own)} from this repository")
    return listing, versions


def main():
    """`add` a release, or `build` the files Decky reads."""
    command, args = sys.argv[1], sys.argv[2:]
    if command == "add":
        store, tag, zip_path, repository = args
        entry = add_release(store, tag, zip_path, repository)
        print(f"Added {entry['name']} {tag} ({len(entry['versions'])} version(s))")
    elif command == "build":
        store, public_url = args
        build(store, public_url)
    else:
        sys.exit(f"unknown command {command}: use add or build")


if __name__ == "__main__":
    main()
