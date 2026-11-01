// src/current.ts: which game the panel opens on (the Steam page you're on, else the running game).
import { loadSource } from "./load_source.mjs";

const calls = [];
globalThis.window = globalThis;
window.SP_REACT = {}; window.DFL = {};
window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit = { connect: () => ({
  // the backend's match_app: app 777 is RomM game 3, app 888 is RomM game 50, anything else is unknown
  callable: (m) => async (...a) => { calls.push([m, ...a]); return a[0] === 777 ? 3 : a[0] === 888 ? 50 : null; },
}) };
const cards = {  // Steam's details for each card, as RegisterForAppDetails hands them over
  777: { strShortcutExe: '"/usr/bin/python3"', strShortcutLaunchOptions: '"/p/bin/romm_launch.py" 3' },
  888: { strShortcutExe: '"/x/retroarch.sh"', strShortcutLaunchOptions: '-L c.so "/r/gba/MF.gba"' },
};
window.SteamClient = { Apps: {
  RegisterForAppDetails: (id, cb) => { setTimeout(() => cb(cards[id] || null), 1); return { unregister() {} }; },
} };
const { currentGame } = await loadSource("current.ts");

let fails = 0;
const check = (ok, m) => { console.log((ok ? "PASS " : "FAIL ") + m); if (!ok) fails++; };
/** Puts Steam's UI on `path` with app `running` running (undefined: nothing running). */
const set = (path, running) => {
  window.SteamUIStore = { MainRunningAppID: running, WindowStore: { GamepadUIMainWindowInstance: { m_locationPathname: path } } };
};

set("/library/home", 777);
check(JSON.stringify(await currentGame()) === '{"romId":3,"appId":777,"playing":true}', "running game found while in the menu");
set("/library/app/888", 777);
const r = await currentGame();
check(r.romId === 50 && r.appId === 888 && !r.playing && calls.at(-1)[3].includes('"/r/gba/MF.gba"'),
  "Steam page wins over the running game, and its launch options are passed for matching");
set("/library/home", undefined);
check(await currentGame() === null, "nothing running, not on a game page: stay put");
set("/library/app/123", undefined);
check(await currentGame() === null, "non-RomM game page: stay put");
console.log(`\n${fails} failures`);
process.exit(fails ? 1 : 0);
