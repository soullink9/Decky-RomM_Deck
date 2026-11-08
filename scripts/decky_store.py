"""Adds a release to a Decky Loader plugin store kept as files (the repository's `store` branch).

Used by .gitea/workflows/release.yml after each release:
    python3 scripts/decky_store.py <store folder> <version> <zip> <zip's download address> <icon's address>

Decky's store (Decky settings → General → Plugin Store → Custom, with the store's address) asks for two things:
  <store address>            the plugin list: every plugin with its versions, newest first, each version
                             with the zip's SHA-256 (Decky refuses a zip that doesn't match) and its address
  <store address>/versions   for update checks (Decky 3.3.1 and newer): {plugin name: [version, hash, address]}
These are kept as plugins.json and plugins/versions.json. A plain file host can't answer both addresses (one
is a folder of the other), so the web server maps them; CONTRIBUTING.md has the Traefik rule.

The plugin's name, author, description and tags come from plugin.json. The name must be the one in plugin.json:
Decky matches store entries to installed plugins by it. Releasing a version again replaces that version's entry,
and every earlier version stays listed, so Decky can still install an older one.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_list(path):
    """The store's plugin list, or [] for a new store."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def add_release(store, version, zip_path, artifact, image_url, plugin=None):
    """Put `version` (the zip at `zip_path`, downloadable from `artifact`) at the top of the plugin's versions,
    and write both store files. Returns the plugin's entry."""
    plugin = plugin or json.loads((ROOT / "plugin.json").read_text())
    publish = plugin.get("publish", {})
    store = Path(store)
    plugins = load_list(store / "plugins.json")
    entry = next((p for p in plugins if p.get("name") == plugin["name"]), None)
    if entry is None:
        entry = {"id": max([p.get("id", 0) for p in plugins] + [0]) + 1, "name": plugin["name"], "versions": []}
        plugins.append(entry)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry.update({
        "author": plugin.get("author", ""),
        "description": publish.get("description", ""),
        "tags": publish.get("tags", []),
        "image_url": image_url,
        "visible": True,
        "updated": now,
    })
    release = {"name": version, "hash": hashlib.sha256(Path(zip_path).read_bytes()).hexdigest(),
               "artifact": artifact, "created": now}
    entry["versions"] = [release] + [v for v in entry.get("versions", []) if v.get("name") != version]

    plugins.sort(key=lambda p: p.get("name", "").lower())
    (store / "plugins").mkdir(parents=True, exist_ok=True)
    (store / "plugins.json").write_text(json.dumps(plugins, indent=2) + "\n")
    newest = {p["name"]: [p["versions"][0]["name"], p["versions"][0]["hash"], p["versions"][0]["artifact"]]
              for p in plugins if p.get("versions")}
    (store / "plugins" / "versions.json").write_text(json.dumps(newest, indent=2) + "\n")
    return entry


def main():
    """Read the arguments and update the store folder."""
    store, version, zip_path, artifact, image_url = sys.argv[1:6]
    entry = add_release(store, version, zip_path, artifact, image_url)
    print(f"Store: {entry['name']} {version} ({len(entry['versions'])} version(s) listed)")


if __name__ == "__main__":
    main()
