// Which web pages the plugin opens. Links come from RomM (and are kept on this PC for the Steam pages), so
// before one opens it's checked: the configured RomM server's own pages, or the few sites RomM links games
// to, over https. Anything else (another server, a stale link from a server you've since left) is ignored.

/** The sites RomM matches games to, which the Steam page's buttons may open (https only). */
const SITES = new Set(["retroachievements.org", "howlongtobeat.com", "www.youtube.com"]);

/** "http://romm.lan:8080" for an address, with the default port left out, or "" if it isn't a web address. */
function origin(address: string): string {
  try {
    const u = new URL(address);
    return u.protocol === "http:" || u.protocol === "https:" ? u.origin : "";
  } catch {
    return "";
  }
}

/** May the plugin open `url`? Yes for a page on `server` (RomM's address as configured), or an https page
 * of one of the known sites. */
export function allowedLink(url: string, server: string): boolean {
  const mine = origin(server);
  const theirs = origin(url);
  if (!theirs) return false;
  if (mine && theirs === mine) return true;
  try {
    const u = new URL(url);
    return u.protocol === "https:" && !u.username && !u.password && !u.port && SITES.has(u.hostname);
  } catch {
    return false;
  }
}
