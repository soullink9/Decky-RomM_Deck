// Which game the user is on: the one running, or the Steam page they have open.
import { callable } from "./decky";
import { appDetails } from "./cards";

const matchApp = callable<[appId: number, exe: string, options: string], number | null>("match_app");

export type Current = { romId: number; appId: number; playing: boolean };

/** The Steam game page that's open, and the game that's running (app ids, or null). */
function where(): { onPage: number | null; running: number | null } {
  const ui = (window as any).SteamUIStore;
  const path: string = ui?.WindowStore?.GamepadUIMainWindowInstance?.m_locationPathname || "";
  return { onPage: Number(path.match(/\/library\/app\/(\d+)/)?.[1]) || null, running: ui?.MainRunningAppID || null };
}

export async function currentGame(): Promise<Current | null> {
  const { onPage, running } = where();
  const appId = onPage || running; // the page you're looking at wins over what's running
  if (!appId) return null;
  const d = await appDetails(appId);
  const romId = await matchApp(appId, d?.exe || "", d?.options || "");
  return romId ? { romId, appId, playing: appId === running } : null;
}
