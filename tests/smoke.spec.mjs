// Recommended by Norma — fixed with Claude via Devin
// Vitest smoke tests for the critical flows: launcher start-up, structured logger, ledger round trip.
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createLogger } from "../scripts/log.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const launcher = join(root, "bin", "arlandria.js");
const ledgerScript = join(root, "skills", "callimachus", "scripts", "ledger.py");

describe("launcher", () => {
  it("prints the bundled Pi version with the banner suppressed", () => {
    const run = spawnSync(process.execPath, [launcher, "--version"], {
      encoding: "utf8",
      env: { ...process.env, ARLANDRIA_SKIP_UV_CHECK: "1", ARLANDRIA_QUIET: "1" },
    });
    expect(run.status).toBe(0);
    expect(run.stdout).toMatch(/\d+\.\d+\.\d+/);
    expect(run.stdout).not.toContain("▇");
  });

  it("logs the banner through the structured logger when not quiet", () => {
    const run = spawnSync(process.execPath, [launcher, "--version"], {
      encoding: "utf8",
      env: { ...process.env, ARLANDRIA_SKIP_UV_CHECK: "1", ARLANDRIA_QUIET: "" },
    });
    expect(run.status).toBe(0);
    expect(run.stdout).toMatch(/^\d{4}-\d{2}-\d{2}T[\d:.]+Z INFO \[arlandria\]\n/);
    expect(run.stdout).toContain("▇");
  });
});

describe("structured logger", () => {
  let out;
  let err;
  beforeEach(() => {
    out = vi.spyOn(process.stdout, "write").mockImplementation(() => true);
    err = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.ARLANDRIA_LOG_LEVEL;
  });

  it("tags lines with timestamp, level, component and metadata; routes by severity", () => {
    const log = createLogger("smoke");
    log.info("hello", { requestId: "r1" });
    log.error("boom");
    expect(out).toHaveBeenCalledTimes(1);
    expect(out.mock.calls[0][0]).toMatch(/^\d{4}-\d{2}-\d{2}T\S+ INFO \[smoke\] hello \{"requestId":"r1"\}\n$/);
    expect(err).toHaveBeenCalledTimes(1);
    expect(err.mock.calls[0][0]).toMatch(/ ERROR \[smoke\] boom\n$/);
  });

  it("honours ARLANDRIA_LOG_LEVEL", () => {
    const log = createLogger("smoke");
    log.debug("hidden by default");
    expect(out).not.toHaveBeenCalled();
    process.env.ARLANDRIA_LOG_LEVEL = "debug";
    log.debug("now visible");
    expect(out).toHaveBeenCalledTimes(1);
    process.env.ARLANDRIA_LOG_LEVEL = "error";
    log.warn("suppressed");
    expect(err).not.toHaveBeenCalled();
  });
});

describe("callimachus ledger", () => {
  let dir;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "arlandria-smoke-"));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("round-trips non-ASCII criteria through ledger.py as UTF-8", () => {
    const uv = spawnSync("uv", ["--version"], { stdio: "ignore" });
    if (uv.error || uv.status !== 0) return; // uv is a runtime requirement, not a test-time one
    const ledger = join(dir, "review", "ledger.json");
    const question = "Wie beeinflusst Kaffee die Schlafqualität? — 咖啡";
    const run = spawnSync("uv", ["run", ledgerScript, "criteria", "--ledger", ledger,
      "--include", "adults", "--exclude", "animal studies", "--question", question], { encoding: "utf8" });
    expect(run.status, run.stderr).toBe(0);
    expect(JSON.parse(run.stdout)).toMatchObject({ criteria_version: 1, question });
    const saved = JSON.parse(readFileSync(ledger, "utf8"));
    expect(saved.review_id).toBe("review");
    expect(saved.question).toBe(question);
    expect(saved.criteria.include).toEqual(["adults"]);
  });
});
