// Steam library cards: make new ones for downloads, or take over existing ones (EmuDeck's)
// so they start through RomM Deck's launcher, which syncs saves before and after playing.
import { steamApps, callable, sleep } from "./decky";

/** A card's command as the backend gives it (Python's names). */
type Command = { exe: string; start_dir: string; options: string };
/** A card's command as Steam reports it for an existing card. */
type Details = { exe: string; options: string; startDir: string };

const getCard = callable<[romId: number], (Command & { name: string; collections: string[] }) | null>("card");
const getCover = callable<[romId: number], { data: string; ext: "png" | "jpg" } | null>("cover");
const setAppId = callable<[romId: number, appId: number]>("set_app_id");
const matchApp = callable<[appId: number, exe: string, options: string], number | null>("match_app");
const backendTakeOver = callable<[romId: number, appId: number, exe: string, options: string, startDir: string], Command | { error: string }>("take_over");
const takenOver = callable<[], { rom_id: number; app_id: number }[]>("taken_over");

const SHORTCUT = 1073741824; // Steam's app type for non-Steam games

/** Steam's app details, cut down to the card's command (null if Steam gave nothing). */
function toDetails(d: any): Details | null {
  if (!d) return null;
  return {
    exe: d.strShortcutExe || "",
    options: d.strShortcutLaunchOptions || d.strLaunchOptions || "",
    startDir: d.strShortcutStartDir || "",
  };
}

/** A card's command, as Steam has it. Steam only hands over a card's details through a callback,
 * so this waits for it (3 s at most; null if Steam doesn't answer). */
export function appDetails(appId: number): Promise<Details | null> {
  return new Promise((resolve) => {
    const done = (d: any) => resolve(toDetails(d));  // (called once: from the cache, Steam, or the timeout)
    const cached = (window as any).appDetailsStore?.GetAppDetails?.(appId);
    if (cached?.strShortcutExe) return done(cached);
    let reg: any;
    const timer = setTimeout(() => { reg?.unregister?.(); done(null); }, 3000);
    reg = steamApps().RegisterForAppDetails(appId, (d: any) => {
      clearTimeout(timer);
      reg?.unregister?.();
      done(d);
    });
  });
}

/** Does this card already start through RomM Deck's launcher? */
const isOurs = (d: Details) => d.options.includes("romm_launch.py");

/** Set a card's command. Steam keeps the target and start folder in quotes (paths may have spaces),
 * which JSON.stringify adds; launch options are stored as typed. */
function setCommand(appId: number, c: Command) {
  const apps = steamApps();
  apps.SetShortcutExe(appId, JSON.stringify(c.exe));
  apps.SetShortcutStartDir(appId, JSON.stringify(c.start_dir));
  apps.SetAppLaunchOptions(appId, c.options);
}

/** Is this Steam card really this game? (Checked again right before anything is removed.) */
export async function cardIsGame(appId: number, romId: number) {
  const d = await appDetails(appId);
  return !!d && (await matchApp(appId, d.exe, d.options)) === romId;
}

/** Point an existing card at RomM Deck's launcher. Name, artwork and playtime stay. */
export async function takeOver(romId: number, appId: number): Promise<boolean> {
  const d = await appDetails(appId);
  if (!d) return false;
  if (isOurs(d)) return true;
  const c = await backendTakeOver(romId, appId, d.exe, d.options, d.startDir);
  if ("error" in c) return false;
  setCommand(appId, c);
  return true;
}

/** Take over every non-Steam card that starts a game RomM has. */
export async function takeOverAll(progress: (done: number, total: number) => void) {
  const apps: any[] = ((window as any).appStore?.allApps || []).filter((a: any) => a.app_type === SHORTCUT);
  let count = 0;
  for (const [i, app] of apps.entries()) {
    progress(i, apps.length);
    const d = await appDetails(app.appid);
    if (!d || isOurs(d)) continue;
    const romId = await matchApp(app.appid, d.exe, d.options);
    if (romId && (await takeOver(romId, app.appid))) count++;
  }
  return count;
}

/** Steam ROM Manager puts its own command back when it runs again; take those cards back. */
export async function repairCards() {
  for (const { rom_id, app_id } of await takenOver()) {
    const d = await appDetails(app_id);
    if (d && d.exe && !isOurs(d)) await takeOver(rom_id, app_id);
  }
}

/** Add a new card for a game that has none. */
export async function addCard(romId: number) {
  const card = await getCard(romId);
  if (!card) return; // downloaded, but no emulator is set up for this platform
  const apps = steamApps();
  const appId: number = await apps.AddShortcut(card.name, card.exe, card.start_dir, card.options);
  await sleep(500); // Steam ignores most AddShortcut arguments, so set each one after it settles
  apps.SetShortcutName(appId, card.name);
  setCommand(appId, card);
  await setAppId(romId, appId);
  const cover = await getCover(romId);
  if (cover) await apps.SetCustomArtworkForApp(appId, cover.data, cover.ext, 0); // 0 = portrait grid
  await addToCollection(appId, card.collections).catch(() => {});
}

/** Put a card in its platform's collection, like Steam ROM Manager does.
 *  Uses the first of `names` that already exists in Steam, or creates the first one. */
async function addToCollection(appId: number, names: string[]) {
  const w = window as any;
  const store = w.collectionStore;
  let app = null;
  for (let i = 0; i < 20 && !app; i++) { // a new card takes a moment to show up in Steam's list
    app = w.appStore.GetAppOverviewByAppID(appId);
    if (!app) await sleep(250);
  }
  if (!store || !app) return;
  const existing = names.map((n) => store.GetUserCollectionsByName(n)?.[0]).find(Boolean);
  if (existing) {
    existing.AddApps([app]);
    await existing.Save();
  } else {
    await store.NewUnsavedCollection(names[0], undefined, [app]).Save();
  }
}

/** Delete a card from Steam (nothing if `appId` is null). */
export function removeCard(appId: number | null) {
  if (appId) steamApps().RemoveShortcut(appId);
}
