// Runs the unit tests of the pure modules (src/lib/*.ts): they are bundled with esbuild, which
// comes with Vite, and run with Node's own test runner. No browser, no extra packages.
//
//   npm test

import { build } from "esbuild";
import { spawnSync } from "node:child_process";
import { mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, ".build");
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

const files = readdirSync(here).filter((f) => f.endsWith(".test.ts"));
await build({
  entryPoints: files.map((f) => join(here, f)),
  outdir: out,
  bundle: true,
  platform: "node",
  format: "esm",
  outExtension: { ".js": ".mjs" },
  logLevel: "warning",
});

const run = spawnSync(process.execPath, ["--test", ...files.map((f) => join(out, f.replace(/\.ts$/, ".mjs")))], {
  stdio: "inherit",
});
rmSync(out, { recursive: true, force: true });
process.exit(run.status ?? 1);
