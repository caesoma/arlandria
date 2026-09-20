#!/usr/bin/env node
// Branded launcher. Prints the banner, then starts an interactive Pi session
// with the Callimachus and Hypatia skills and command extensions.
// No build step: Pi loads TypeScript extensions via jiti.
import { spawn, spawnSync } from "node:child_process";
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
    let directory = dirname(fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent")));
    while (dirname(directory) !== directory) {
      const metaPath = join(directory, "package.json");
      if (existsSync(metaPath)) {
        const meta = JSON.parse(readFileSync(metaPath, "utf8"));
        if (meta.name === "@earendil-works/pi-coding-agent") {
          const bin = typeof meta.bin === "string" ? meta.bin : meta.bin?.pi;
          const path = typeof bin === "string" ? join(directory, bin) : null;
          return path && existsSync(path) ? path : null;
        }
      }
      directory = dirname(directory);
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

const callimachusSkill = join(pkgRoot, "skills", "callimachus");
const callimachusExtension = join(pkgRoot, "extensions", "callimachus", "index.ts");
const hypatiaExtension = join(pkgRoot, "extensions", "hypatia", "index.ts");
const hypatiaSkill = join(pkgRoot, "skills", "hypatia");
const piArgs = ["-e", callimachusExtension, "-e", hypatiaExtension, "--skill", callimachusSkill, "--skill", hypatiaSkill, ...process.argv.slice(2)];

const bundled = bundledPi();
const cmd = bundled ? process.execPath : "pi";
const argv = bundled ? [bundled, ...piArgs] : piArgs;

const child = spawn(cmd, argv, { stdio: "inherit" });
child.on("error", () => {
  console.error("Could not launch Pi. Install it with:\n  npm install -g @earendil-works/pi-coding-agent");
  process.exit(1);
});
child.on("exit", (code) => process.exit(code ?? 0));
