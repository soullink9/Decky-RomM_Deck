// RomM's details on Steam's own game page (Game Mode), for the cards RomM Deck made or took over.
//
// Steam only shows a game's info section (description, developer, release date, rating, feature
// icons) for games it believes are Steam games. So, for a RomM Deck card, and only while that
// card's own page is open, Steam is told it's not a shortcut; everywhere else it gets the truth.
// The same approach as the MetaDeck and Decky Metadata plugins, with their safeguards:
//  * Steam's launch and id lookups (GetGameID, GetPrimaryAppID, the icon) always get the truth,
//    so Play keeps working;
//  * data is only handed over once Steam has set up the page itself (earlier makes Steam crash);
//  * every patched function falls back to Steam's own answer on any error.
// On top of the info section, the page gets RomM's screenshots, an Activity list (notes,
// RetroAchievements unlocks, saves) and RomM links in place of Steam's store/community buttons.
// Nothing is written to Steam's files; stop() puts every function back. The panel has an off switch.
import { React, callable, addEventListener, removeEventListener, Focusable, Navigation } from "./decky";
import { Icon, IconName } from "./ui";

declare const PLUGIN_NAME: string; // filled in from plugin.json by build.mjs

export type Activity = { at: number; kind: string; title: string; body: string; by: string; image: string };
export type Details = {
  description: string; developers: string[]; publishers: string[]; release_date: number | null;
  rating: number | null; features: number[]; facts: [string, string][];
  links?: [string, string][]; activity?: Activity[]; screenshots?: string[];  // (optional: not every game has them)
};

const w = window as any;
const SHORTCUT = 1073741824;  // app_type of a non-Steam game
let details: Record<string, Details> = {};
let enabled = true;
let truth = 0;  // > 0: inside a Steam call that must see the real answer
let live = false;  // patches installed (pieces Steam keeps hold of check this, and do nothing once stopped)
const undos: (() => void)[] = [];
// RomM's screenshots, as Decky serves the copies the backend made (Steam's https pages can't load
// pictures from a plain-http RomM, but they do load from Decky on this PC)
const DATA = `http://localhost:1337/plugins/${encodeURIComponent(typeof PLUGIN_NAME === "string" ? PLUGIN_NAME : "RomM Deck")}/data/`;
const scores = new Map<any, any>();  // overview -> its own metacritic_score, to put back
// What Steam was given per game, reused until RomM's details change: handing Steam new but equal
// objects makes it redraw the page (and can keep it redrawing).
type Made = { d: Details; desc: any; assoc: any; shots: any[] };
const made = new Map<number, Made>();
function madeFor(appId: number, d: Details) {
  let m = made.get(appId);
  if (!m || m.d !== d) {
    const people = (list: string[]) => list.map((name) => ({ strName: name, strURL: "" }));
    m = {
      d,
      desc: { strFullDescription: <RommDetails d={d} />, strSnippet: d.description },
      assoc: { rgDevelopers: people(d.developers), rgPublishers: people(d.publishers), rgFranchises: [] },
      shots: (d.screenshots || []).slice(0, 10).map((path, i) => {  // the fields Steam's screenshot list reads
        const url = DATA + path;
        return { appid: appId, id: `romm-${appId}-${i}`, nScreenshotID: i + 1, strCaption: "", strImageURL: url, strThumbnailURL: url,
          strURL: url, url, nWidth: 1280, nHeight: 720, width: 1280, height: 720, bSpoiler: false };
      }),
    };
    made.set(appId, m);
  }
  return m;
}

const ours = (appId: number): Details | undefined => (enabled ? details[String(appId)] : undefined);

/** Replace obj[name] with wrap(original); remember exactly how to undo it. */
function patch(obj: any, name: string, wrap: (original: any) => any) {
  if (!obj || typeof obj[name] !== "function") return;
  const original = obj[name];
  const own = Object.prototype.hasOwnProperty.call(obj, name);
  obj[name] = wrap(original);
  undos.push(() => { if (own) obj[name] = original; else delete obj[name]; });
}

/** Steam's stores only accept changes while state changes are allowed. */
function change(block: () => void) {
  const g = w.__mobxGlobals;
  const before = g?.allowStateChanges;
  if (g) g.allowStateChanges = true;
  try { block(); } finally { if (g) g.allowStateChanges = before; }
}

/** The app id of the Steam game page that's open (0 if none). */
function pageAppId(): number {
  const win = w.SteamUIStore?.WindowStore?.GamepadUIMainWindowInstance || w.Router?.WindowStore?.GamepadUIMainWindowInstance;
  const path: string = win?.m_history?.location?.pathname || win?.m_locationPathname || "";
  return Number(path.match(/\/library\/(?:app|details|[^/]+\/app)\/(\d+)/)?.[1]) || 0;
}

/** Steam's play bar reads these while a page opens; a shortcut's can be missing (Decky Metadata's fix). */
function safeFields(appId: number) {
  try {
    const d = w.appDetailsStore?.GetAppData?.(appId)?.details;
    if (!d) return;
    if (!w.appStore?.GetAppOverviewByAppID?.(Number(d.unAppID))) d.unAppID = appId;
    for (const k of ["vecDLC", "vecChildConfigApps", "vecScreenShots"]) if (!Array.isArray(d[k])) d[k] = [];
  } catch { /* best effort only */ }
}

// ---------- screenshots ----------

// What each game's screenshot fields held before RomM's were added, and what was put there
const shotsBefore = new Map<number, { data: any; vec: any; n: any; shots: any }>();
const shotsSet = new Map<number, { m: Made; vec: any[] }>();

/** RomM's screenshots after any of the player's own Steam ones (once Steam has set the page up). */
function applyShots(appId: number, data: any, m: Made) {
  const det = data?.details;
  if (!det || !m.shots.length) return;
  const set = shotsSet.get(appId);
  if (set && set.m === m && det.vecScreenShots === set.vec) return;  // already there
  if (!shotsBefore.has(appId)) shotsBefore.set(appId, { data, vec: det.vecScreenShots, n: det.nScreenshots, shots: data.screenshots });
  const theirs = (Array.isArray(det.vecScreenShots) ? det.vecScreenShots : []).filter((x: any) => !String(x?.id).startsWith("romm-"));
  const vec = [...theirs, ...m.shots];
  shotsSet.set(appId, { m, vec });
  change(() => {
    det.vecScreenShots = vec;
    det.nScreenshots = vec.length;
    data.screenshots = { rgScreenshots: vec, screenshots: vec, vecScreenshots: vec, vecScreenShots: vec };
    w.appDetailsCache?.SetCachedDataForApp?.(appId, "screenshots", 1, data.screenshots);
  });
}

/** Steam's own screenshot fields back (switched off, or unloading). */
function restoreShots() {
  change(() => {
    for (const [appId, b] of shotsBefore) {
      const det = b.data?.details;
      if (det && det.vecScreenShots === shotsSet.get(appId)?.vec) {
        det.vecScreenShots = b.vec;
        det.nScreenshots = b.n;
        b.data.screenshots = b.shots;
      }
    }
  });
  shotsBefore.clear();
  shotsSet.clear();
}

// ---------- finding Steam's page pieces ----------

/** A class or function in Steam's own code (via Decky's module search), or undefined. */
function findInSteam(test: (x: any) => boolean) {
  try {
    return w.DFL?.findModuleChild?.((m: any) => {
      if (!m || typeof m !== "object") return undefined;
      for (const k in m) {
        try { if (test(m[k])) return m[k]; } catch { /* next */ }
      }
      return undefined;
    });
  } catch { return undefined; }
}

const isElement = (x: any) => !!x && typeof x === "object" && typeof x.$$typeof === "symbol" && String(x.$$typeof).includes("react.");
const has = (el: any, ...keys: string[]) => !!el?.props && typeof el.props === "object" && keys.every((k) => k in el.props);

/** React elements under `root` that pass `test`, nearest first. Only follows children (never
 * other props: walking into Steam's stores would make the page re-render without end). */
function findElements(root: any, test: (el: any) => boolean, max = 8) {
  const out: any[] = [], queue = [root];
  for (let budget = 500; queue.length && budget > 0 && out.length < max; budget--) {
    const node = queue.shift();
    if (Array.isArray(node)) { queue.push(...node); continue; }
    if (!isElement(node)) continue;
    try { if (test(node)) { out.push(node); continue; } } catch { /* not this one */ }
    const kids = node.props?.children;
    if (kids && typeof kids === "object") queue.push(kids);
  }
  return out;
}

/** A short outline of a page piece (element names and prop names), for the log. */
function outline(root: any) {
  const lines: string[] = [];
  const walk = (node: any, depth: number) => {
    if (lines.length > 40 || depth > 5) return;
    if (Array.isArray(node)) return node.forEach((n) => walk(n, depth));
    if (!isElement(node)) return;
    const t = node.type, name = typeof t === "string" ? t : t?.displayName || t?.name || (typeof t === "object" ? "object" : "anonymous");
    lines.push(`${"  ".repeat(depth)}${name} {${Object.keys(node.props || {}).join(",")}}`);
    const kids = node.props?.children;
    if (kids && typeof kids === "object") walk(kids, depth + 1);
  };
  walk(root, 0);
  return lines.join("\n");
}
const logged = new Set<string>();
function logOnce(what: string, root: any) {
  if (logged.has(what)) return;
  logged.add(what);
  callable<[string]>("log_steam_page")(`${what}\n${outline(root)}`).catch(() => {});
}

// ---------- the Game Info buttons: RomM's links instead of Steam's store/community ones ----------

function openWeb(url: string) {
  try { if (Navigation?.NavigateToExternalWeb) return Navigation.NavigateToExternalWeb(url); } catch { /* next */ }
  try { w.SteamClient?.System?.OpenInSystemBrowser?.(url); } catch { /* nothing else to try */ }
}

/** Takes the place of Steam's row of links (Store page, Community, Discussions, Support...). */
export function RommLinks(props: any) {
  const d = ours(Number(props?.overview?.appid) || pageAppId());
  if (!d?.links?.length) return null;
  const Button = w.DFL?.DialogButton || "button";
  return (
    <Focusable style={{ display: "flex", flexWrap: "wrap", gap: "8px", margin: "12px 0" }} flow-children="horizontal">
      {d.links.map(([label, url]) => (
        <Button key={url} style={{ width: "auto", minWidth: 0, padding: "8px 18px", display: "flex", alignItems: "center", gap: "8px" }}
          onClick={() => openWeb(url)}>
          <Icon name="open" size={16} />{label}
        </Button>
      ))}
    </Focusable>
  );
}

const infoWrappers = new Map<any, any>();
/** Steam's info section body, with its links row swapped for RommLinks. */
function infoWrapper(original: any) {
  let wrapper = infoWrappers.get(original);
  if (!wrapper) {
    wrapper = (props: any) => {
      const out = original(props);
      try {
        if (live && ours(Number(props?.overview?.appid))) {
          const rows = findElements(out, isLinksRow);
          for (const row of rows) row.type = RommLinks;
          if (!rows.length) logOnce("Game Info: no links row found", out);
        }
      } catch { /* Steam's own buttons */ }
      return out;
    };
    wrapper.__rommDeck = true;
    infoWrappers.set(original, wrapper);
  }
  return wrapper;
}

const isLinksRow = (el: any) => has(el, "overview", "details", "workshopVisible", "marketPresence");

function intoInfo(section: any) {
  for (const row of findElements(section, isLinksRow)) row.type = RommLinks;  // (if Steam ever draws it here directly)
  const bodies = findElements(section, (el) => typeof el.type === "function" && !el.type.prototype?.isReactComponent
    && !el.type.__rommDeck && !isLinksRow(el) && has(el, "overview", "details"));
  for (const el of bodies) el.type = infoWrapper(el.type);
  if (!bodies.length && !findElements(section, (el) => el.type?.__rommDeck).length) logOnce("Game Info: no body found", section);
}

// ---------- Activity ----------

const KIND_ICONS: Record<string, IconName> = {
  note: "note", achievement: "trophy", award: "trophy", save: "save", state: "save", played: "gamepad", sync: "sync", "sync-failed": "warning",
};

/** RomM's activity for a game: notes, RetroAchievements unlocks, saves and states, sync results. */
export function RommActivity({ d }: { d: Details }) {
  const items = d.activity || [];
  const days: [string, Activity[]][] = [];
  for (const e of items) {
    const day = new Date(e.at * 1000).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
    if (days.length && days[days.length - 1][0] === day) days[days.length - 1][1].push(e);
    else days.push([day, [e]]);
  }
  const romm = d.links?.find(([label]) => label === "RomM")?.[1];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "4px", margin: "8px 0 16px" }}>
      {days.map(([day, events]) => (
        <div key={day} style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <div style={{ fontSize: "12px", textTransform: "uppercase", letterSpacing: "0.06em", opacity: 0.6, margin: "10px 0 2px" }}>{day}</div>
          {events.map((e, i) => (
            <Focusable key={i} onActivate={() => { if (e.kind === "note" && romm) openWeb(romm); }}
              style={{ display: "flex", gap: "14px", alignItems: "flex-start", padding: "12px 14px", borderRadius: "4px", background: "rgba(255,255,255,0.06)" }}>
              {e.image
                ? <img src={e.image} width={44} height={44} style={{ borderRadius: "4px", flex: "none" }} />
                : <div style={{ width: "44px", height: "44px", flex: "none", display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "4px", background: "rgba(255,255,255,0.08)" }}>
                    <Icon name={KIND_ICONS[e.kind] || "sync"} size={22} />
                  </div>}
              <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: "4px" }}>
                <div style={{ fontWeight: 600 }}>{e.title}</div>
                {e.body && <div style={{ whiteSpace: "pre-line", lineHeight: 1.4, opacity: 0.8, overflowWrap: "anywhere" }}>{e.body}</div>}
                <div style={{ fontSize: "12px", opacity: 0.5 }}>
                  {new Date(e.at * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}{e.by ? ` · ${e.by}` : ""} · {e.kind.startsWith("sync") ? "this PC" : "RomM"}
                </div>
              </div>
            </Focusable>
          ))}
        </div>
      ))}
    </div>
  );
}

/** Steam's Activity section, with RomM's list added at its end (Steam's own part is left as it is). */
function intoActivity(section: any, d: Details) {
  if (!d.activity?.length || !isElement(section)) return section;
  const kids = section.props?.children;
  if (typeof kids === "function") { logOnce("Activity: no place for RomM's list", section); return section; }
  return React.cloneElement(section, undefined, kids, <RommActivity key="romm-deck-activity" d={d} />);
}

// ---------- the page ----------

const opened = new Map<number, number>();
/** A page was opened: the backend catches up on its notes/saves if they're old (at most every 10 min). */
function pageOpened(appId: number) {
  if (Date.now() - (opened.get(appId) || 0) < 10 * 60 * 1000) return;
  opened.set(appId, Date.now());
  callable<[number]>("page_opened")(appId).catch(() => {});
}

/** RomM's details, shown as the game's description: the summary, then every other fact. */
export function RommDetails({ d }: { d: Details }) {
  return (
    <Focusable style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
      {d.description && <div style={{ whiteSpace: "pre-line", lineHeight: 1.5 }}>{d.description}</div>}
      {d.facts.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "max-content 1fr", columnGap: "18px", rowGap: "8px" }}>
          {d.facts.map(([label, value]) => (
            <React.Fragment key={label}>
              <div style={{ fontSize: "12px", textTransform: "uppercase", letterSpacing: "0.06em", opacity: 0.6, paddingTop: "2px" }}>{label}</div>
              <div style={{ lineHeight: 1.4 }}>{value}</div>
            </React.Fragment>
          ))}
        </div>
      )}
      <div style={{ fontSize: "12px", opacity: 0.45 }}>Details from RomM</div>
    </Focusable>
  );
}

function applyScores() {
  change(() => {
    for (const o of w.appStore?.allApps || []) {
      if (o?.app_type !== SHORTCUT) continue;
      const d = ours(o.appid);
      if (d?.rating) {
        if (!scores.has(o)) scores.set(o, o.metacritic_score);
        o.metacritic_score = d.rating;
      } else if (scores.has(o)) {
        o.metacritic_score = scores.get(o);
        scores.delete(o);
      }
    }
  });
}

export function start(tries = 12): () => void {
  const store = w.appDetailsStore, apps = w.appStore;
  if (!store || !apps?.allApps?.length) {  // Steam's library isn't loaded yet: try again shortly
    let stop = () => {};
    const timer = tries > 0 ? setTimeout(() => { stop = start(tries - 1); }, 5000) : undefined;
    return () => { clearTimeout(timer); stop(); };
  }
  const detailsProto = Object.getPrototypeOf(store);
  const overviewProto = Object.getPrototypeOf(apps.allApps[0]);

  // Launching and id lookups always see the truth
  const truthful = (original: any) => function (this: any, ...args: any[]) {
    truth++;
    try { return original.apply(this, args); } finally { truth--; }
  };
  patch(overviewProto, "GetGameID", truthful);
  patch(overviewProto, "GetPrimaryAppID", truthful);
  patch(apps, "GetIconURLForApp", truthful);

  // On a RomM Deck card's own page, Steam renders its info section as for a Steam game
  patch(overviewProto, "BIsModOrShortcut", (original) => function (this: any, ...args: any[]) {
    const real = original.apply(this, args);
    try {
      if (real !== true || truth > 0 || this?.app_type !== SHORTCUT) return real;
      return ours(this.appid) && pageAppId() === this.appid ? false : real;
    } catch { return real; }
  });

  patch(detailsProto, "GetDescriptions", (original) => function (this: any, appId: number, ...rest: any[]) {
    const real = original.call(this, appId, ...rest);
    try {
      const d = ours(appId);
      const data = d && store.GetAppData?.(appId);
      if (!data?.details) return real;  // Steam hasn't set the page up yet: leave it alone
      safeFields(appId);
      const m = madeFor(appId, d!);
      if (data.descriptionsData !== m.desc) change(() => {
        data.descriptionsData = m.desc;
        w.appDetailsCache?.SetCachedDataForApp?.(appId, "descriptions", 1, m.desc);
      });
      try { applyShots(appId, data, m); } catch { /* the page just has no screenshots */ }
      return m.desc;
    } catch { return real; }
  });

  patch(detailsProto, "GetAssociations", (original) => function (this: any, appId: number, ...rest: any[]) {
    const real = original.call(this, appId, ...rest);
    try {
      const d = ours(appId);
      const data = d && store.GetAppData?.(appId);
      if (!data?.details || !(d!.developers.length || d!.publishers.length)) return real;
      safeFields(appId);
      const m = madeFor(appId, d!);
      if (data.associationData !== m.assoc) change(() => {
        data.associationData = m.assoc;
        w.appDetailsCache?.SetCachedDataForApp?.(appId, "associations", 1, m.assoc);
      });
      return m.assoc;
    } catch { return real; }
  });

  patch(overviewProto, "GetCanonicalReleaseDate", (original) => function (this: any, ...args: any[]) {
    try {
      const d = this?.app_type === SHORTCUT ? ours(this.appid) : undefined;
      if (d?.release_date) return d.release_date;
    } catch { /* Steam's own answer */ }
    return original.apply(this, args);
  });

  patch(overviewProto, "BHasStoreCategory", (original) => function (this: any, category: number, ...rest: any[]) {
    try {
      if (this?.app_type === SHORTCUT && ours(this.appid)?.features.includes(Number(category))) return true;
    } catch { /* Steam's own answer */ }
    return original.call(this, category, ...rest);
  });

  // Which sections the page has: Screenshots and Activity too, when RomM has some
  const Sections = findInSteam((c) => typeof c?.prototype?.GetSections === "function");
  patch(Sections?.prototype, "GetSections", (original) => function (this: any, ...args: any[]) {
    const ret = original.apply(this, args);
    try {
      const appId = Number(this?.props?.overview?.appid);
      const d = this?.props?.overview?.app_type === SHORTCUT ? ours(appId) : undefined;
      if (d && ret) {
        const add = (name: string) => { if (typeof ret.add === "function") ret.add(name); else if (Array.isArray(ret) && !ret.includes(name)) ret.push(name); };
        if (d.screenshots?.length) add("screenshots");
        if (d.activity?.length) add("activity");
        pageOpened(appId);
      }
    } catch { /* Steam's own sections */ }
    return ret;
  });

  // Each section as it's drawn: the Game Info buttons and the Activity list
  const Section = findInSteam((c) => typeof c === "function" && c.prototype?.isReactComponent
    && typeof c.prototype.render === "function" && String(c.prototype.render).includes("RegisterSection"));
  patch(Section?.prototype, "render", (original) => function (this: any, ...args: any[]) {
    const ret = original.apply(this, args);
    try {
      const name = this?.props?.name;
      if (name !== "info" && name !== "activity") return ret;
      const appId = Number(this?.props?.overview?.appid) || pageAppId();
      const d = ours(appId);
      if (!d) return ret;
      if (name === "info") { intoInfo(ret); return ret; }
      return intoActivity(ret, d);
    } catch { return ret; }
  });
  if (!Sections || !Section) callable<[string]>("log_steam_page")(`Steam's page parts not found (sections: ${!!Sections}, section: ${!!Section})`).catch(() => {});
  live = true;

  load();
  const onDetails = addEventListener("steam_details", (m: Record<string, Details>) => { received++; use(m); });

  return () => {
    removeEventListener("steam_details", onDetails);
    live = false;
    const was = enabled;
    enabled = false;
    applyScores();  // Steam's own scores back
    try { restoreShots(); } catch { /* best effort */ }
    enabled = was;
    while (undos.length) undos.pop()!();
    infoWrappers.clear();
    details = {};
  };
}

/** The panel's switch: on or off right away (Steam's own answers return when off). */
export function setEnabled(on: boolean) {
  enabled = on;
  try { applyScores(); } catch { /* a later page view uses the new setting anyway */ }
  if (!on) try { restoreShots(); } catch { /* best effort */ }
}

/** A card was just made or taken over: fetch its details (they arrive as a 'steam_details' event). */
export function refresh() {
  load();
}

let received = 0;  // 'steam_details' events so far: an answer asked for before the latest one is older
function use(m: Record<string, Details>) {
  details = m || {};
  applyScores();
}
function load() {
  const asked = received;
  callable<[], Record<string, Details>>("steam_details")().then((m) => { if (received === asked) use(m); }).catch(() => {});
}
