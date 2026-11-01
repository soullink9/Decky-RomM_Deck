import { loadSource } from "./load_source.mjs";
globalThis.window = globalThis;
window.SP_REACT = {}; window.DFL = {};
const calls = [];
const cards = {  // appid -> details as Steam has them
  101: { strShortcutExe: '"/emu/launchers/retroarch.sh"', strShortcutLaunchOptions: '-L c/mgba_libretro.so "/roms/gba/MF.gba"', strShortcutStartDir: '"/emu/launchers"' },
  102: { strShortcutExe: '"/emu/launchers/dolphin-emu.sh"', strShortcutLaunchOptions: 'vblank_mode=0 %command% -b -e "/roms/gc/Unknown.rvz"', strShortcutStartDir: '"/emu"' },
  103: { strShortcutExe: '"/usr/bin/python3"', strShortcutLaunchOptions: '"/p/bin/romm_launch.py" 9', strShortcutStartDir: '"/p/bin"' },
};
const taken = [];
window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit = { connect: () => ({
  callable: (m) => async (...a) => {
    calls.push([m, ...a]);
    if (m === "match_app") return a[0] === 101 ? 50 : null;
    if (m === "take_over") { taken.push({ rom_id: a[0], app_id: a[1] }); return { exe: "/usr/bin/python3", start_dir: "/p/bin", options: `"/p/bin/romm_launch.py" ${a[0]}` }; }
    if (m === "taken_over") return taken;
    return null;
  } }) };
const set = [];
window.SteamClient = { Apps: {
  RegisterForAppDetails: (id, cb) => { setTimeout(() => cb(cards[id]), 5); return { unregister() {} }; },
  SetShortcutExe: (id, v) => { set.push(["exe", id, v]); cards[id].strShortcutExe = v; },
  SetShortcutStartDir: (id, v) => { set.push(["dir", id, v]); cards[id].strShortcutStartDir = v; },
  SetAppLaunchOptions: (id, v) => { set.push(["opts", id, v]); cards[id].strShortcutLaunchOptions = v; },
} };
window.appStore = { allApps: [{ appid: 101, app_type: 1073741824 }, { appid: 102, app_type: 1073741824 }, { appid: 103, app_type: 1073741824 }, { appid: 440, app_type: 1 }] };
const C = await loadSource("cards.ts");
let fails = 0; const check = (ok, m) => { console.log((ok ? "PASS " : "FAIL ") + m); if (!ok) fails++; };

const n = await C.takeOverAll(() => {});
check(n === 1, `take over all: only the card RomM knows is changed (${n})`);
const to = calls.find((c) => c[0] === "take_over");
check(to && to[3] === '"/emu/launchers/retroarch.sh"' && to[4].includes("mgba_libretro.so"), "its original command is sent to be kept");
check(JSON.stringify(set) === JSON.stringify([["exe", 101, '"/usr/bin/python3"'], ["dir", 101, '"/p/bin"'], ["opts", 101, '"/p/bin/romm_launch.py" 50']]), `card 101 now runs the launcher: ${JSON.stringify(set)}`);
check(!calls.some((c) => c[0] === "match_app" && c[1] === 103), "cards already ours are skipped");

// Steam ROM Manager runs again and puts its command back
cards[101].strShortcutExe = '"/emu/launchers/retroarch.sh"'; cards[101].strShortcutLaunchOptions = '-L c/mgba_libretro.so "/roms/gba/MF.gba"';
set.length = 0;
await C.repairCards();
check(set.length === 3 && cards[101].strShortcutLaunchOptions.includes("romm_launch.py"), "repair takes the card back after Steam ROM Manager");
set.length = 0; await C.repairCards();
check(set.length === 0, "repair leaves cards that are already ours alone");
check(await C.cardIsGame(101, 50) === true, "cardIsGame: the card that starts this game");
check(await C.cardIsGame(102, 50) === false, "cardIsGame: a card for another game is never removed with it");
console.log(`\n${fails} failures`);
process.exit(fails ? 1 : 0);
