"""A very small RomM API client (standard library only)."""
import json
import os
import ssl
import uuid
import urllib.error
import urllib.parse
import urllib.request

from . import config

# Decky ships its own Python, which may not find the system certificates on its own.
_CA_FILES = ("/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/certs/ca-certificates.crt")


def _ssl_context():
    for ca in _CA_FILES:
        if os.path.exists(ca):
            return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


class RomMError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status  # HTTP status from RomM, e.g. 404 when a game was deleted


class RomM:
    def __init__(self, url, token=""):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = 30  # seconds; the launcher lowers this so a dead server can't stall a game
        self.ssl = _ssl_context()

    @classmethod
    def from_settings(cls):
        s = config.load("settings")
        if not s.get("url") or not s.get("token"):
            raise RomMError("Not connected to RomM yet")
        return cls(s["url"], s["token"])

    # ---------- plumbing ----------

    def _open(self, method, path, params=None, body=None, headers=None, timeout=None):
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout, context=self.ssl)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:200]
            raise RomMError(f"RomM said {e.code}: {detail}", e.code) from None
        except urllib.error.URLError as e:
            raise RomMError(f"Can't reach RomM: {e.reason}") from None

    def get(self, path, timeout=None, **params):
        with self._open("GET", path, params, timeout=timeout) as r:
            return json.load(r)

    def post_json(self, path, data):
        body = json.dumps(data).encode()
        with self._open("POST", path, body=body, headers={"Content-Type": "application/json"}) as r:
            return json.load(r)

    def upload(self, path, params, field, filename, data):
        """multipart/form-data POST of a single file."""
        boundary = uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        with self._open("POST", path, params, body=body, headers=headers, timeout=300) as r:
            return json.load(r)

    def download(self, path, dest, progress=None, timeout=60):
        """Stream a file to `dest`. progress(done_bytes, total_bytes) is called as it goes."""
        with self._open("GET", path, timeout=timeout) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1024 * 1024):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)

    def fetch_bytes(self, url_or_path, timeout=None):
        path = url_or_path if url_or_path.startswith("/") else "/" + url_or_path
        with self._open("GET", path, timeout=timeout) as r:
            return r.read()

    # ---------- RomM endpoints we use ----------

    def exchange_pair_code(self, code):
        """Swap a pairing code (RomM web: Settings > Client API Tokens > Pair device) for a token."""
        return self.post_json("/api/client-tokens/exchange", {"code": code})["raw_token"]

    def collections(self):
        regular = self.get("/api/collections")
        smart = self.get("/api/collections/smart")
        out = [{"kind": "collection", "id": c["id"], "name": c["name"], "count": len(c.get("rom_ids") or [])} for c in regular]
        out += [{"kind": "smart", "id": c["id"], "name": c["name"], "count": len(c.get("rom_ids") or [])} for c in smart]
        return sorted(out, key=lambda c: c["name"].lower())

    def platforms(self):
        out = [{"kind": "platform", "id": p["id"], "name": p.get("custom_name") or p["name"], "count": p["rom_count"]}
               for p in self.get("/api/platforms") if p.get("rom_count")]
        return sorted(out, key=lambda p: p["name"].lower())

    def roms(self, kind, key):
        """Games in a collection, smart collection or platform, or matching a search."""
        param = {"collection": "collection_id", "smart": "smart_collection_id",
                 "platform": "platform_ids", "search": "search_term"}[kind]
        page = self.get(
            "/api/roms", limit=10000, order_by="name", with_char_index="false", with_files="true",
            with_filter_values="false", with_rom_id_index="false", **{param: key},
        )
        return page["items"]

    def rom(self, rom_id):
        return self.get(f"/api/roms/{rom_id}")

    def me(self):
        """The signed-in RomM user (includes RetroAchievements progress, if linked)."""
        return self.get("/api/users/me")

    def assets(self, kind, rom_id):
        """kind is 'saves' or 'states'."""
        return self.get(f"/api/{kind}", rom_id=rom_id)

    def firmware(self, platform_id):
        return self.get("/api/firmware", platform_id=platform_id)
