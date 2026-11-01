"""Minimal fake RomM (only the endpoints the plugin uses) for offline testing."""
import io, json, re, sys, threading, zipfile
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

TOKEN = "rmm_testtoken"
CLOCK = [datetime(2026, 10, 1, tzinfo=timezone.utc)]


def tick():
    CLOCK[0] += timedelta(minutes=1)
    return CLOCK[0].isoformat()


def rom(id, name, slug, fs_slug, fs_name, ext, multi=False, size=1000):
    return dict(id=id, name=name, platform_slug=slug, platform_fs_slug=fs_slug, platform_id={"gba": 1, "psx": 2, "ngc": 3, "switch": 4, "pico": 5, "nds": 7, "ps3": 8}[slug],
                platform_display_name=slug.upper(), fs_name=fs_name, fs_name_no_ext=fs_name.rsplit(".", 1)[0] if not multi else fs_name,
                fs_extension=ext, fs_size_bytes=size, has_multiple_files=multi, files=[], path_cover_large=f"/assets/romm/resources/roms/{id}/cover/big.png?ts=1")


def zipped(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return b.getvalue()


ROMS = {
    1: rom(1, "Pokemon Emerald", "gba", "gba", "Pokemon Emerald (USA).gba", "gba"),
    2: rom(2, "Final Fantasy VII", "psx", "psx", "Final Fantasy VII (USA)", "", multi=True),
    3: rom(3, "Wind Waker", "ngc", "gc", "Wind Waker (USA).rvz", "rvz"),
    4: {**rom(4, "Zelda TOTK", "switch", "switch", "Zelda TOTK.nsp", "nsp"), "title_id": "0100F4700B2E0000"},
    5: rom(5, "Crash", "psx", "psx", "Crash (USA).zip", "zip"),
    6: rom(6, "Some Pico Game", "pico", "pico8", "game.p8", "p8"),
    7: rom(7, "Pokemon Platinum", "nds", "nds", "Pokemon Platinum (USA).nds", "nds"),
}
CONTENT = {
    1: b"GBA" * 1000,
    2: zipped({"Final Fantasy VII (USA) (Disc 1).chd": b"d1", "Final Fantasy VII (USA) (Disc 2).chd": b"d2",
               "Final Fantasy VII (USA).m3u": b"Final Fantasy VII (USA) (Disc 1).chd\nFinal Fantasy VII (USA) (Disc 2).chd\n"}),
    3: b"RVZ" * 10,
    4: b"NSP" * 10,
    5: zipped({"Crash (USA).cue": b"cue", "Crash (USA).bin": b"bin"}),
    6: b"p8",
    7: b"NDS" * 10,
}
# games only reachable by platform/search (not in a collection), already on the PC
EXTRA_ROMS = [
    rom(50, "Metroid Fusion", "gba", "gba", "Metroid Fusion (USA).gba", "gba"),
    rom(51, "Spyro", "psx", "psx", "Spyro (USA).cue", "cue"),
    rom(52, "Not On PC", "gba", "gba", "Not On PC.gba", "gba"),
]
COLLECTIONS = [{"id": 10, "name": "Favorites", "rom_ids": [1, 2, 3, 4, 5, 6, 7]}]
SMART = [{"id": 20, "name": "Recently added", "rom_ids": [1]}]
FIRMWARE = {4: [{"id": 100, "file_name": "prod.keys"}], 1: [{"id": 101, "file_name": "gba_bios.bin"}]}
ASSETS = {"saves": [], "states": []}  # each: dict(id, rom_id, emulator, file_name, updated_at, data)
NEXT_ID = [1000]
UPLOADS = []
FILES = {}  # file id -> bytes
FILE_REQUESTS = []
FAIL_UPLOADS = [False]


def parse_multipart(body, ctype):
    boundary = re.search(r"boundary=(.+)", ctype).group(1).encode()
    for part in body.split(b"--" + boundary):
        if b"filename=" in part:
            head, _, data = part.partition(b"\r\n\r\n")
            fname = re.search(rb'filename="([^"]*)"', head).group(1).decode()
            return fname, data[:-2] if data.endswith(b"\r\n") else data
    raise ValueError("no file")


ME = {"id": 1, "username": "me", "ra_progression": None}  # RomM user (RetroAchievements progress when linked)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authed(self):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send(403, {"detail": "Forbidden"})
            return False
        return True

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query); p = u.path
        if p.startswith("/assets/romm/resources/roms/"):
            return self.send(200, raw=b"\x89PNG fake", ctype="image/png")
        if not self.authed():
            return
        if p == "/api/users/me":
            return self.send(200, ME)
        if p == "/api/collections":
            return self.send(200, COLLECTIONS)
        if p == "/api/collections/smart":
            return self.send(200, SMART)
        if p == "/api/platforms":
            plats = {}
            for r in list(ROMS.values()) + EXTRA_ROMS:
                pl = plats.setdefault(r["platform_id"], {"id": r["platform_id"], "name": r["platform_display_name"], "custom_name": None, "rom_count": 0})
                pl["rom_count"] += 1
            return self.send(200, list(plats.values()))
        if p == "/api/roms":
            allr = list(ROMS.values()) + EXTRA_ROMS
            if "platform_ids" in q:
                items = [r for r in allr if r["platform_id"] == int(q["platform_ids"][0])]
            elif "search_term" in q:
                items = [r for r in allr if q["search_term"][0].lower() in r["name"].lower()]
            else:
                cid = int((q.get("collection_id") or q.get("smart_collection_id"))[0])
                ids = next(c["rom_ids"] for c in COLLECTIONS + SMART if c["id"] == cid)
                items = [ROMS[i] for i in ids]
            return self.send(200, {"items": items, "total": len(items)})
        m = re.fullmatch(r"/api/roms/(\d+)", p)
        if m:
            found = {r["id"]: r for r in list(ROMS.values()) + EXTRA_ROMS}.get(int(m[1]))
            return self.send(200, found) if found else self.send(404, {"detail": f"Rom with ID {m[1]} not found"})
        m = re.fullmatch(r"/api/roms/(\d+)/content/(.+)", p)
        if m and "file_ids" in q:  # one file of a multi-file game
            f = next(f for f in ROMS[int(m[1])]["files"] if str(f["id"]) == q["file_ids"][0])
            assert unquote(m[2]) == f["file_name"], m[2]
            FILE_REQUESTS.append(f["file_name"])
            return self.send(200, raw=FILES[f["id"]], ctype="application/octet-stream")
        if m:
            assert unquote(m[2]) == ROMS[int(m[1])]["fs_name"], m[2]
            return self.send(200, raw=CONTENT[int(m[1])], ctype="application/octet-stream")
        if p == "/api/firmware":
            return self.send(200, FIRMWARE.get(int(q["platform_id"][0]), []))
        m = re.fullmatch(r"/api/firmware/(\d+)/content/(.+)", p)
        if m:
            return self.send(200, raw=b"FW" + m[1].encode(), ctype="application/octet-stream")
        m = re.fullmatch(r"/api/(saves|states)", p)
        if m:
            rid = int(q["rom_id"][0])
            return self.send(200, [{k: v for k, v in a.items() if k != "data"} for a in ASSETS[m[1]] if a["rom_id"] == rid])
        m = re.fullmatch(r"/api/(saves|states)/(\d+)/content", p)
        if m:
            a = next(a for a in ASSETS[m[1]] if a["id"] == int(m[2]))
            return self.send(200, raw=a["data"], ctype="application/octet-stream")
        self.send(404, {"detail": "nope " + p})

    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query); p = u.path
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if p == "/api/client-tokens/exchange":
            code = json.loads(body)["code"].replace("-", "").upper()
            if code == "ABCD1234":
                return self.send(200, {"raw_token": TOKEN})
            return self.send(404, {"detail": "Invalid or expired pairing code"})
        if not self.authed():
            return
        m = re.fullmatch(r"/api/(saves|states)", p)
        if m and FAIL_UPLOADS[0]:
            return self.send(500, {"detail": "disk full"})
        if m:
            kind = m[1]
            fname, data = parse_multipart(body, self.headers["Content-Type"])
            rid, emu = int(q["rom_id"][0]), q.get("emulator", [None])[0]
            existing = next((a for a in ASSETS[kind] if a["rom_id"] == rid and a["emulator"] == emu and a["file_name"] == fname), None)
            if existing:
                existing.update(data=data, updated_at=tick())
                a = existing
            else:
                NEXT_ID[0] += 1
                a = dict(id=NEXT_ID[0], rom_id=rid, emulator=emu, file_name=fname, updated_at=tick(), data=data)
                ASSETS[kind].append(a)
            UPLOADS.append((kind, rid, emu, fname))
            return self.send(200, {k: v for k, v in a.items() if k != "data"})
        self.send(404, {"detail": "nope"})


def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
