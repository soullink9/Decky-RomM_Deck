"""What RomM knows about a game, shaped for where it's shown.

  * cover art: Steam's grid image (cover) and the panel's small covers (thumb)
  * Steam game pages: details() gives the description, developer, release date, rating, feature
    icons and every other fact; links() the Game Info buttons; activity() the Activity list;
    screenshots() local copies of RomM's screenshots
Nothing here changes RomM or the games; it only reads RomM and keeps small copies on the PC.
"""
import base64
import datetime
import hashlib
import re
import threading
import urllib.parse
from pathlib import Path

from . import config


def cover(client, rom_id):
    """Cover art as base64 for Steam's grid image, or None."""
    path = client.rom(rom_id).get("path_cover_large")  # the large one: Steam's grid is big
    if not path:
        return None
    data = client.fetch_bytes(path)
    return {"data": base64.b64encode(data).decode(), "ext": "png" if data[:4] == b"\x89PNG" else "jpg"}


COVERS = config.SETTINGS_DIR / "covers"  # small cover art for the panel, kept after the first time
_cover_slots = threading.Semaphore(4)  # a long list doesn't send RomM dozens of requests at once


def thumb(client, rom_id, path=""):
    """A game's small cover art for the panel: (data: URL or "" if RomM has none, RomM's path for it).
    `path`: RomM's path, when the list already gave one (saves asking RomM for the game)."""
    rom_id = str(rom_id)
    COVERS.mkdir(parents=True, exist_ok=True)
    mine = sorted(COVERS.glob(f"{rom_id}-*"))
    if not path:
        if mine:
            return _data_url(mine[-1]), ""
        with _cover_slots:
            rom = client.rom(rom_id)
        path = rom.get("path_cover_small") or rom.get("path_cover_large") or ""
        if not path:
            return "", ""
    target = COVERS / f"{rom_id}-{hashlib.sha1(path.encode()).hexdigest()[:10]}"
    if target.exists():
        return _data_url(target), path
    try:
        with _cover_slots:
            data = client.fetch_bytes(path, timeout=15)
    except Exception as e:
        e.cover_path = path  # (so the panel can still try RomM's own address for it)
        raise
    for old in mine:  # the cover changed in RomM: keep only the new one
        old.unlink(missing_ok=True)
    config.write_atomic(target, data)
    return _data_url(target), path


# Steam's feature icons on a game page (its "store categories"), from RomM's game modes
STEAM_FEATURES = {"single player": 2, "multiplayer": 1, "co-operative": 9, "split screen": 24}


def details(rom, base_url="", ra_progress=None):
    """Everything RomM knows about a game, for its Steam page: Steam's own fields (description,
    developers, publishers, release date, rating, feature icons), every other fact as
    (label, text) rows, links for the Game Info buttons, and the Activity list (see activity).
    Missing data is simply left out. `base_url`: RomM's address (for the RomM link)."""
    meta = rom.get("metadatum") or {}
    igdb = rom.get("igdb_metadata") or {}
    ra = rom.get("merged_ra_metadata") or rom.get("ra_metadata") or {}
    hltb = rom.get("hltb_metadata") or {}
    mine = rom.get("rom_user") or {}

    def pick(*values):
        """The first value that isn't empty: RomM's own merged metadata first, then each source's.
        If all are empty: [] when the last fallback is a list, else None."""
        for v in values:
            if v:
                return v
        return [] if isinstance(values[-1], list) else None

    def names(values):
        """Names from a list of strings or of {"name": ...} objects (sources differ)."""
        return [v if isinstance(v, str) else (v or {}).get("name", "") for v in values or []]

    companies = names(pick(meta.get("companies"), igdb.get("companies"), []))
    developers = names(pick(meta.get("developers"), ra.get("developers"), companies[:1], []))
    publishers = names(pick(meta.get("publishers"), ra.get("publishers"), companies[1:2], []))
    date = pick(meta.get("first_release_date"), igdb.get("first_release_date"), ra.get("first_release_date"))
    if isinstance(date, (int, float)) and date > 1e11:  # milliseconds
        date /= 1000
    rating = _number(pick(meta.get("average_rating"), igdb.get("total_rating")))
    if rating is not None and rating <= 10:  # a 0-10 score
        rating *= 10
    modes = pick(meta.get("game_modes"), igdb.get("game_modes"), [])

    facts = []
    def fact(label, value):
        """Add a (label, text) row, joining lists with commas; empty values are left out."""
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value if v)
        if value not in (None, "", 0):
            facts.append([label, str(value)])

    fact("Genres", pick(meta.get("genres"), igdb.get("genres"), ra.get("genres"), []))
    fact("Themes", igdb.get("themes"))
    fact("Game modes", modes)
    fact("Players", meta.get("player_count") if str(meta.get("player_count") or "") not in ("", "1") else "")
    fact("Perspective", igdb.get("player_perspectives"))
    fact("Franchise", pick(meta.get("franchises"), igdb.get("franchises"), []))
    fact("Series", pick(meta.get("collections"), igdb.get("collections"), []))
    fact("Age rating", pick(meta.get("age_ratings"), [a.get("rating", "") for a in igdb.get("age_ratings") or [] if isinstance(a, dict)], []))
    if rating:
        count = meta.get("rating_count") or igdb.get("total_rating_count")
        fact("Rating", f"{round(rating)}/100" + (f" ({count:,} ratings)" if isinstance(count, int) and count else ""))
    fact("How long to beat", " · ".join(f"{label} {_hours(hltb.get(key))}" for key, label in (
        ("main_story", "Main"), ("main_plus_extra", "Main + extras"), ("completionist", "Completionist"))
        if _hours(hltb.get(key))))
    cheevos = [a for a in ra.get("achievements") or [] if isinstance(a, dict)]
    if cheevos:
        points = sum(a.get("points") or 0 for a in cheevos)
        fact("RetroAchievements", f"{len(cheevos)} achievements, {points:,} points")
    fact("Also known as", (rom.get("alternative_names") or igdb.get("alternative_names") or [])[:3])
    fact("Keywords", (igdb.get("keywords") or [])[:8])
    fact("Regions", rom.get("regions"))
    fact("Languages", rom.get("languages"))
    fact("Revision", rom.get("revision"))
    fact("Tags", rom.get("tags"))
    fact("Platform", rom.get("platform_display_name"))
    size = rom.get("fs_size_bytes") or 0
    fact("File", f"{rom.get('fs_name', '')}" + (f" · {size / 1024**3:.1f} GB" if size >= 1024**3 else f" · {size / 1024**2:.0f} MB" if size else ""))
    status = [str(mine.get("status")).replace("_", " ").capitalize() if mine.get("status") else "",
              f"{mine['completion']}% complete" if mine.get("completion") else "",
              f"rated {mine['rating']}/10" if mine.get("rating") else "",
              "now playing" if mine.get("now_playing") else "", "in backlog" if mine.get("backlogged") else ""]
    fact("In your RomM", [x for x in status if x])
    fact("RomM game", f"#{rom['id']}" if rom.get("id") else "")

    return {
        "description": (rom.get("summary") or "").strip(),
        "developers": [d for d in developers if d][:4],
        "publishers": [p for p in publishers if p][:4],
        "release_date": int(date) if isinstance(date, (int, float)) and date > 0 else None,
        "rating": round(rating) if rating else None,
        "features": sorted({STEAM_FEATURES[m.lower()] for m in names(modes) if m and m.lower() in STEAM_FEATURES}),
        "facts": facts,
        "links": links(rom, base_url),
        "activity": activity(rom, ra_progress),
    }


def links(rom, base_url=""):
    """[label, address] for the buttons under Game Info: the game in RomM, and the sites RomM matched it to."""
    out = []
    if base_url and rom.get("id"):
        out.append(["RomM", f"{base_url.rstrip('/')}/rom/{rom['id']}"])
    if rom.get("ra_id"):
        out.append(["RetroAchievements", f"https://retroachievements.org/game/{rom['ra_id']}"])
    if rom.get("hltb_id"):
        out.append(["HowLongToBeat", f"https://howlongtobeat.com/game/{rom['hltb_id']}"])
    if rom.get("youtube_video_id"):
        out.append(["Trailer", f"https://www.youtube.com/watch?v={urllib.parse.quote(str(rom['youtube_video_id']))}"])
    return out


def activity(rom, ra_progress=None, limit=40):
    """What's happened with a game, newest first, for its Steam page's Activity:
    [{"at": unix time, "kind": note|achievement|award|save|state|played, "title", "body", "by", "image"}].
    From RomM: notes (yours and other players' public ones), RetroAchievements unlocks
    (`ra_progress`: the user's progress from /api/users/me), saves and states, last played."""
    events = []

    def add(when, kind, title, body="", by="", image=""):
        """Add one event, if its time can be read (an event without a time can't be placed)."""
        at = _when(when)
        if at:
            events.append({"at": at, "kind": kind, "title": title, "body": body, "by": by, "image": image})

    for n in rom.get("all_user_notes") or []:
        text = (n.get("content") or "").strip()
        add(n.get("updated_at") or n.get("created_at"), "note", (n.get("title") or "").strip() or "Note",
            text if len(text) <= 1200 else text[:1200].rstrip() + "…", n.get("username") or "")

    ra = rom.get("merged_ra_metadata") or rom.get("ra_metadata") or {}
    badges = {a.get("badge_id"): a for a in ra.get("achievements") or [] if isinstance(a, dict) and a.get("badge_id")}
    for game in (ra_progress or {}).get("results") or []:
        if not rom.get("ra_id") or game.get("rom_ra_id") != rom.get("ra_id"):
            continue
        for e in game.get("earned_achievements") or []:
            a = badges.get(e.get("id")) or {}
            body = [a.get("description") or "", f"{a['points']} points" if a.get("points") else "", "hardcore" if e.get("date_hardcore") else ""]
            add(e.get("date_hardcore") or e.get("date"), "achievement", a.get("title") or "Achievement unlocked",
                " · ".join(x for x in body if x), image=a.get("badge_url") or "")
        if game.get("highest_award_kind"):
            add(game.get("most_recent_awarded_date"), "award", f"{str(game['highest_award_kind']).replace('-', ' ').capitalize()} on RetroAchievements",
                f"{game.get('num_awarded') or 0} of {game.get('max_possible') or 0} achievements")

    for kind, label in (("save", "Save"), ("state", "Save state")):
        for s in sorted(rom.get(f"user_{kind}s") or [], key=lambda s: str(s.get("updated_at") or ""), reverse=True)[:10]:
            add(s.get("updated_at") or s.get("created_at"), kind, f"{label} in RomM",
                " · ".join(x for x in (s.get("file_name"), s.get("emulator")) if x))
    add((rom.get("rom_user") or {}).get("last_played"), "played", "Played")

    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


def _when(value):
    """RomM's and RetroAchievements' times (ISO, "2026-01-02 10:00:00", seconds or ms) as unix time, or None."""
    if isinstance(value, (int, float)) and value > 0:
        return int(value / 1000 if value > 1e11 else value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"\.\d+", "", value.strip().replace("Z", "+00:00").replace(" ", "T", 1))  # (older Pythons: no fractions)
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            when = datetime.datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)  # both report UTC
    return int(when.timestamp())


SHOTS = config.DATA_DIR / "shots"  # RomM's screenshots, copied for Steam's game pages


def screenshots(client, rom_id, paths, limit=10):
    """Copies on this PC of RomM's screenshots of a game: ["shots/<rom>/<file>"] (under DATA_DIR).
    Steam's pages can't show pictures from a plain-http (or self-signed) RomM, but they can show
    what Decky serves from DATA_DIR. Ones already copied aren't fetched again; old ones are removed."""
    folder = SHOTS / str(rom_id)
    wanted = {}
    for path in (paths or [])[:limit]:
        ext = Path(urllib.parse.urlparse(path).path).suffix.lower()
        wanted[hashlib.sha1(path.encode()).hexdigest()[:12] + (ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg")] = path
    out = []
    if wanted:
        folder.mkdir(parents=True, exist_ok=True)
    for name, path in wanted.items():
        target = folder / name
        if not target.exists():
            try:
                data = client.fetch_bytes(path, timeout=20)
            except Exception as e:
                config.log.warning("Screenshot %s of rom %s not copied: %s", path, rom_id, e)
                continue
            config.write_atomic(target, data)
        out.append(f"shots/{rom_id}/{name}")
    if folder.is_dir():
        for old in folder.iterdir():
            if old.name not in wanted:
                old.unlink(missing_ok=True)
        if not any(folder.iterdir()):
            folder.rmdir()
    return out


def _number(value):
    """A number from RomM's data (which sometimes sends numbers as strings), or None."""
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _hours(value):
    """HLTB times are seconds: "12 h" (or "" if unknown)."""
    v = _number(value)
    if not v:
        return ""
    hours = v / 3600 if v > 500 else v
    return f"{hours:.0f} h" if hours >= 1 else f"{round(hours * 60)} min"


def _data_url(path):
    """An image file as a data: URL, which the panel can show without reaching RomM."""
    data = Path(path).read_bytes()
    return f"data:image/{_image_type(data)};base64,{base64.b64encode(data).decode()}"


def _image_type(data):
    """png, webp, gif or jpeg, from the file's first bytes (RomM's paths don't always say)."""
    if data[:4] == b"\x89PNG":
        return "png"
    if data[8:12] == b"WEBP":
        return "webp"
    if data[:3] == b"GIF":
        return "gif"
    return "jpeg"
