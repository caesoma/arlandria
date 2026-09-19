#!/usr/bin/env node
// Branded launcher. Prints the banner, then starts an interactive Pi session
// with the Arlandria skill + command extension on the path, so `/litreview`
// and `/literature-review` are available immediately. No build step: the
// extension is TypeScript loaded by Pi via jiti, and this launcher is plain JS.
import { spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { existsSync, readFileSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..");

const { ARLANDRIA_ASCII_LOGO_TEXT } = await import(pathToFileURL(join(pkgRoot, "logo.mjs")).href);
if (!process.env.ARLANDRIA_QUIET) {
  console.log("\n" + ARLANDRIA_ASCII_LOGO_TEXT + "\n");
}

// Prefer the Pi binary bundled as our dependency; fall back to a global `pi`.
function bundledPi() {
  try {
    const req = createRequire(import.meta.url);
    const metaPath = req.resolve("@earendil-works/pi-coding-agent/package.json");
    const meta = JSON.parse(readFileSync(metaPath, "utf8"));
    let bin = meta.bin;
    if (bin && typeof bin === "object") bin = bin.pi ?? Object.values(bin)[0];
    if (typeof bin === "string") {
      const p = join(dirname(metaPath), bin);
      if (existsSync(p)) return p;
    }
  } catch {}
  return null;
}

// The Python primitives self-bootstrap via `uv` (PEP 723 inline deps). Pi installs JS deps only,
// nothing for Python, so without uv the search/dedupe/resolve tools fail with ImportError mid-review.
// Probe for it up front (fast) and fail with a clear install hint. Skippable for unusual setups.
function ensureUv() {
  if (process.env.ARLANDRIA_SKIP_UV_CHECK) return;
  const probe = spawnSync("uv", ["--version"], { stdio: "ignore" });
  if (probe.error || probe.status !== 0) {
    console.error(
      "\nArlandria needs `uv` to run its Python primitives (search, dedupe, resolve, ...),\n" +
        "but it is not on your PATH. Install it with:\n\n" +
        "  curl -LsSf https://astral.sh/uv/install.sh | sh\n\n" +
        "Then re-run. Docs: https://docs.astral.sh/uv/\n" +
        "(Set ARLANDRIA_SKIP_UV_CHECK=1 to bypass this check.)\n",
    );
    process.exit(1);
  }
}

ensureUv();

const skill = join(pkgRoot, "skills", "callimachus");
const extension = join(pkgRoot, "extensions", "litreview", "index.ts");
const piArgs = ["-e", extension, "--skill", skill, ...process.argv.slice(2)];

const bundled = bundledPi();
const cmd = bundled ? process.execPath : "pi";
const argv = bundled ? [bundled, ...piArgs] : piArgs;

const child = spawn(cmd, argv, { stdio: "inherit" });
child.on("error", () => {
  console.error("Could not launch Pi. Install it with:\n  npm install -g @earendil-works/pi-coding-agent");
  process.exit(1);
});
child.on("exit", (code) => process.exit(code ?? 0));
