"""Decky backend: the Quick Access panel calls these methods (see src/index.tsx)."""
import asyncio
import json
import os
import time

import decky
from romm_deck import autoload, config, library, motion, presets, saves, session, systems
from romm_deck.api import RomM, RomMError

config.log = decky.logger  # shared code logs into Decky's plugin log


class Plugin:
    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self.downloading = {}  # rom_id -> percent
        self.download_names = {}  # rom_id -> what the home page calls it while it downloads
        self._cover_failed = set()
        self.loop.create_task(self.game_closed())  # a game left unfinished by a crash or power-off
        if not getattr(self, "_notes", None):
            self._notes = self.loop.create_task(self._pass_on_notifications())

    async def _unload(self):
        pass

    async def _pass_on_notifications(self):
        """Popups from the launcher (settings/notify/*.json) go to the panel, which shows them."""
        folder = config.SETTINGS_DIR / "notify"
        while True:
            for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
                try:
                    note = json.loads(path.read_text())
                    if time.time() - path.stat().st_mtime < 120:  # old ones (plugin was off) are dropped
                        await decky.emit("notify", note.get("title", "RomM Deck"), note.get("body", ""))
                except (OSError, ValueError):
                    pass
                path.unlink(missing_ok=True)
            await asyncio.sleep(0.5)

    # ---------- connection ----------

    async def status(self):
        s = config.load("settings")
        return {"connected": bool(s.get("token")), "url": s.get("url", "")}

    async def connect(self, url, code_or_token):
        """Accepts a pairing code from RomM's web UI, or a client token (rmm_...)."""
        url = url.strip().rstrip("/")
        if not url.startswith("http"):
            url = "https://" + url
        code_or_token = code_or_token.strip()
        try:
            client = RomM(url)
            token = code_or_token if code_or_token.startswith("rmm_") else \
                await asyncio.to_thread(client.exchange_pair_code, code_or_token)
            client.token = token
            await asyncio.to_thread(client.collections)  # proves the token works
        except RomMError as e:
            return {"ok": False, "error": str(e)}
        config.save("settings", {**config.load("settings"), "url": url, "token": token})
        return {"ok": True}

    async def disconnect(self):
        s = config.load("settings")
        s.pop("url", None), s.pop("token", None)  # other settings stay
        config.save("settings", s)

    # ---------- browsing ----------

    async def collections(self):
        return await self._call(lambda c: c.collections())

    async def platforms(self):
        return await self._call(lambda c: c.platforms())

    async def roms(self, kind, key):
        """kind: collection | smart | platform (key is its id) or search (key is the text)."""
        items = await self._call(lambda c: c.roms(kind, key))
        if isinstance(items, dict):  # an error
            return items
        on_pc = await asyncio.to_thread(library.find_existing, items)
        return [{
            "id": r["id"],
            "name": r.get("name") or r["fs_name_no_ext"],
            "platform": r["platform_display_name"],
            "installed": r["id"] in on_pc,
            "cover": r.get("path_cover_small") or r.get("path_cover_large") or "",
        } for r in items]

    async def thumb(self, rom_id, path=""):
        """Small cover art for the panel: {"data": the copy saved on this PC as a data: URL,
        "url": RomM's own address for it}, either "" if unknown. The panel tries them in that order."""
        base = config.load("settings").get("url", "")
        try:
            data, path = await asyncio.to_thread(library.thumb, RomM.from_settings(), library.resolve(rom_id), path or "")
        except Exception as e:
            path = getattr(e, "cover_path", path) or ""
            if rom_id not in self._cover_failed:  # once per game, so a long list doesn't flood the log
                self._cover_failed.add(rom_id)
                decky.logger.warning("No cover for rom %s (%s): %s", rom_id, path or "no path", e)
            data = ""
        return {"data": data, "url": f"{base}{path if path.startswith('/') else '/' + path}" if base and path else ""}

    async def steam_details(self):
        """{Steam app id: RomM's details} for RomM Deck's cards, for their Steam pages.
        Kept on the PC (settings/steam-details.json) and refreshed weekly (and when a game is
        played or its page opened, see page_opened); ones not fetched yet arrive later as a
        'steam_details' event, so nothing waits on RomM."""
        games, kept = library.installed(), config.load("steam-details")
        out, missing = {}, []
        for rid, g in games.items():
            if not g.get("app_id"):
                continue
            entry = kept.get(rid)
            if entry:
                out[str(g["app_id"])] = {**entry["details"], "activity": self._with_last_sync(rid, entry["details"])}
            if not entry or time.time() - entry.get("at", 0) > 7 * 86400:
                missing.append(rid)
        self._refresh_details(missing)
        return out

    @staticmethod
    def _with_last_sync(rom_id, details):
        """The game's Activity, plus how its last save sync on this PC went."""
        events = list(details.get("activity") or [])
        st = saves.status(rom_id)
        if st and st.get("at"):
            events.append({"at": int(st["at"]), "kind": "sync" if st.get("ok") else "sync-failed",
                           "title": "Saves synced with RomM" if st.get("ok") else "Save sync didn't finish",
                           "body": "" if st.get("ok") else st.get("error", ""), "by": "", "image": ""})
            events.sort(key=lambda e: e["at"], reverse=True)
        return events

    def _refresh_details(self, ids):
        if ids and not getattr(self, "_fetching_details", False):
            self._fetching_details = True
            self.loop.create_task(self._fetch_details(ids))

    async def page_opened(self, app_id):
        """A RomM Deck card's Steam page was opened: catch up on its notes, saves and
        achievements if they're more than 15 minutes old."""
        rid = next((r for r, g in library.installed().items() if str(g.get("app_id")) == str(app_id)), None)
        entry = config.load("steam-details").get(rid) if rid else None
        if rid and (not entry or time.time() - entry.get("at", 0) > 15 * 60):
            self._refresh_details([rid])

    async def _fetch_details(self, ids):
        try:
            client = RomM.from_settings()
            base = config.load("settings").get("url", "")
            progress, asked = None, False
            for rid in ids:
                try:
                    rom = await asyncio.to_thread(client.rom, rid)
                    if rom.get("ra_id") and not asked:  # RetroAchievements unlocks: one ask for all games
                        asked = True
                        try:
                            progress = (await asyncio.to_thread(client.me)).get("ra_progression")
                        except RomMError as e:
                            decky.logger.info("No RetroAchievements progress from RomM: %s", e)
                    found = library.details(rom, base, progress)
                    try:
                        found["screenshots"] = await asyncio.to_thread(library.screenshots, client, rid, rom.get("merged_screenshots"))
                    except OSError as e:  # (can't write the copies: the page just has no screenshots)
                        decky.logger.warning("Screenshots of rom %s not copied: %s", rid, e)
                        found["screenshots"] = []
                except RomMError as e:
                    decky.logger.warning("No RomM details for rom %s: %s", rid, e)
                    continue
                with config.editing("steam-details") as kept:
                    kept[rid] = {"details": found, "at": time.time()}
            self._fetching_details = False
            await decky.emit("steam_details", await self.steam_details())
        except Exception:
            decky.logger.exception("Fetching RomM details for Steam pages failed")
        finally:
            self._fetching_details = False

    async def log_steam_page(self, text):
        """What Steam's page looked like, when RomM Deck couldn't find its place on it (for fixing that)."""
        decky.logger.info("Steam page: %s", str(text)[:4000])

    async def summary(self):
        """Counts for the home page. RomM's are kept for 5 minutes."""
        if time.time() - getattr(self, "_counted_at", 0) > 300:
            def count(client):
                platforms = [p for p in client.platforms() if p.get("count", 1)]
                return {"platforms": len(platforms), "collections": len(client.collections())}
            r = await self._call(count)
            if "error" not in r:
                self._counts, self._counted_at = r, time.time()
        return {"on_pc": len(library.installed()), **getattr(self, "_counts", {})}

    async def match_app(self, app_id, exe, options):
        """The RomM game behind a Steam card (for opening the panel on it), or None."""
        try:
            return await asyncio.to_thread(library.match_shortcut, RomM.from_settings(), app_id, exe or "", options or "")
        except Exception:
            decky.logger.exception("Couldn't match Steam app %s", app_id)
            return None

    async def scan(self):
        """Match every game in RomM against Emulation/roms, platform by platform, and move games
        whose RomM entry was deleted to the entry that matches them now."""
        def run(client):
            before = set(library.installed())
            everything = [r for p in client.platforms() for r in client.roms("platform", p["id"])]
            ids = {r["id"] for r in everything}
            relinked, lost = [], []
            for rom_id, g in library.installed().items():
                if int(rom_id) not in ids:
                    (relinked if library.relink(client, rom_id, everything) else lost).append(g["name"])
            library.find_existing(everything)
            found = len(set(library.installed()) - before) - len(relinked)
            return {"found": max(found, 0), "relinked": relinked, "lost": lost}
        return await self._call(run)

    async def game(self, rom_id):
        rom_id = library.resolve(rom_id)

        def fetch(client):
            try:
                return client.rom(rom_id)
            except RomMError as e:
                if e.status != 404 or not library.installed().get(str(rom_id)):
                    raise
                new_id = library.relink(client, rom_id)  # its RomM entry was deleted
                if not new_id:
                    raise RomMError("RomM no longer has this game, and no other RomM game matches "
                                    "the file on this PC") from None
                return client.rom(new_id)

        r = await self._call(fetch)
        if "error" in r:
            return r
        rom_id = r["id"]
        await asyncio.to_thread(library.find_existing, [r])
        local = library.installed().get(str(rom_id))
        return {
            "id": r["id"],
            "name": r.get("name") or r["fs_name_no_ext"],
            "platform": r["platform_display_name"],
            "platform_id": r["platform_id"],
            "size_mb": round(r["fs_size_bytes"] / 1048576),
            "installed": bool(local),
            "playable": bool(local and local.get("launch")),
            "app_id": local.get("app_id") if local else None,
            "downloading": self.downloading.get(rom_id),
            "extras": len(library._extra_files(r)),  # Switch updates & DLC in RomM
            "extras_on_pc": sum(1 for p in (local or {}).get("extras", []) if os.path.isfile(p)),
            "extras_dir": str(library.extras_dir() or ""),
            "preset": self._preset_info((local or {}).get("system") or r["platform_slug"]),
            "cover": r.get("path_cover_small") or r.get("path_cover_large") or "",
            "saves": saves.status(rom_id) if local and saves.emu_for(local) else None,
            "syncs": bool(local and saves.emu_for(local)),
            "about": {k: v for k, v in library.details(r).items() if k in ("developers", "release_date")},
        }

    def _preset_info(self, platform):
        p = presets.preset_for(platform)
        if not p:
            return None
        return {"platform": platform, "label": p["label"], "about": p["about"], "motion": p["motion"],
                "on": presets.enabled(platform), **presets.status(platform)}

    async def calibrate_motion(self):
        """Guided calibration of the motion sensor; steps arrive as 'calibration' events."""
        def progress(text):
            asyncio.run_coroutine_threadsafe(decky.emit("calibration", text), self.loop)
        try:
            await asyncio.to_thread(motion.calibrate, progress)
            return {"ok": True}
        except motion.SensorError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            decky.logger.exception("Motion calibration failed")
            return {"ok": False, "error": str(e)}

    async def set_preset(self, platform, on):
        """Turn a device controller preset on/off for a platform."""
        try:
            await asyncio.to_thread(presets.set_enabled, platform, on)
            return {"ok": True}
        except Exception as e:
            decky.logger.exception("Controller preset for %s", platform)
            return {"ok": False, "error": str(e)}

    async def downloads(self):
        """What's downloading right now, for the home page."""
        return [{"id": k, "name": self.download_names.get(k, f"RomM game #{k}"), "percent": v}
                for k, v in self.downloading.items()]

    async def installed(self):
        return [{"id": int(k), "name": g["name"], "platform": g["platform"], "installed": True}
                for k, g in sorted(library.installed().items(), key=lambda kv: kv[1]["name"].lower())]

    # ---------- download / remove ----------

    async def download(self, rom_id, name=""):
        """Starts in the background; reports with 'progress' and 'downloaded' events."""
        if rom_id not in self.downloading:
            self.downloading[rom_id] = 0
            self.download_names[rom_id] = name or f"RomM game #{rom_id}"
            self.loop.create_task(self._download(rom_id))

    async def download_extras(self, rom_id, name=""):
        """Switch updates & DLC for a game already on the PC (background, like download)."""
        rom_id = library.resolve(rom_id)
        if rom_id not in self.downloading:
            self.downloading[rom_id] = 0
            self.download_names[rom_id] = f"{name or f'RomM game #{rom_id}'} (updates & DLC)"
            self.loop.create_task(self._download(rom_id, extras_only=True))

    # ---------- settings ----------

    async def options(self):
        s = config.load("settings")
        return {"steam_pages": s.get("steam_pages", True),
                "switch_extras_dir": str(library.extras_dir() or ""),
                "switch_extras_dir_from_ryujinx": not s.get("switch_extras_dir") and bool(library.extras_dir())}

    async def set_option(self, key, value):
        if key not in ("switch_extras_dir", "steam_pages"):
            return
        s = config.load("settings")
        s[key] = value.strip() if isinstance(value, str) else value
        config.save("settings", s)

    async def _download(self, rom_id, extras_only=False):
        last = [-1]

        def progress(done, total):
            pct = int(done * 100 / total) if total else 0
            if pct != last[0]:
                last[0] = self.downloading[rom_id] = pct
                asyncio.run_coroutine_threadsafe(decky.emit("progress", rom_id, pct), self.loop)

        try:
            client = RomM.from_settings()
            if extras_only:
                n = await asyncio.to_thread(library.download_extras, client, rom_id, progress)
                name = library.installed()[str(rom_id)]["name"]
                await decky.emit("downloaded", rom_id, {"ok": True, "name": name, "playable": False, "extras": n})
                return
            game = await asyncio.to_thread(library.install, client, rom_id, progress)
            await decky.emit("downloaded", rom_id, {"ok": True, "name": game["name"], "playable": bool(game["launch"]),
                                                    "extras": len(game.get("extras", []))})
        except Exception as e:  # report anything to the panel instead of failing silently
            decky.logger.exception("Download of rom %s failed", rom_id)
            await decky.emit("downloaded", rom_id, {"ok": False, "error": str(e)})
        finally:
            self.downloading.pop(rom_id, None)
            self.download_names.pop(rom_id, None)

    async def uninstall(self, rom_id):
        """Final save sync, check RomM has every save, then delete saves, game and Steam card.
        Any problem: nothing is deleted and the reason comes back as {"ok": False, "error"}."""
        rom_id = library.resolve(rom_id)
        if session.running(rom_id):
            return {"ok": False, "error": "It's running right now. Close the game first."}
        try:
            r = await asyncio.to_thread(library.uninstall, RomM.from_settings(), rom_id)
            return {"ok": True, **r}
        except Exception as e:
            decky.logger.exception("Uninstall stopped for rom %s", rom_id)
            return {"ok": False, "error": str(e)}

    async def take_over(self, rom_id, app_id, exe, options, start_dir):
        rom_id = library.resolve(rom_id)
        try:
            return await asyncio.to_thread(library.take_over, rom_id, app_id, exe, options, start_dir)
        except Exception as e:
            decky.logger.exception("Couldn't take over card %s", app_id)
            return {"error": str(e)}

    async def taken_over(self):
        return library.taken_over()

    async def card(self, rom_id):
        """Steam card details, or None if the game has no emulator set up."""
        rom_id = library.resolve(rom_id)
        game = library.installed().get(str(rom_id))
        if not game or not game.get("launch"):
            return None
        collections = systems.COLLECTIONS.get(game["system"]) or [game["platform"]]
        return {"name": game["name"], "collections": collections, **library.shortcut(rom_id)}

    async def set_app_id(self, rom_id, app_id):
        rom_id = library.resolve(rom_id)
        library.set_app_id(rom_id, app_id)

    async def cover(self, rom_id):
        rom_id = library.resolve(rom_id)
        try:
            return await asyncio.to_thread(library.cover, RomM.from_settings(), rom_id)
        except Exception:
            return None

    async def bios(self, platform_id):
        names = await self._call(lambda c: library.install_firmware(c, platform_id))
        if isinstance(names, dict):
            return names
        return {"ok": True, "count": len(names)}

    # ---------- saves ----------

    async def game_saves(self, rom_id, mode):
        """One game's saves. mode: sync (newest wins) | push (this PC wins) | pull (RomM wins).
        push and pull keep the losing side's copy on RomM as backup-<time>-<name>."""
        rom_id = library.resolve(rom_id)
        game = library.installed().get(str(rom_id))
        if not game or not saves.emu_for(game):
            return {"ok": False, "error": "Saves aren't synced for this game"}
        direction, force = {"sync": ("both", False), "push": ("push", True), "pull": ("pull", True)}[mode]
        try:
            r = await asyncio.to_thread(saves.sync, RomM.from_settings(), str(rom_id), game, direction, force)
            return {"ok": True, **r}
        except Exception as e:
            decky.logger.exception("Saves (%s) failed for rom %s", mode, rom_id)
            return {"ok": False, "error": str(e)}

    async def game_closed(self, app_id=None):
        """Steam says a game stopped (the panel listens for that). Pushes its saves and puts
        controller settings back, in case Steam's "Exit game" closed our launcher before it could.
        Waits for the emulator to finish writing (and for the launcher, if it's still doing this).
        Then the game's Steam page catches up (new saves, last played)."""
        for _ in range(60):  # up to ~3 minutes
            try:
                await asyncio.to_thread(session.finish)
            except Exception:
                decky.logger.exception("Finishing a closed game failed")
            if not session.pending():
                break
            await asyncio.sleep(3)
        rid = next((r for r, g in library.installed().items() if app_id and str(g.get("app_id")) == str(app_id)), None)
        if rid:
            self._refresh_details([rid])

    # ---------- emulator settings ----------

    async def autoload_status(self):
        """Emulators still set to load the last save state when a game starts."""
        return await asyncio.to_thread(autoload.status)

    async def autoload_off(self):
        return await asyncio.to_thread(autoload.turn_off)

    async def sync_saves(self, rom_id=None):
        """Sync one game, or every downloaded game when rom_id is None."""
        games = library.installed()
        ids = [str(rom_id)] if rom_id else list(games)
        done, failed = 0, []
        for rid in ids:
            game = games.get(rid)
            if not game or not saves.emu_for(game):
                continue
            try:
                await asyncio.to_thread(saves.sync, RomM.from_settings(), rid, game)
                done += 1
            except Exception as e:
                decky.logger.exception("Save sync failed for rom %s", rid)
                failed.append(f"{games[rid]['name']}: {e}")
        return {"done": done, "failed": failed}

    # ---------- helper ----------

    async def _call(self, fn):
        """Run a RomM request off the event loop; errors come back as {'error': ...}."""
        try:
            return await asyncio.to_thread(fn, RomM.from_settings())
        except RomMError as e:
            return {"error": str(e)}
