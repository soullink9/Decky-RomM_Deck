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
check(release_notes.release_title("0.5.0-beta") == "V0.5.0 Beta" and release_notes.release_title("1.0.2") == "V1.0.2",
      "release titles: V0.5.0 Beta, V1.0.2")

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

# --- decky_store.py: the files a Decky custom store serves ----------------------------------------------------
store = tmp / "store"
plugin = json.loads((ROOT / "plugin.json").read_text())
first = make_zip("first.zip", {**good, "romm-deck/main.py": "first"})
decky_store.add_release(store, "0.5.1", first, "https://gitea.example/r/releases/download/v0.5.1/romm-deck.zip", "https://gitea.example/icon.png")
listing = json.loads((store / "plugins.json").read_text())
entry = listing[0] if listing else {}
import hashlib
check(len(listing) == 1 and entry["name"] == plugin["name"] and entry["author"] == plugin["author"]
      and entry["tags"] == plugin["publish"]["tags"] and entry["image_url"] == "https://gitea.example/icon.png"
      and entry["versions"][0]["hash"] == hashlib.sha256(first.read_bytes()).hexdigest()
      and entry["versions"][0]["artifact"].endswith("/v0.5.1/romm-deck.zip"),
      "a new store: the plugin listed under plugin.json's name, with the zip's SHA-256 and download address")
second = make_zip("second.zip", {**good, "romm-deck/main.py": "second"})
decky_store.add_release(store, "0.5.2", second, "https://gitea.example/r/releases/download/v0.5.2/romm-deck.zip", "https://gitea.example/icon.png")
entry = json.loads((store / "plugins.json").read_text())[0]
versions = json.loads((store / "plugins/versions.json").read_text())
check([v["name"] for v in entry["versions"]] == ["0.5.2", "0.5.1"], "the next release goes on top; the older one stays installable")
check(versions == {plugin["name"]: ["0.5.2", hashlib.sha256(second.read_bytes()).hexdigest(), entry["versions"][0]["artifact"]]},
      "plugins/versions.json (Decky 3.3.1+ update checks): the newest version, hash and address")
decky_store.add_release(store, "0.5.2", first, "https://gitea.example/again.zip", "https://gitea.example/icon.png")
entry = json.loads((store / "plugins.json").read_text())[0]
check([v["name"] for v in entry["versions"]] == ["0.5.2", "0.5.1"] and entry["versions"][0]["artifact"] == "https://gitea.example/again.zip",
      "releasing a version again replaces its entry instead of listing it twice")
(store / "plugins.json").write_text(json.dumps([{"id": 7, "name": "Another Plugin", "versions": [{"name": "1.0.0", "hash": "x", "artifact": "y"}]}]))
decky_store.add_release(store, "0.5.2", second, "https://gitea.example/z.zip", "https://gitea.example/icon.png")
listing = json.loads((store / "plugins.json").read_text())
check(sorted(p["name"] for p in listing) == sorted(["Another Plugin", plugin["name"]]) and len({p["id"] for p in listing}) == 2,
      "other plugins in the same store are kept, each with its own id")

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
env = {**os.environ, "GITHUB_SERVER_URL": gitea_url, "GITHUB_REPOSITORY": "owner/decky-romm_deck", "RELEASE_TOKEN": "secret"}

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
check(result.returncode == 0 and len(FakeGitea.releases) == 1 and release["name"] == "V0.5.2 again"
      and [a["name"] for a in release["assets"]] == ["romm-deck.zip"],
      "run again for the same tag: the release is updated and its zip replaced, not doubled")

result = run_publish("V0.5.2", {"RELEASE_TOKEN": "wrong"})
check(result.returncode != 0 and "401" in result.stderr, f"a token Gitea refuses: stops with Gitea's answer ({result.stderr.strip()[:80]})")
result = run_publish("V0.5.2 inside", {"GITHUB_SERVER_URL": "https://gitea.example.invalid", "GITEA_INTERNAL_URL": gitea_url})
check(result.returncode == 0 and release["name"] == "V0.5.2 inside",
      "public address unreachable from the runner: GITEA_INTERNAL_URL is used instead")
result = run_publish("V0.5.2", {"RELEASE_TOKEN": ""})
check(result.returncode != 0 and "RELEASE_TOKEN" in result.stderr, "no token: stops and says which setting is missing")
server.shutdown()

print(f"\n{fails} failures")
sys.exit(1 if fails else 0)
