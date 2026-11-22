// src/links.ts: the plugin only opens pages on the configured RomM server, or the sites RomM links games to.
import { loadSource } from "./load_source.mjs";

const { allowedLink } = await loadSource("links.ts");

let fails = 0;
const check = (ok, m) => { console.log((ok ? "PASS " : "FAIL ") + m); if (!ok) fails++; };
const server = "http://romm.lan:8080";

check(allowedLink("http://romm.lan:8080/rom/12", server), "the RomM server's own game page opens");
check(allowedLink("http://ROMM.lan:8080/rom/12", server + "/"), "case and a trailing slash don't matter");
check(!allowedLink("http://romm.lan:9999/rom/12", server), "another port on the same host doesn't");
check(!allowedLink("https://romm.lan:8080/rom/12", server), "another scheme doesn't");
check(!allowedLink("http://evil.example/rom/12", server), "another server doesn't");
check(!allowedLink("http://romm.lan:8080@evil.example/rom/12", server), "a user-info trick doesn't");
check(allowedLink("https://retroachievements.org/game/1", server), "RetroAchievements opens");
check(allowedLink("https://howlongtobeat.com/game/2", server), "HowLongToBeat opens");
check(allowedLink("https://www.youtube.com/watch?v=abc", server), "a YouTube trailer opens");
check(!allowedLink("http://www.youtube.com/watch?v=abc", server), "...but not over plain http");
check(!allowedLink("https://retroachievements.org.evil.example/game/1", server), "a look-alike host doesn't");
check(!allowedLink("javascript:alert(1)", server), "javascript: never opens");
check(!allowedLink("file:///etc/passwd", server), "file: never opens");
check(!allowedLink("not a url", server), "garbage never opens");
check(!allowedLink("http://romm.lan:8080/rom/12", ""), "no server configured: RomM links don't open");

console.log(`\n${fails} failures`);
process.exit(fails ? 1 : 0);
