// Bundles src/ into dist/index.js, the ES module Decky Loader imports.
import { build } from "esbuild";
import { readFileSync } from "fs";

const { name } = JSON.parse(readFileSync("plugin.json", "utf8"));

await build({
  entryPoints: ["src/index.tsx"],
  outfile: "dist/index.js",
  bundle: true,
  format: "esm",
  target: "es2020",
  jsxFactory: "React.createElement",
  jsxFragment: "React.Fragment",
  define: { PLUGIN_NAME: JSON.stringify(name) },
  legalComments: "none",
});
console.log("built dist/index.js");
