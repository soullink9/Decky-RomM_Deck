// Small visual pieces for the panel: icons, cover art, a status line. Built into the plugin
// (nothing to install), and drawn with Steam's own colours so they look at home in the menu.
import { React, useState, useEffect, useRef, callable } from "./decky";

// ---------- icons (Material Design icons, Apache 2.0) ----------

const PATHS = {
  back: "M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z",
  download: "M5 20h14v-2H5v2zM19 9h-4V3H9v6H5l7 7 7-7z",
  sync: "M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0 0 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 0 0 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z",
  up: "M19.35 10.04A7.49 7.49 0 0 0 12 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 0 0 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z",
  down: "M19.35 10.04A7.49 7.49 0 0 0 12 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 0 0 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM17 13l-5 5-5-5h3V9h4v4h3z",
  gamepad: "M21 6H3c-1.1 0-2 .9-2 2v8c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-10 7H8v3H6v-3H3v-2h3V8h2v3h3v2zm4.5 2c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm4-3c-.83 0-1.5-.67-1.5-1.5S18.67 9 19.5 9s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z",
  compass: "M12 10.9c-.61 0-1.1.49-1.1 1.1s.49 1.1 1.1 1.1c.61 0 1.1-.49 1.1-1.1s-.49-1.1-1.1-1.1zM12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm2.19 12.19L6 18l3.81-8.19L18 6l-3.81 8.19z",
  trash: "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
  chip: "M15 9H9v6h6V9zm-2 4h-2v-2h2v2zm8-2V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2zm-4 6H7V7h10v10z",
  open: "M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z",
  card: "M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-2 10h-4v4h-2v-4H7v-2h4V7h2v4h4v2z",
  search: "M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
  pc: "M20 18c1.1 0 1.99-.9 1.99-2L22 6c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2H0v2h24v-2h-4zM4 6h16v10H4V6z",
  grid: "M4 8h4V4H4v4zm6 12h4v-4h-4v4zm-6 0h4v-4H4v4zm0-6h4v-4H4v4zm6 0h4v-4h-4v4zm6-10v4h4V4h-4zm-6 4h4V4h-4v4zm6 6h4v-4h-4v4zm0 6h4v-4h-4v4z",
  stack: "M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H8V4h12v12z",
  folder: "M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z",
  block: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zM4 12c0-4.42 3.58-8 8-8 1.85 0 3.55.63 4.9 1.69L5.69 16.9A7.902 7.902 0 0 1 4 12zm8 8c-1.85 0-3.55-.63-4.9-1.69L18.31 7.1A7.902 7.902 0 0 1 20 12c0 4.42-3.58 8-8 8z",
  dlc: "M20.5 11H19V7c0-1.1-.9-2-2-2h-4V3.5a2.5 2.5 0 0 0-5 0V5H4c-1.1 0-1.99.9-1.99 2v3.8H3.5c1.49 0 2.7 1.21 2.7 2.7s-1.21 2.7-2.7 2.7H2V20c0 1.1.9 2 2 2h3.8v-1.5c0-1.49 1.21-2.7 2.7-2.7 1.49 0 2.7 1.21 2.7 2.7V22H17c1.1 0 2-.9 2-2v-4h1.5a2.5 2.5 0 0 0 0-5z",
  power: "M13 3h-2v10h2V3zm4.83 2.17-1.42 1.42A6.92 6.92 0 0 1 19 12c0 3.87-3.13 7-7 7A6.995 6.995 0 0 1 7.58 6.58L6.17 5.17A8.932 8.932 0 0 0 3 12a9 9 0 0 0 18 0c0-2.74-1.23-5.18-3.17-6.83z",
  check: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z",
  note: "M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z",
  trophy: "M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94A5.01 5.01 0 0 0 11 15.9V19H7v2h10v-2h-4v-3.1a5.01 5.01 0 0 0 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2zM5 8V7h2v3.82C5.84 10.4 5 9.3 5 8zm14 0c0 1.3-.84 2.4-2 2.82V7h2v1z",
  save: "M17 3H5a2 2 0 0 0-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z",
  warning: "M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z",
};
export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="currentColor" style={{ flex: "none" }} aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  );
}

/** A button's text with an icon in front. `color` for the one red button (Remove). */
export function Label({ icon, children, color }: { icon: IconName; children: any; color?: string }) {
  return (
    <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "8px", color }}>
      <Icon name={icon} />
      <span>{children}</span>
    </span>
  );
}

// ---------- cover art ----------

const thumb = callable<[id: number, path: string], { data: string; url: string }>("thumb");
const covers = new Map<number, string[]>();  // id -> what to try, in order ([] = no cover), for this session

/** A game's cover, loaded when it scrolls into view (so a long list doesn't load them all). */
export function Cover({ id, path = "", width = 40 }: { id: number; path?: string; width?: number }) {
  // the copy saved on this PC first; if Steam won't show that (or there's none), RomM's own address
  const [tries, setTries] = useState(covers.get(id) ?? null);
  const box = useRef(null as HTMLDivElement | null);
  useEffect(() => {
    if (covers.has(id)) return setTries(covers.get(id)!);
    let alive = true, started = false;
    const load = () => {
      if (started) return;
      started = true;
      thumb(id, path).then((r) => {
        const list = [r.data, r.url].filter(Boolean);
        covers.set(id, list);
        if (alive) setTries(list);
      }).catch(() => {});
    };
    // The menu is its own window: watch with *its* IntersectionObserver (the plugin's code runs in
    // Steam's main window, whose observer can't see the menu). If no answer comes, just load.
    const el = box.current;
    const Observer = (el?.ownerDocument?.defaultView as any)?.IntersectionObserver;
    if (!el || !Observer) { load(); return () => { alive = false; }; }
    let answered = false;
    const watch = new Observer((entries: any[]) => {
      answered = true;
      if (entries.some((e) => e.isIntersecting)) { watch.disconnect(); load(); }
    }, { rootMargin: "300px" });
    watch.observe(el);
    const fallback = setTimeout(() => { if (!answered) { watch.disconnect(); load(); } }, 1500);
    return () => { alive = false; watch.disconnect(); clearTimeout(fallback); };
  }, [id]);
  return (
    <div ref={box} style={{
      width: `${width}px`, height: `${Math.round(width * 4 / 3)}px`, flex: "none", borderRadius: "4px", overflow: "hidden",
      background: "rgba(255,255,255,0.08)", display: "flex", alignItems: "center", justifyContent: "center",
      color: "rgba(255,255,255,0.35)",
    }}>
      {tries?.length ? <img key={tries[0]} src={tries[0]} style={{ width: "100%", height: "100%", objectFit: "cover" }}
        onError={() => { const rest = tries.slice(1); covers.set(id, rest); setTries(rest); }} />  /* next, or the placeholder */
        : <Icon name="gamepad" size={Math.round(width / 2)} />}
    </div>
  );
}

/** A list row: cover, name, and a second line (platform, ✓ on this PC). */
export function GameRow({ id, cover, name, sub, onPC, selected }: {
  id: number; cover?: string; name: string; sub: string; onPC?: boolean; selected?: boolean;  // selected: choosing games
}) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: "10px", textAlign: "left", width: "100%" }}>
      {selected !== undefined && (
        <span style={{ width: "20px", height: "20px", borderRadius: "50%", flex: "none", display: "flex", alignItems: "center",
          justifyContent: "center", border: selected ? "none" : "2px solid rgba(255,255,255,0.4)", boxSizing: "border-box",
          color: "#ff6b6b" }}>
          {selected && <Icon name="check" size={20} />}
        </span>
      )}
      <Cover id={id} path={cover} width={32} />
      <span style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
        <span style={{ fontSize: "12px", opacity: 0.6, display: "flex", alignItems: "center", gap: "4px" }}>
          {onPC && <span style={{ color: "#5ba32b", display: "flex" }}><Icon name="check" size={12} /></span>}
          {sub}
        </span>
      </span>
    </span>
  );
}

// ---------- status ----------

export const GREEN = "#5ba32b", AMBER = "#e8a33d", GREY = "rgba(255,255,255,0.4)";

/** A coloured dot and a short line, e.g. "● Saves synced 10 min ago". */
export function Status({ color, children }: { color: string; children: any }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px" }}>
      <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: color, flex: "none" }} />
      <span style={{ opacity: 0.85 }}>{children}</span>
    </span>
  );
}

export function ago(seconds: number): string {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} days ago`;
  return `on ${new Date(seconds * 1000).toLocaleDateString()}`;
}
