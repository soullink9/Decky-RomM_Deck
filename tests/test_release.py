"""Release scripts: the version check and notes (scripts/release_notes.py), the Decky install check
(scripts/check_package.py), and publishing on Gitea (scripts/publish_gitea_release.py) against a fake Gitea
server. These run in both release workflows, so a mistake here would stop or spoil a release."""
import io, json, os, re, subprocess, sys, tempfile, threading, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_package, decky_store, publish_gitea_release as publish, release_notes

fails = 0
def check(ok, msg):
    global fails
    print(("PASS " if ok else "FAIL ") + msg); fails += 0 if ok else 1

tmp = Path(tempfile.mkdtemp())
version = json.loads((ROOT / "package.json").read_text())["version"]

# --- release_notes.py: the tag must match the plugin's version, and the notes give the zip's address --------
def notes_script(tag):
    out = subprocess.run([sys.executable, str(ROOT / "scripts/release_notes.py"), tag, "soullink9/Decky-RomM_Deck",
                          str(tmp / "notes.md")], capture_output=True, text=True)
    return out.returncode, out.stdout, out.stderr

code, out, _ = notes_script(f"v{version}")
notes = (tmp / "notes.md").read_text()
zip_url = f"https://github.com/soullink9/Decky-RomM_Deck/releases/download/v{version}/romm-deck.zip"
check(code == 0 and f"title={release_notes.release_title(version)}" in out and "prerelease=" in out,
      f"the plugin's own version: notes written, title and pre-release given to the workflow ({out.strip()!r})")
check(zip_url in notes and "## What's in it" in notes, "notes give the zip's own download address, then the changelog")
check(not re.search(r"\]\((?!https?:|#)", notes), "every link in the notes is absolute, so it works on the release page")
code, _, err = notes_script("v9.9.9")
check(code != 0 and "isn't the plugin's version" in err, f"another version: refused ({err.strip()})")
check(release_notes.release_title("0.5.0-beta") == "V0.5.0 Beta" and release_notes.release_title("0.6.0") == "V0.6.0",
      "release titles: V0.5.0 Beta, V0.6.0")

# --- check_package.py: what Decky's installer accepts ------------------------------------------------------
def make_zip(name, files):
    path = tmp / name
    with zipfile.ZipFile(path, "w") as z:
        for member, data in files.items():
            z.writestr(member, data)
    return path

good = {"romm-deck/plugin.json": json.dumps({"name": "RomM Deck"}), "romm-deck/main.py": "",
        "romm-deck/dist/index.js": "", "romm-deck/package.json": json.dumps({"version": version})}
check(check_package.problems_in(make_zip("good.zip", good)) == [], "a zip laid out like Decky expects passes")
flat = {k.split("/", 1)[1]: v for k, v in good.items()}
check(check_package.problems_in(make_zip("flat.zip", flat)) != [], "files not inside one folder: refused")
(tmp / "page.zip").write_text("<html>release page</html>")
check(check_package.problems_in(tmp / "page.zip") != [], "a web page saved as .zip: refused")
check(any("rebuild" in p for p in check_package.problems_in(make_zip("old.zip", {**good, "romm-deck/package.json": '{"version": "0.0.1"}'}))),
      "a zip of another version: refused")

# --- decky_store.py: the files a Decky custom store serves, with the official store merged in ----------------
import hashlib
store = tmp / "store"
plugin = json.loads((ROOT / "plugin.json").read_text())
official_list = [{"id": 1, "name": "CSS Loader", "author": "x", "description": "d", "tags": ["style"], "image_url": "i",
                  "versions": [{"name": "2.0.0", "hash": "aa"}]},
                 {"id": 100000, "name": plugin["name"], "author": "someone else", "description": "", "tags": [],
                  "image_url": "", "versions": [{"name": "9.9.9", "hash": "bb"}]}]
official_versions = {"CSS Loader": ["2.0.0", "aa"], plugin["name"]: ["9.9.9", "bb"]}

class FakeOfficial(BaseHTTPRequestHandler):
    """The official store: the list at /plugins and the newest versions at /plugins/versions."""
    up = True
    def log_message(self, *args):
        pass
    def do_GET(self):
        if not FakeOfficial.up:
            self.send_response(503); self.end_headers(); return
        body = {"/plugins": official_list, "/plugins/versions": official_versions}.get(self.path.split("?")[0])
        data = json.dumps(body).encode()
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
official_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOfficial)
threading.Thread(target=official_server.serve_forever, daemon=True).start()
official_url = f"http://127.0.0.1:{official_server.server_port}/plugins"

GH = "soullink9/Decky-RomM_Deck"
def gh_zip(tag):
    return f"https://github.com/{GH}/releases/download/{tag}/romm-deck.zip"
github, asked = {}, []
def fake_github(url):
    asked.append(url)
    return github.get(url)
def gitea_free(store):
    """Every file written to the store branch names no host but GitHub's (and the official store's, in its copy)."""
    hosts = set()
    for f in store.rglob("*"):
        if f.is_file() and f.parent.name != "official":
            hosts |= set(re.findall(r"https?://([^/\s\"']+)", f.read_text()))
    return hosts <= {"github.com", "raw.githubusercontent.com"}, hosts

first = make_zip("first.zip", {**good, "romm-deck/main.py": "first"})
decky_store.add_release(store, "v0.5.1", first, GH)
listing, versions = decky_store.build(store, GH, decky_store.fetch_official(store, official_url), fake_github)
check([p["name"] for p in listing] == ["CSS Loader"] and plugin["name"] not in versions,
      "a release not on GitHub yet isn't listed at all (no Gitea link to fall back on)")

github[gh_zip("v0.5.1")] = b"github's build of 0.5.1"
listing, versions = decky_store.build(store, GH, decky_store.fetch_official(store, official_url), fake_github)
ours = listing[0] if listing else {}
artifact, sha = gh_zip("v0.5.1"), hashlib.sha256(b"github's build of 0.5.1").hexdigest()
check(ours.get("name") == plugin["name"] and ours["author"] == plugin["author"] and ours["tags"] == plugin["publish"]["tags"]
      and ours["versions"][0] == {"name": "0.5.1", "hash": sha, "artifact": artifact, "created": ours["versions"][0]["created"]}
      and ours["image_url"] == f"https://raw.githubusercontent.com/{GH}/v0.5.1/assets/brand/icon@2x.png",
      "once on GitHub: our plugin comes first, with GitHub's link, the hash of the bytes GitHub serves, and GitHub's icon")
check([p["name"] for p in listing] == [plugin["name"], "CSS Loader"] and len({p["id"] for p in listing}) == 2
      and ours["id"] != 100000,
      "the official plugins follow; one with our name is left out, and our id never clashes with theirs")
check(versions == {"CSS Loader": ["2.0.0", "aa"], plugin["name"]: ["0.5.1", sha, artifact]},
      "plugins/versions.json: official update info, and ours with its GitHub address")
check(json.loads((store / "plugins.json").read_text()) == listing
      and json.loads((store / "plugins/versions.json").read_text()) == versions, "…both written where Decky reads them")

second = make_zip("second.zip", {**good, "romm-deck/main.py": "second"})
decky_store.add_release(store, "v0.5.2", second, GH)
decky_store.add_release(store, "v0.5.2", second, GH)
FakeOfficial.up = False
listing, versions = decky_store.build(store, GH, decky_store.fetch_official(store, official_url), fake_github)
check([v["name"] for v in listing[0]["versions"]] == ["0.5.1"] and versions[plugin["name"]][0] == "0.5.1"
      and listing[0]["image_url"].endswith("/v0.5.1/assets/brand/icon@2x.png"),
      "a newer release not on GitHub yet: left out; the store keeps offering the newest one GitHub has")
check([p["name"] for p in listing] == [plugin["name"], "CSS Loader"],
      "official store unreachable: its listing from last time is kept")
check((store / "README.md").exists(), "the store branch says what it is (README.md)")

github[gh_zip("v0.5.2")] = second.read_bytes()
asked.clear()
listing, versions = decky_store.build(store, GH, decky_store.fetch_official(store, official_url), fake_github)
check([v["name"] for v in listing[0]["versions"]] == ["0.5.2", "0.5.1"]
      and versions[plugin["name"]] == ["0.5.2", hashlib.sha256(second.read_bytes()).hexdigest(), gh_zip("v0.5.2")]
      and listing[0]["image_url"] == f"https://raw.githubusercontent.com/{GH}/v0.5.2/assets/brand/icon@2x.png",
      "the next build after GitHub's release appears: the new version goes on top, once, with its update check and icon")
check(asked == [gh_zip("v0.5.2")],
      f"a version already found on GitHub isn't downloaded again (its hash is kept in own.json): {asked}")

# a store from before, whose own.json named the Gitea repository: rewritten to GitHub's on the next build
own = json.loads((store / "own.json").read_text())
own[0]["repository"] = "Soullink/decky-romm_deck"
(store / "own.json").write_text(json.dumps(own))
decky_store.build(store, GH, decky_store.fetch_official(store, official_url), fake_github)
check(json.loads((store / "own.json").read_text())[0]["repository"] == GH, "an older own.json's Gitea repository becomes GitHub's")
ok, hosts = gitea_free(store)
check(ok, f"nothing on the store branch names a host other than GitHub (it's push-mirrored there): {sorted(hosts)}")
FakeOfficial.up = True

# no official listing at all (never fetched, and the official store down): nothing is written
FakeOfficial.up = False
empty_store = tmp / "empty-store"
decky_store.add_release(empty_store, "v0.5.2", second, "owner/decky-romm_deck")
try:
    decky_store.fetch_official(empty_store, official_url)
    refused = False
except decky_store.NoOfficialListing:
    refused = True
check(refused and not (empty_store / "plugins.json").exists(),
      "official store unreachable with no copy from before: refused, so the official plugins never vanish from the store")
official_server.shutdown()

# --- build_zip.py: the same files always make the same zip, so Gitea's and GitHub's builds match ------------
import build_zip, os as _os, time as _time
tree = tmp / "zipsrc" / "romm-deck"
(tree / "bin").mkdir(parents=True)
(tree / "plugin.json").write_text('{"name": "RomM Deck"}')
(tree / "bin" / "run.sh").write_text("#!/bin/sh\n"); (tree / "bin" / "run.sh").chmod(0o755)
build_zip.build(tree, tmp / "one.zip")
_time.sleep(1.1)
for f in tree.rglob("*"):
    _os.utime(f)  # newer modification times, as on another machine or a later checkout
build_zip.build(tree, tmp / "two.zip")
same = (tmp / "one.zip").read_bytes() == (tmp / "two.zip").read_bytes()
modes = {i.filename: oct(i.external_attr >> 16) for i in zipfile.ZipFile(tmp / "one.zip").infolist()}
check(same, "building the same files again, with other file times, gives a byte-for-byte identical zip")
check(modes.get("romm-deck/bin/run.sh") == "0o100755" and modes.get("romm-deck/plugin.json") == "0o100644"
      and list(modes)[0] == "romm-deck/", f"one top folder; executables stay executable, the rest plain files: {modes}")

# --- publish_gitea_release.py against a fake Gitea ------------------------------------------------------------
class FakeGitea(BaseHTTPRequestHandler):
    """Just enough of Gitea's release API: releases by tag, create, edit, delete and upload attachments."""
    releases, calls, uploads, next_id = {}, [], {}, 1  # uploads: asset id -> (bytes, sent as "attachment")

    def log_message(self, *args):
        pass

    def reply(self, code, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self):
        base = "/api/v1/repos/owner/decky-romm_deck"
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        FakeGitea.calls.append((self.command, self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "token secret":
            return self.reply(401, {"message": "token is required"})
        if not path.startswith(base):
            return self.reply(404, {"message": "not found"})
        path = path[len(base):]
        if self.command == "GET" and path.startswith("/releases/tags/"):
            tag = path.rsplit("/", 1)[1]
            found = [r for r in FakeGitea.releases.values() if r["tag_name"] == tag]
            return self.reply(200, found[0]) if found else self.reply(404, {"message": "release not found"})
        if self.command == "POST" and path == "/releases":
            data = json.loads(body)
            release = {**data, "id": FakeGitea.next_id, "assets": []}
            FakeGitea.releases[release["id"]] = release; FakeGitea.next_id += 1
            return self.reply(201, release)
        match = re.fullmatch(r"/releases/(\d+)(/assets(?:/(\d+))?)?", path)
        if not match or int(match[1]) not in FakeGitea.releases:
            return self.reply(404, {"message": "not found"})
        release = FakeGitea.releases[int(match[1])]
        if self.command == "PATCH" and not match[2]:
            release.update(json.loads(body))
            return self.reply(200, release)
        if self.command == "DELETE" and match[3]:
            release["assets"] = [a for a in release["assets"] if a["id"] != int(match[3])]
            return self.reply(204)
        if self.command == "POST" and match[2] and not match[3]:
            boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
            part = body.split(b"--" + boundary)[1]
            head, content = part.split(b"\r\n\r\n", 1)
            name = self.path.split("name=")[1]
            asset = {"id": FakeGitea.next_id, "name": name}
            FakeGitea.uploads[asset["id"]] = (content[:-2], b'name="attachment"' in head)
            FakeGitea.next_id += 1; release["assets"].append(asset)
            return self.reply(201, asset)
        return self.reply(405, {"message": "method not allowed"})

    do_GET = do_POST = do_PATCH = do_DELETE = handle_any

server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitea)
threading.Thread(target=server.serve_forever, daemon=True).start()
gitea_url = f"http://127.0.0.1:{server.server_port}"
zip_path = make_zip("romm-deck.zip", good)
# A real runner sets the workflow's own Gitea addresses for every step; left in, they'd send these calls to the
# real Gitea instead of the fake one. The tests set them themselves where they're needed.
outside = {k: v for k, v in os.environ.items() if k != "LOCAL_GITEA_URL"}
env = {**outside, "GITHUB_SERVER_URL": gitea_url, "GITHUB_REPOSITORY": "owner/decky-romm_deck", "RELEASE_TOKEN": "secret"}

def run_publish(title, extra_env=None):
    return subprocess.run([sys.executable, str(ROOT / "scripts/publish_gitea_release.py"), "v0.5.2", "abc123", title,
                           str(tmp / "notes.md"), "false", str(zip_path)], env={**env, **(extra_env or {})},
                          capture_output=True, text=True)

result = run_publish("V0.5.2")
release = next(iter(FakeGitea.releases.values()), {})
check(result.returncode == 0 and release.get("tag_name") == "v0.5.2" and release.get("target_commitish") == "abc123"
      and release.get("name") == "V0.5.2" and release.get("body") == notes and release.get("prerelease") is False,
      f"new release: created with its tag on the released commit, title and notes ({result.stdout.strip()!r} {result.stderr.strip()!r})")
assets = release.get("assets", [])
check(len(assets) == 1 and assets[0]["name"] == "romm-deck.zip"
      and FakeGitea.uploads[assets[0]["id"]] == (zip_path.read_bytes(), True), "…and the zip uploaded byte for byte, as Gitea's \"attachment\" field")
check(all(auth == "token secret" for _, _, auth in FakeGitea.calls), "every call carries the token")

result = run_publish("V0.5.2 again")
check(result.returncode == 0 and len(FakeGitea.releases) == 1 and release.get("name") == "V0.5.2 again"
      and [a["name"] for a in release["assets"]] == ["romm-deck.zip"],
      "run again for the same tag: the release is updated and its zip replaced, not doubled")

result = run_publish("V0.5.2", {"RELEASE_TOKEN": "wrong"})
check(result.returncode != 0 and "401" in result.stderr, f"a token Gitea refuses: stops with Gitea's answer ({result.stderr.strip()[:80]})")
result = run_publish("V0.5.2 inside", {"GITHUB_SERVER_URL": "https://gitea.example.invalid", "LOCAL_GITEA_URL": gitea_url})
check(result.returncode == 0 and release.get("name") == "V0.5.2 inside",
      "public address unreachable from the runner: LOCAL_GITEA_URL is used instead")
result = run_publish("V0.5.2", {"RELEASE_TOKEN": ""})
check(result.returncode != 0 and "RELEASE_TOKEN" in result.stderr, "no token: stops and says which setting is missing")
server.shutdown()

print(f"\n{fails} failures")
sys.exit(1 if fails else 0)
