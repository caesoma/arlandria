#!/usr/bin/env node
// Branded launcher. Prints the banner, then starts an interactive Pi session
// with the Callimachus skill + command extension on the path, so `/litreview`
// and `/literature-review` are available immediately. No build step: the
// extension is TypeScript loaded by Pi via jiti, and this launcher is plain JS.
import { spawn, spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { existsSync, readFileSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..");

const { CALLIMACHUS_ASCII_LOGO_TEXT } = await import(pathToFileURL(join(pkgRoot, "logo.mjs")).href);
if (!process.env.CALLIMACHUS_QUIET) {
  console.log("\n" + CALLIMACHUS_ASCII_LOGO_TEXT + "\n");
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
  if (process.env.CALLIMACHUS_SKIP_UV_CHECK) return;
  const probe = spawnSync("uv", ["--version"], { stdio: "ignore" });
  if (probe.error || probe.status !== 0) {
    console.error(
      "\nCallimachus needs `uv` to run its Python primitives (search, dedupe, resolve, ...),\n" +
        "but it is not on your PATH. Install it with:\n\n" +
        "  curl -LsSf https://astral.sh/uv/install.sh | sh\n\n" +
        "Then re-run. Docs: https://docs.astral.sh/uv/\n" +
        "(Set CALLIMACHUS_SKIP_UV_CHECK=1 to bypass this check.)\n",
    );
    process.exit(1);
  }
}

ensureUv();

const skill = join(pkgRoot, "skills", "literature-review");
const extension = join(pkgRoot, "extensions", "litreview", "index.ts");
const hypathiaExtension = join(pkgRoot, "extensions", "hypathia", "index.ts");
const hypathiaSkill = join(pkgRoot, "skills", "hypathia");
const piArgs = ["-e", extension, "-e", hypathiaExtension, "--skill", skill, "--skill", hypathiaSkill, ...process.argv.slice(2)];

const bundled = bundledPi();
const cmd = bundled ? process.execPath : "pi";
const argv = bundled ? [bundled, ...piArgs] : piArgs;

const child = spawn(cmd, argv, { stdio: "inherit" });
child.on("error", () => {
  console.error("Could not launch Pi. Install it with:\n  npm install -g @earendil-works/pi-coding-agent");
  process.exit(1);
});
child.on("exit", (code) => process.exit(code ?? 0));
