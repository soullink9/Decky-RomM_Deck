// The small bridge to Decky Loader and the Steam client.
//
// Decky Loader exposes Steam's React, its UI components (DFL) and the backend bridge
// as globals; this file names the pieces the plugin uses. It does the same job as the
// @decky/ui and @decky/api packages, without needing them at build time.
declare const PLUGIN_NAME: string; // filled in from plugin.json by build.mjs

const w = window as any;

export const React = w.SP_REACT;
export const { useState, useEffect, useRef } = w.SP_REACT;

export const {
  PanelSection, PanelSectionRow, ButtonItem, TextField, ToggleField, Field, staticClasses, Navigation,
} = w.DFL;
/** Something the controller can move to (Steam's own Focusable); a plain div if it's missing. */
export const Focusable = w.DFL?.Focusable || ((p: any) => w.SP_REACT.createElement("div", p));

// API version 2 adds useQuickAccessVisible (version 1 features are unchanged)
const api = w.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit.connect(2, PLUGIN_NAME);

/** True while the Quick Access menu is open (Decky's own signal). On an older Decky without it,
 * always true: the panel then only checks which game you're on when it's first shown. */
export const useQuickAccessVisible: () => boolean = api.useQuickAccessVisible || (() => true);

/** A function that calls a method on the Python Plugin class in main.py. */
export const callable = <A extends any[] = [], R = any>(method: string) =>
  api.callable(method) as (...args: A) => Promise<R>;

export const addEventListener = (event: string, fn: (...args: any[]) => void) => api.addEventListener(event, fn);
export const removeEventListener = (event: string, fn: (...args: any[]) => void) => api.removeEventListener(event, fn);
export const toast = (title: string, body: string) => api.toaster.toast({ title, body });

/** Steam's own client API (read fresh each time; Steam can replace it after startup). */
export const steamApps = () => w.SteamClient.Apps;
export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
