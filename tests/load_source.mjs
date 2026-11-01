// Builds one of the plugin's src/ modules for these tests (with the esbuild the plugin already uses).
import { build } from "esbuild";
import { mkdtempSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { fileURLToPath } from "url";

/** Bundles src/<name> into a temporary ES module and imports it. */
export async function loadSource(name) {
  const out = join(mkdtempSync(join(tmpdir(), "romm-deck-test-")), name.replace(/\.tsx?$/, ".mjs"));
  await build({
    entryPoints: [fileURLToPath(new URL(`../src/${name}`, import.meta.url))],
    outfile: out, bundle: true, format: "esm", logLevel: "warning",
    define: { PLUGIN_NAME: JSON.stringify("RomM Deck") },
  });
  return import(out);
}
