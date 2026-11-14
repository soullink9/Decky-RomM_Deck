// The Quick Access Menu panel, and the plugin's entry point (the default export at the bottom).
//
// Every button calls a method of the Python Plugin class in main.py through `api` below. The panel
// is a small set of pages (home, a list of platforms or collections, a list of games, one game),
// switched with `go(page)`; Decky rebuilds the panel each time the menu opens, so the current page
// is kept in a module variable (`lastPage`) to reopen where you were.
import {
  React, useState, useEffect, useRef, PanelSection, PanelSectionRow, ButtonItem, TextField, ToggleField, Field,
  staticClasses, Navigation, callable, addEventListener, removeEventListener, toast, useQuickAccessVisible,
} from "./decky";
import { addCard, removeCard, takeOver, takeOverAll, repairCards, cardIsGame } from "./cards";
import { currentGame } from "./current";
import { Icon, Label, Cover, GameRow, Status, ago, GREEN, AMBER, GREY } from "./ui";
import { start as startSteamPages, refresh as refreshSteamPages, setEnabled as showOnSteamPages } from "./steampage";

// The shapes the backend's methods return (see main.py), as the panel uses them.
/** A platform or collection to browse ("kind" says which, and for collections, smart or regular). */
type Collection = { kind: string; id: number; name: string; count: number };
/** A game in a list. */
type Rom = { id: number; name: string; platform: string; installed: boolean; cover?: string };
/** A game's own page: everything the panel shows about it, including its controller preset. */
type Game = Rom & {
  platform_id: number; size_mb: number; playable: boolean; app_id: number | null; downloading: number | null;
  extras: number; extras_on_pc: number; extras_dir: string;
  syncs: boolean; saves: { ok: boolean; at: number; error: string } | null;
  about: { developers: string[]; release_date: number | null };
  preset: { platform: string; label: string; about: string; motion: boolean; on: boolean; calibrated: boolean; last: string } | null;
};
/** Where the panel is: each page remembers the one to go back to. */
type Page =
  | { page: "home" }
  | { page: "pick"; kind: "platforms" | "collections" }
  | { page: "list"; title: string; kind: string; id: number | string; back: Page }
  | { page: "game"; id: number; back: Page; playing?: boolean; appId?: number; auto?: boolean };
/** What a backend method returns when it failed. */
type Err = { error: string };
/** A download in progress, as the home page lists it. */
type Download = { id: number; name: string; percent: number };
type GamePageView = Extract<Page, { page: "game" }>;
/** A save sync's outcome: files sent up and down, saves from other emulators left alone, files on RomM. */
type SavesResult = { ok: boolean; error?: string; up?: number; down?: number; other?: string[]; on_romm?: number };

/** The backend's methods (main.py), typed. Names match the Python methods. */
const api = {
  status: callable<[], { connected: boolean; url: string }>("status"),
  connect: callable<[url: string, code: string], { ok: boolean; error?: string }>("connect"),
  disconnect: callable("disconnect"),
  collections: callable<[], Collection[] | Err>("collections"),
  platforms: callable<[], Collection[] | Err>("platforms"),
  roms: callable<[kind: string, key: number | string], Rom[] | Err>("roms"),
  installed: callable<[], Rom[]>("installed"),
  scan: callable<[], { found: number; relinked: string[]; lost: string[] } | Err>("scan"),
  game: callable<[id: number], Game | Err>("game"),
  download: callable<[id: number, name: string]>("download"),
  downloads: callable<[], Download[]>("downloads"),
  uninstall: callable<[id: number], { ok: boolean; error?: string; app_id?: number | null; deleted?: string[]; kept?: string[] }>("uninstall"),
  bios: callable<[platformId: number], { ok: boolean; count: number } | Err>("bios"),
  downloadExtras: callable<[id: number, name: string]>("download_extras"),
  setPreset: callable<[platform: string, on: boolean], { ok: boolean; error?: string }>("set_preset"),
  calibrateMotion: callable<[], { ok: boolean; error?: string }>("calibrate_motion"),
  options: callable<[], { steam_pages: boolean; switch_extras_dir: string; switch_extras_dir_from_ryujinx: boolean }>("options"),
  setOption: callable<[key: string, value: string | boolean]>("set_option"),
  syncSaves: callable<[id?: number], { done: number; failed: string[] }>("sync_saves"),
  gameSaves: callable<[id: number, mode: "sync" | "push" | "pull"], SavesResult>("game_saves"),
  autoloadStatus: callable<[], string[]>("autoload_status"),
  autoloadOff: callable<[], string[]>("autoload_off"),
  summary: callable<[], { on_pc: number; platforms?: number; collections?: number }>("summary"),
};

/** The game page's save buttons: [backend mode, label, description, icon]. */
const SAVE_BUTTONS: ["sync" | "push" | "pull", string, string, "sync" | "up" | "down"][] = [
  ["sync", "Sync", "Newest copy wins, here or on RomM", "sync"],
  ["push", "Push to RomM", "This PC's saves replace RomM's", "up"],
  ["pull", "Pull from RomM", "RomM's saves replace this PC's", "down"],
];

/** "On this PC · 23" */
const counted = (label: string, n?: number) => (n === undefined ? label : `${label} · ${n}`);

/** The "Back" button at the top of every page but home. */
function Back({ go }: { go: () => void }) {
  return <PanelSectionRow><ButtonItem layout="below" onClick={go}><Label icon="back">Back</Label></ButtonItem></PanelSectionRow>;
}

/** Did the backend answer with an error ({ error: "..." }) instead of data? */
const isErr = (x: any): x is Err => x && typeof x === "object" && "error" in x;

/** A dangerous button's two-press confirmation: the first press arms it, and it disarms by itself
 * after 5 seconds, so a stray second press much later can't delete anything. */
function useConfirm(): [boolean, (on: boolean) => void] {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 5000);
    return () => clearTimeout(timer);
  }, [armed]);
  return [armed, setArmed];
}

// ---------- pages ----------

/** First run (or after Disconnect): the RomM address and a pairing code or token. */
function Setup({ onDone }: { onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  /** Pair with RomM (the backend exchanges a code for a token, then tests it). */
  const connect = async () => {
    setMsg("Connecting…");
    const r = await api.connect(url, code);
    if (r.ok) onDone();
    else setMsg(r.error || "Couldn't connect");
  };
  return (
    <PanelSection title="Connect to RomM">
      <PanelSectionRow>
        <TextField label="RomM address" description="e.g. https://romm.example.com" value={url}
          onChange={(e: any) => setUrl(e.target.value)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField label="Pairing code or token"
          description="RomM web: Settings > Client API Tokens > Pair device. Codes expire after 60 seconds."
          value={code} onChange={(e: any) => setCode(e.target.value)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={connect} disabled={!url || !code}>Connect</ButtonItem>
      </PanelSectionRow>
      {msg && <PanelSectionRow><Field description={msg} /></PanelSectionRow>}
    </PanelSection>
  );
}

/** The home page: downloads in progress, ways into the library, and settings. */
function Home({ go, url, onDisconnect }: { go: (p: Page) => void; url: string; onDisconnect: () => void }) {
  const [search, setSearch] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [counts, setCounts] = useState({} as { on_pc?: number; platforms?: number; collections?: number });
  useEffect(() => { api.summary().then(setCounts).catch(() => {}); }, []);
  const home: Page = { page: "home" };

  /** Sync every downloaded game's saves, then say how it went. */
  const syncAll = async () => {
    setSyncing(true);
    const r = await api.syncSaves();
    setSyncing(false);
    toast("RomM saves", r.failed.length ? `${r.failed.length} failed: ${r.failed[0]}` : `Synced ${r.done} games`);
  };

  return (
    <>
      <Downloads go={go} back={home} />
      <PanelSection title="Library">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => go({ page: "list", title: "On this PC", kind: "installed", id: 0, back: home })}>
            <Label icon="pc">{counted("On this PC", counts.on_pc)}</Label>
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => go({ page: "pick", kind: "platforms" })}>
            <Label icon="grid">{counted("Platforms", counts.platforms)}</Label>
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => go({ page: "pick", kind: "collections" })}>
            <Label icon="stack">{counted("Collections", counts.collections)}</Label>
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField label="Search RomM" value={search} onChange={(e: any) => setSearch(e.target.value)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!search.trim()}
            onClick={() => go({ page: "list", title: `"${search.trim()}"`, kind: "search", id: search.trim(), back: home })}>
            <Label icon="search">Search</Label>
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Saves">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={syncAll} disabled={syncing}>
            <Label icon="sync">{syncing ? "Syncing…" : "Sync all saves now"}</Label>
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <AutoloadSection />
      <PanelSection title="RomM">
        <PanelSectionRow><Field label="Server" description={url} /></PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={async () => { await api.disconnect(); onDisconnect(); }}>
            <Label icon="power">Disconnect</Label>
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

/** The folder Switch updates and DLC download into (Ryujinx's own, if it has one set). */
function ExtrasFolder() {
  const [dir, setDir] = useState("");
  const [fromRyujinx, setFromRyujinx] = useState(false);
  const [saved, setSaved] = useState("");
  useEffect(() => {
    api.options().then((o: { switch_extras_dir: string; switch_extras_dir_from_ryujinx: boolean }) => {
      setDir(o.switch_extras_dir); setSaved(o.switch_extras_dir); setFromRyujinx(o.switch_extras_dir_from_ryujinx);
    });
  }, []);
  return (
    <>
      <PanelSectionRow>
        <TextField label="Switch updates & DLC folder" value={dir} onChange={(e: any) => setDir(e.target.value)}
          description={fromRyujinx && dir === saved ? "Found in Ryujinx's settings (a folder it loads updates and DLC from)"
            : "Switch updates and DLC download here, not into roms/switch"} />
      </PanelSectionRow>
      {dir !== saved && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={async () => { await api.setOption("switch_extras_dir", dir); setSaved(dir); setFromRyujinx(false); }}>
            <Label icon="folder">Save folder</Label>
          </ButtonItem>
        </PanelSectionRow>
      )}
    </>
  );
}

/** The off switch for everything RomM Deck shows on Steam's game pages (src/steampage.tsx). */
function SteamPagesSwitch() {
  const [on, setOn] = useState(null as boolean | null);
  useEffect(() => { api.options().then((o) => setOn(o.steam_pages !== false)).catch(() => setOn(true)); }, []);
  return (
    <PanelSectionRow>
      <ToggleField label={<Label icon="open">RomM details on Steam game pages</Label>} checked={!!on} disabled={on === null}
        description="Description, developer, release date, rating and everything else RomM knows, on the Steam page of games with a RomM Deck card"
        onChange={async (v: boolean) => { setOn(v); showOnSteamPages(v); await api.setOption("steam_pages", v); }} />
    </PanelSectionRow>
  );
}

/** Takes over every existing Steam card RomM knows the game of, so it syncs saves (src/cards.ts). */
function CardsButton() {
  const [state, setState] = useState("");
  /** Check every non-Steam card, showing how far it's got. */
  const go = async () => {
    setState("Starting…");
    const n = await takeOverAll((done, total) => setState(`Checking card ${done + 1} of ${total}…`));
    setState("");
    if (n) refreshSteamPages();  // their Steam pages get RomM's details
    toast("Steam cards", n ? `${n} cards now sync saves automatically` : "No more cards to change");
  };
  return (
    <PanelSectionRow>
      <ButtonItem layout="below" disabled={!!state} onClick={go}
        description={state || "Makes your existing cards (EmuDeck's) pull saves before you play and push them after. Names, artwork and playtime stay."}>
        <Label icon="card">Sync saves on all my Steam cards</Label>
      </ButtonItem>
    </PanelSectionRow>
  );
}

/** "Steam cards & emulators": the settings that change things outside the plugin. */
function AutoloadSection() {
  const [on, setOn] = useState(null as string[] | null);
  useEffect(() => { api.autoloadStatus().then(setOn); }, []);
  /** Turn auto-load off everywhere, then check again. */
  const turnOff = async () => {
    const changed = await api.autoloadOff();
    toast("Auto-load states", changed.length ? `Turned off in ${changed.join(", ")}` : "Already off");
    setOn(await api.autoloadStatus());
  };
  return (
    <PanelSection title="Steam cards & emulators">
      <SteamPagesSwitch />
      <CardsButton />
      <ExtrasFolder />
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={!on || on.length === 0} onClick={turnOff}
          description={autoloadSummary(on)}>
          <Label icon="block">Turn off auto-load states</Label>
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

/** A list of RomM's platforms or collections; each opens its games. */
function Pick({ view, go }: { view: Extract<Page, { page: "pick" }>; go: (p: Page) => void }) {
  const [items, setItems] = useState(null as Collection[] | Err | null);
  useEffect(() => { (view.kind === "platforms" ? api.platforms() : api.collections()).then(setItems); }, [view.kind]);
  const title = view.kind === "platforms" ? "Platforms" : "Collections";

  return (
    <PanelSection title={title}>
      <Back go={() => go({ page: "home" })} />
      {items === null && <PanelSectionRow><Field description="Loading…" /></PanelSectionRow>}
      {isErr(items) && <PanelSectionRow><Field description={items.error} /></PanelSectionRow>}
      {Array.isArray(items) && items.length === 0 && (
        <PanelSectionRow><Field description={`No ${title.toLowerCase()} in RomM yet`} /></PanelSectionRow>
      )}
      {Array.isArray(items) && items.map((c) => (
        <PanelSectionRow key={`${c.kind}-${c.id}`}>
          <ButtonItem layout="below" onClick={() => go({ page: "list", title: c.name, kind: c.kind, id: c.id, back: view })}>
            <span style={{ display: "flex", alignItems: "center", gap: "10px", width: "100%", textAlign: "left" }}>
              <Icon name={view.kind === "platforms" ? "grid" : "stack"} />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span>
              <span style={{ fontSize: "12px", opacity: 0.6 }}>{c.count}{c.kind === "smart" ? " · smart" : ""}</span>
            </span>
          </ButtonItem>
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
}

/** A list of games (a platform, a collection, a search, or what's on this PC), with removing
 * several at once on the "On this PC" list. */
function List({ view, go }: { view: Extract<Page, { page: "list" }>; go: (p: Page) => void }) {
  const [roms, setRoms] = useState(null as Rom[] | Err | null);
  const [scanning, setScanning] = useState(false);
  const [choosing, setChoosing] = useState(false);       // picking games to remove
  const [chosen, setChosen] = useState([] as number[]);
  const [confirm, setConfirm] = useConfirm();
  const [removing, setRemoving] = useState("");           // "Removing 2 of 5: …"
  /** (Re)load the list from the backend. */
  const load = () => {
    const request = view.kind === "installed" ? api.installed() : api.roms(view.kind, view.id);
    return request.then(setRoms);
  };
  useEffect(() => { load(); }, [view.kind, view.id]);

  /** Match RomM's whole library against Emulation/roms (and relink games RomM deleted). */
  const scan = async () => {
    setScanning(true);
    const r = await api.scan();
    setScanning(false);
    toast("RomM Deck", isErr(r) ? r.error : [
      `Found ${r.found} more games on this PC`,
      r.relinked.length ? `relinked ${r.relinked.join(", ")} to their current RomM entry` : "",
      r.lost.length ? `not in RomM any more: ${r.lost.join(", ")}` : "",
    ].filter(Boolean).join("; "));
    load();
  };

  // Each game is removed exactly as from its own page: saves synced, checked on RomM, then deleted.
  // One that can't be (a save didn't reach RomM, it's running...) is skipped and stays on the PC.
  const removeChosen = async () => {
    setConfirm(false);
    const list = (roms as Rom[]).filter((r) => chosen.includes(r.id));
    const removed: string[] = [], kept: string[] = [];
    for (const [i, g] of list.entries()) {
      setRemoving(`Removing ${i + 1} of ${list.length}: ${g.name}…`);
      const r = await api.uninstall(g.id).catch((e: unknown) => ({ ok: false, error: String(e) } as any));
      if (r.ok) { removeCard(r.app_id ?? null); removed.push(g.name); }
      else kept.push(`${g.name} (${r.error || "unknown problem"})`);
    }
    setRemoving(""); setChoosing(false); setChosen([]);
    toast("Removed from this PC", [
      removed.length ? `${removed.length} removed, saves safe on RomM` : "",
      kept.length ? `Not removed: ${kept.join("; ")}` : "",
    ].filter(Boolean).join(". "));
    load();
  };

  /** Choose or unchoose one game for removing. */
  const toggle = (id: number) => {
    setConfirm(false);  // the choice changed: the next press arms again
    setChosen((c: number[]) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  };
  /** A game in the list was pressed: choose it (when removing several) or open its page. */
  const pressed = (id: number) => {
    if (choosing) toggle(id);
    else go({ page: "game", id, back: view });
  };
  const all = Array.isArray(roms) ? roms.map((r) => r.id) : [];
  let removeLabel = `Remove ${chosen.length} selected`;
  if (removing) removeLabel = "Removing…";
  else if (confirm) removeLabel = `Press again to remove ${chosen.length}`;

  return (
    <PanelSection title={view.title}>
      <Back go={() => go(view.back)} />
      {view.kind === "installed" && !choosing && (
        <>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={scanning} onClick={scan}
              description="Matches your RomM library against Emulation/roms, and relinks games whose RomM entry was deleted">
              <Label icon="folder">{scanning ? "Looking…" : "Find games already on this PC"}</Label>
            </ButtonItem>
          </PanelSectionRow>
          {all.length > 0 && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => { setChoosing(true); setChosen([]); }}
                description="Pick games, then remove them together. Each one's saves are synced and checked on RomM first.">
                <Label icon="trash">Remove several games</Label>
              </ButtonItem>
            </PanelSectionRow>
          )}
        </>
      )}
      {choosing && (
        <>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={!chosen.length || !!removing}
              onClick={() => (confirm ? removeChosen() : setConfirm(true))}
              description={removing || (chosen.length
                ? "Syncs saves and states, checks RomM has every one, then deletes each game, its saves and its Steam card. A game with anything not on RomM is skipped."
                : "Tap games below to choose them")}>
              <Label icon="trash" color="#ff6b6b">{removeLabel}</Label>
            </ButtonItem>
          </PanelSectionRow>
          {!removing && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => setChosen(chosen.length === all.length ? [] : all)}>
                <Label icon="check">{chosen.length === all.length ? "Choose none" : "Choose all"}</Label>
              </ButtonItem>
            </PanelSectionRow>
          )}
          {!removing && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => { setChoosing(false); setChosen([]); setConfirm(false); }}>
                <Label icon="back">Cancel</Label>
              </ButtonItem>
            </PanelSectionRow>
          )}
        </>
      )}
      {roms === null && <PanelSectionRow><Field description="Loading…" /></PanelSectionRow>}
      {isErr(roms) && <PanelSectionRow><Field description={roms.error} /></PanelSectionRow>}
      {Array.isArray(roms) && roms.length === 0 && <PanelSectionRow><Field description="No games" /></PanelSectionRow>}
      {Array.isArray(roms) && roms.map((r) => (
        <PanelSectionRow key={r.id}>
          <ButtonItem layout="below" disabled={!!removing} onClick={() => pressed(r.id)}>
            <GameRow id={r.id} cover={r.cover} name={r.name} onPC={r.installed && view.kind !== "installed"}
              sub={`${r.platform}${r.installed && view.kind !== "installed" ? " · on this PC" : ""}`}
              selected={choosing ? chosen.includes(r.id) : undefined} />
          </ButtonItem>
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
}

/** What the game page's status line says, and its dot's colour. */
function gameState(game: Game, view: GamePageView, downloading: boolean): [string, string] {
  if (view.playing) return ["Playing now", GREEN];
  if (downloading) return ["Downloading", "#1a9fff"];
  if (game.installed) return ["On this PC", GREEN];
  return ["In RomM, not on this PC", GREY];
}

/** The game page's line about its saves (nothing for a game whose saves aren't synced). */
function SavesStatus({ game }: { game: Game }) {
  if (!game.syncs) return null;
  if (!game.saves) return <Status color={GREY}>Saves not synced yet</Status>;
  if (game.saves.ok) return <Status color={GREEN}>Saves synced {ago(game.saves.at)}</Status>;
  const why = game.saves.error ? `: ${game.saves.error}` : "";
  return <Status color={AMBER}>Last sync failed {ago(game.saves.at)}{why}</Status>;
}

/** The popup after a save button, in words: what moved, or why nothing did. */
function savesMessage(mode: string, label: string, r: SavesResult, game: Game): string {
  if (!r.ok) return r.error || "Failed";
  const nothingMoved = !r.up && !r.down;
  if (nothingMoved && r.other?.length) {
    return `RomM's saves for this game are from ${r.other.join(", ")}, which this PC doesn't use`;
  }
  if (mode === "pull" && !r.down) return "RomM has no saves or states for this game yet";
  if (mode === "push" && !r.up) return "No saves or states for this game on this PC yet";
  return `${label}: ${r.up} files up, ${r.down} down. RomM game #${game.id} has ${r.on_romm} saves/states from this PC`;
}

/** The text under the Calibrate motion button. */
/** The auto-load button's line: which emulators still load the last state on start, while that's being checked. */
function autoloadSummary(on: string[] | null): string {
  if (on === null) return "Checking…";
  if (on.length) return `On in: ${on.join(", ")}`;
  return "Off in every emulator";
}

/** The calibrate button's text: what it does now, which depends on whether motion was calibrated before. */
function calibrateLabel(busy: string, calibrated: boolean): string {
  if (busy === "calibrate") return "Calibrating…";
  return calibrated ? "Recalibrate motion" : "Calibrate motion";
}

/** The calibrate button's line: during calibration, the step the player is on; otherwise what calibrating is for. */
function calibrationHint(busy: string, step: string, calibrated: boolean): string {
  if (busy === "calibrate") return step || "Starting…";
  if (calibrated) return "Calibrated. Redo it if tilting goes the wrong way.";
  return "Needed once before motion works: lay it flat, then stand it up facing you.";
}

/** One game: download, Steam card, controller preset, saves, BIOS, remove. */
function GamePage({ view, go }: { view: GamePageView; go: (p: Page) => void }) {
  const [game, setGame] = useState(null as Game | Err | null);
  const [progress, setProgress] = useState(null as number | null);
  const [busy, setBusy] = useState("");
  const [calibration, setCalibration] = useState("");  // the step the user is on, while calibrating
  /** (Re)load the game from the backend. */
  const refresh = () => api.game(view.id).then((g: Game | Err) => {
    setGame(g);
    if (!isErr(g)) setProgress(g.downloading);
  });

  useEffect(() => {
    refresh();
    const onProgress = addEventListener("progress", (id: number, pct: number) => id === view.id && setProgress(pct));
    const onDone = addEventListener("downloaded", (id: number) => { if (id === view.id) setTimeout(refresh, 1500); });
    const onStep = addEventListener("calibration", (text: string) => setCalibration(text));
    return () => {
      removeEventListener("progress", onProgress); removeEventListener("downloaded", onDone);
      removeEventListener("calibration", onStep);
    };
  }, [view.id]);

  // Same as the home page: keep the bar current while the menu is open (asks the plugin, not RomM)
  const visible = useQuickAccessVisible();
  const downloading = progress !== null;
  useEffect(() => {
    if (!visible || !downloading) return;
    let seen = false;  // (a download that's only just been asked for may not be listed yet)
    /** This game's current percent, from the backend's list of downloads. */
    const check = () => api.downloads().then((l) => {
      const d = l.find((x) => x.id === view.id);
      if (d) { seen = true; setProgress(d.percent); }
      else if (seen) refresh();  // finished meanwhile
    }).catch(() => {});
    check();
    const timer = setInterval(check, 1000);
    return () => clearInterval(timer);
  }, [visible, downloading, view.id]);

  /** Run one button's action: buttons are disabled meanwhile (`busy` names it), then the page reloads. */
  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    await fn();
    setBusy("");
    refresh();
  };

  if (game === null) return <PanelSection><PanelSectionRow><Field description="Loading…" /></PanelSectionRow></PanelSection>;
  if (isErr(game)) return <PanelSection><PanelSectionRow><Field description={game.error} /></PanelSectionRow></PanelSection>;

  const year = game.about?.release_date ? String(new Date(game.about.release_date * 1000).getUTCFullYear()) : "";
  const size = game.size_mb >= 1024 ? `${(game.size_mb / 1024).toFixed(1)} GB` : `${game.size_mb} MB`;
  const [stateText, stateColor] = gameState(game, view, progress !== null);

  return (
    <>
      <PanelSection>
        <Back go={() => go(view.back)} />
        <PanelSectionRow>
          <div style={{ display: "flex", gap: "12px", alignItems: "flex-start", padding: "4px 0 8px" }}>
            <Cover id={game.id} path={game.cover} width={72} />
            <div style={{ display: "flex", flexDirection: "column", gap: "5px", minWidth: 0 }}>
              <div style={{ fontWeight: "bold", fontSize: "15px", lineHeight: 1.25, wordBreak: "break-word" }}>{game.name}</div>
              <div style={{ fontSize: "12px", opacity: 0.7 }}>
                {[game.platform, year, size].filter(Boolean).join(" · ")}
              </div>
              {game.about?.developers?.length > 0 && (
                <div style={{ fontSize: "12px", opacity: 0.7 }}>{game.about.developers.join(", ")}</div>
              )}
              <Status color={stateColor}>{stateText}</Status>
              <SavesStatus game={game} />
            </div>
          </div>
        </PanelSectionRow>
        {progress !== null && <PanelSectionRow><Progress percent={progress} /></PanelSectionRow>}
      </PanelSection>

      {(game.installed || progress === null) && (
        <PanelSection title="Play">
          {!game.installed && progress === null && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => { setProgress(0); api.download(game.id, game.name); }}>
                <Label icon="download">Download</Label>
              </ButtonItem>
            </PanelSectionRow>
          )}

          {game.installed && !game.playable && (
            <PanelSectionRow><Field description="No emulator is set up for this platform here, so there's no Steam card." /></PanelSectionRow>
          )}

          {game.playable && !game.app_id && view.appId && (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={!!busy}
                description="Keeps this card, its artwork and playtime; it will pull saves before you play and push them after"
                onClick={() => run("card", async () => {
                  const ok = await takeOver(game.id, view.appId!);
                  if (ok) refreshSteamPages();
                  toast(game.name, ok ? "This card now syncs saves" : "Couldn't change this card");
                })}><Label icon="card">Sync saves automatically with this card</Label></ButtonItem>
            </PanelSectionRow>
          )}
          {game.playable && !game.app_id && !view.appId && (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={!!busy} onClick={() => run("card", async () => { await addCard(game.id); refreshSteamPages(); })}
                description="Already has an EmuDeck card? Open this menu from that card's Steam page instead, so it can sync with it">
                <Label icon="card">Add Steam card</Label>
              </ButtonItem>
            </PanelSectionRow>
          )}

          {game.installed && game.playable && game.preset && (
            <PanelSectionRow>
              <ToggleField label={<Label icon="gamepad">{game.preset.label}</Label>} checked={game.preset.on} disabled={!!busy}
                description={[
                  `${game.preset.about} Applies to every ${game.platform} game${view.playing ? ", from the next launch" : ""}.`,
                  game.preset.on ? game.preset.last : "",
                ].filter(Boolean).join(" ")}
                onChange={(on: boolean) => run("preset", async () => {
                  const r = await api.setPreset(game.preset!.platform, on);
                  // a running emulator has already read its settings, so a change reaches it at the next launch
                  const when = view.playing ? ": from the next launch" : "";
                  if (!r.ok) toast(game.platform, r.error || "Failed");
                  else if (on) toast(game.platform, `Controller preset on${when}`);
                  else toast(game.platform, `Controller preset off${when}, all changes undone`);
                })} />
            </PanelSectionRow>
          )}

          {game.installed && game.playable && game.preset?.on && game.preset.motion && (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={!!busy}
                description={calibrationHint(busy, calibration, game.preset.calibrated)}
                onClick={() => run("calibrate", async () => {
                  setCalibration("");
                  const r = await api.calibrateMotion();
                  toast("Motion", r.ok ? "Calibrated" : r.error || "Calibration failed");
                })}>
                <Label icon="compass">{calibrateLabel(busy, game.preset.calibrated)}</Label>
              </ButtonItem>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      {game.installed && game.playable && (
        <PanelSection title="Saves & states">
          <PanelSectionRow>
            <Field description={view.playing
              ? "Quit the game before Pull: the emulator may write over it when it closes"
              : "Push and Pull keep the replaced copy on RomM as a backup"} />
          </PanelSectionRow>
          {SAVE_BUTTONS.map(([mode, label, desc, icon]) => (
            <PanelSectionRow key={mode}>
              <ButtonItem layout="below" disabled={!!busy} description={desc}
                onClick={() => run(mode, async () => {
                  const r = await api.gameSaves(game.id, mode);
                  toast(game.name, savesMessage(mode, label, r, game));
                })}><Label icon={icon}>{busy === mode ? "Working…" : label}</Label></ButtonItem>
            </PanelSectionRow>
          ))}
        </PanelSection>
      )}

      <PanelSection title="Manage">
        {game.installed && game.extras > 0 && progress === null && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={!game.extras_dir}
              description={game.extras_dir
                ? `${game.extras_on_pc} of ${game.extras} on this PC · into ${game.extras_dir}`
                : "Set the Switch updates & DLC folder on the home page first"}
              onClick={() => { setProgress(0); api.downloadExtras(game.id, game.name); }}>
              <Label icon="dlc">{game.extras_on_pc >= game.extras ? "Re-download updates & DLC" : "Download updates & DLC"}</Label>
            </ButtonItem>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!busy} description="Downloads this platform's files from RomM into Emulation/bios"
            onClick={() => run("bios", async () => {
              const r = await api.bios(game.platform_id);
              if (isErr(r)) toast("BIOS", r.error);
              else toast("BIOS", r.count ? `Downloaded ${r.count} files` : "RomM has none for this platform");
            })}><Label icon="chip">{busy === "bios" ? "Downloading…" : `Get ${game.platform} BIOS`}</Label></ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" description={`See its saves and states in RomM · RomM game #${game.id}`}
            onClick={() => { Navigation.NavigateToExternalWeb(`${serverUrl}/rom/${game.id}`); Navigation.CloseSideMenus(); }}>
            <Label icon="open">Open on RomM</Label>
          </ButtonItem>
        </PanelSectionRow>
        {game.installed && <RemoveButton game={game} view={view} busy={busy} run={run} />}
      </PanelSection>
    </>
  );
}

// Decky rebuilds the panel every time the menu opens; this remembers where you were.
let lastPage: Page = { page: "home" };
let serverUrl = "";  // RomM's address, for "Open on RomM"

/** The home page's list of what's downloading, live; each one opens its game. Hidden when nothing is. */
function Downloads({ go, back }: { go: (p: Page) => void; back: Page }) {
  const [list, setList] = useState([] as Download[]);
  const reload = useRef(null as null | (() => void));
  useEffect(() => {
    let alive = true;
    let known = new Set<number>();
    /** The current list of downloads, from the backend. */
    const load = () => api.downloads().then((l) => {
      if (!alive) return;
      known = new Set(l.map((d) => d.id));
      setList(l);
    }).catch(() => {});
    load();
    const onProgress = addEventListener("progress", (id: number, pct: number) => {
      if (!known.has(id)) { known.add(id); load(); return; }  // started elsewhere: fetch its name
      setList((l: Download[]) => l.map((d) => (d.id === id ? { ...d, percent: pct } : d)));
    });
    const onDone = addEventListener("downloaded", (id: number) => {
      known.delete(id);
      setList((l: Download[]) => l.filter((d) => d.id !== id));
    });
    reload.current = load;
    return () => { alive = false; removeEventListener("progress", onProgress); removeEventListener("downloaded", onDone); };
  }, []);
  // Progress updates can be missed while the menu is closed: catch up when it opens, and while it's
  // open with something downloading, ask the plugin (not RomM) for the current numbers every second.
  const visible = useQuickAccessVisible();
  const busy = list.length > 0;
  useEffect(() => {
    if (!visible) return;
    reload.current?.();
    if (!busy) return;
    const timer = setInterval(() => reload.current?.(), 1000);
    return () => clearInterval(timer);
  }, [visible, busy]);
  if (!list.length) return null;
  return (
    <PanelSection title="Downloading">
      {list.map((d: Download) => (
        <PanelSectionRow key={d.id}>
          <ButtonItem layout="below" onClick={() => go({ page: "game", id: d.id, back })}>
            <span style={{ display: "flex", alignItems: "center", gap: "10px", width: "100%", textAlign: "left" }}>
              <Cover id={d.id} width={28} />
              <span style={{ flex: 1, minWidth: 0 }}><Progress percent={d.percent} label={d.name} /></span>
            </span>
          </ButtonItem>
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
}

/** A download bar sized to the menu (Steam's own one runs past the right edge in here). */
function Progress({ percent, label }: { percent: number; label?: string }) {
  return (
    <Field label={`${label ? `${label} · ` : "Downloading… "}${percent}%`} childrenLayout="below" bottomSeparator="none">
      <div style={{ width: "100%", height: "6px", borderRadius: "3px", background: "rgba(255,255,255,0.15)", overflow: "hidden" }}>
        <div style={{ width: `${percent}%`, height: "100%", background: "#1a9fff", transition: "width 0.3s" }} />
      </div>
    </Field>
  );
}

/** Remove from this PC: two presses, and nothing is deleted unless RomM has every save. */
function RemoveButton({ game, view, busy, run }: {
  game: Game; view: GamePageView; busy: string; run: (label: string, fn: () => Promise<void>) => void;
}) {
  const [confirm, setConfirm] = useConfirm();

  /** Remove the game (and the card the menu was opened from, if it's this game's). */
  const remove = () => run("remove", async () => {
    setConfirm(false);
    // the card the menu was opened from (e.g. Steam ROM Manager's) goes too, but only if it really
    // starts this game: checked now, while the game's file is still there to match
    const alsoCard = view.appId && (await cardIsGame(view.appId, game.id)) ? view.appId : null;
    const r = await api.uninstall(game.id);
    if (!r.ok) return toast(`${game.name} not removed`, r.error || "Unknown problem");
    removeCard(r.app_id ?? null);
    if (alsoCard && alsoCard !== r.app_id) removeCard(alsoCard);
    const kept = r.kept?.length ? `; kept shared ${r.kept.join(", ")}` : "";
    toast(game.name, `Removed. ${r.deleted?.length || 0} save files deleted, all safe on RomM${kept}`);
  });

  let label = "Remove from this PC";
  if (busy === "remove") label = "Syncing and checking…";
  else if (confirm) label = "Press again to remove";

  return (
    <PanelSectionRow>
      <ButtonItem layout="below" disabled={!!busy || view.playing} onClick={() => (confirm ? remove() : setConfirm(true))}
        description={view.playing ? "Quit the game first"
          : "Syncs saves and states, checks RomM has every one, then deletes the game, its saves and its Steam card. If anything isn't on RomM, nothing is deleted."}>
        <Label icon="trash" color="#ff6b6b">{label}</Label>
      </ButtonItem>
    </PanelSectionRow>
  );
}

/** The panel: a problem message if the backend didn't start, setup if not paired, else the current page. */
function Content() {
  const [status, setStatus] = useState(null as { connected: boolean; url: string } | null);
  const [page, setPageState] = useState(lastPage);
  const [problem, setProblem] = useState("");  // the plugin's Python side didn't answer
  /** Show a page, and remember it for the next time the menu opens. */
  const setPage = (p: Page) => { lastPage = p; setPageState(p); };
  /** Ask the backend whether it's paired with RomM (this also shows that it's running at all). */
  const load = () => api.status().then((st: { connected: boolean; url: string }) => { serverUrl = st.url; setStatus(st); });

  // Each time the menu opens: if you're on a game's Steam page (or playing it), show that game.
  // Only then, never while the menu is open, so nothing moves under you.
  const follow = async () => {
    const here = await currentGame().catch(() => null);
    const shown = lastPage;
    if (here) {
      if (shown.page === "game" && shown.id === here.romId) {
        if (shown.playing !== here.playing) setPage({ ...shown, playing: here.playing, appId: here.appId });
        return;
      }
      // a page opened this way goes back to where you were, not to the previous game
      const back = shown.page === "game" && shown.auto ? shown.back : shown;
      setPage({ page: "game", id: here.romId, playing: here.playing, appId: here.appId, back, auto: true });
    } else if (shown.page === "game" && shown.auto) {
      setPage(shown.back);  // you've left that game: don't keep showing it
    }
  };

  const visible = useQuickAccessVisible();
  useEffect(() => {
    const slow = setTimeout(() => setProblem("No answer from the plugin's background part yet."), 10000);
    load().then(() => { clearTimeout(slow); setProblem(""); },
      (e: unknown) => { clearTimeout(slow); setProblem(`The plugin's background part isn't running (${e}).`); });
    return () => clearTimeout(slow);
  }, []);
  useEffect(() => {
    if (visible && status?.connected) follow();
  }, [visible, status?.connected]);

  if (!status) return problem ? (
    <PanelSection>
      <PanelSectionRow>
        <Field label="RomM Deck didn't start"
          description={`${problem} Restart Decky (or reinstall the plugin). Details are in Decky's log for RomM Deck: ~/homebrew/logs/romm-deck/.`} />
      </PanelSectionRow>
    </PanelSection>
  ) : null;
  if (!status.connected) return <Setup onDone={load} />;
  if (page.page === "pick") return <Pick view={page} go={setPage} />;
  if (page.page === "list") return <List view={page} go={setPage} />;
  if (page.page === "game") return <GamePage view={page} go={setPage} />;
  return <Home go={setPage} url={status.url} onDisconnect={load} />;
}

// ---------- plugin entry ----------

/** The plugin's icon in Decky's list. */
const PluginIcon = () => (
  <svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor">
    <path d="M7 6h10a5 5 0 0 1 5 5v2a5 5 0 0 1-5 5c-1.6 0-2.6-.8-3.3-2h-3.4c-.7 1.2-1.7 2-3.3 2a5 5 0 0 1-5-5v-2a5 5 0 0 1 5-5zm-.5 4v1.5H5v1h1.5V14h1v-1.5H9v-1H7.5V10zm9.5.5a1 1 0 1 0 0 2 1 1 0 0 0 0-2zm2 1.5a1 1 0 1 0 0 2 1 1 0 0 0 0-2z" />
  </svg>
);

/** Decky calls this once when the plugin loads; what it returns is the panel, and onDismount
 * runs when the plugin unloads. Listeners that must work while the menu is closed live here. */
export default function () {
  // Steam ROM Manager puts its own command back on cards when it runs; quietly take them back
  setTimeout(() => repairCards().catch(() => {}), 15000);

  // RomM's details on these games' Steam pages (off switch: the panel's home page)
  let stopSteamPages = () => {};
  try { stopSteamPages = startSteamPages(); } catch (e) { console.error("RomM Deck: Steam pages", e); }
  api.options().then((o) => showOnSteamPages(o.steam_pages !== false)).catch(() => {});

  // When a game stops (e.g. Steam's "Exit game"), make sure its saves get pushed and controller
  // settings put back, even if Steam closed our launcher along with the game.
  const gameClosed = callable<[appId: number]>("game_closed");
  // Popups about saves and controller presets, from the game launcher (via the backend)
  const onNotify = addEventListener("notify", (title: string, body: string) => toast(title, body));
  const lifetime = (window as any).SteamClient?.GameSessions?.RegisterForAppLifetimeNotifications?.(
    (n: { unAppID: number; bRunning: boolean }) => { if (!n.bRunning) gameClosed(n.unAppID).catch(() => {}); });

  // Lives as long as the plugin (not just while the panel is open), so a download
  // that finishes after you close the menu still gets its Steam card.
  const onDownloaded = addEventListener("downloaded", async (id: number, r: { ok: boolean; name?: string; playable?: boolean; error?: string; extras?: number }) => {
    if (!r.ok) return toast("Download failed", r.error || "");
    if (r.playable) { await addCard(id); refreshSteamPages(); }
    const extras = r.extras ? ` (${r.extras} updates/DLC in their own folder)` : "";
    toast(r.name || "Download", (r.playable ? "Downloaded and added to your library" : "Downloaded") + extras);
  });

  return {
    name: "RomM Deck",
    titleView: <div className={staticClasses.Title}>RomM Deck</div>,
    content: <Content />,
    icon: <PluginIcon />,
    onDismount() {
      removeEventListener("downloaded", onDownloaded);
      lifetime?.unregister?.();
      removeEventListener("notify", onNotify);
      stopSteamPages();
    },
  };
}
