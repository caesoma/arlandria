import assert from "node:assert/strict";
import childProcess, { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { after, test } from "node:test";
import { pathToFileURL } from "node:url";
import { runInNewContext } from "node:vm";
import { createJiti } from "jiti";
import { ARLANDRIA_ASCII_LOGO_TEXT } from "../logo.mjs";

const jiti = createJiti(import.meta.url);
const { python } = await jiti.import("../extensions/hypatia/bridge.ts");
const sandbox = mkdtempSync(join(homedir(), ".arlandria-bootstrap-tests-"));
after(() => rmSync(sandbox, { recursive: true }));

test("Python bridge propagates JSON errors, raw diagnostics, exit codes, and invalid output", t => {
  let response;
  const mock = t.mock.method(childProcess, "spawnSync", () => response);
  syncBuiltinESMExports();
  t.after(() => { mock.mock.restore(); syncBuiltinESMExports(); });
  for (const [result, expected] of [
    [{ error: new Error("spawn uv ENOENT") }, /Cannot run Python skill script: spawn uv ENOENT/],
    [{ status: 1, stdout: '{"error":"Invalid evidence"}', stderr: "noise" }, /Invalid evidence/],
    [{ status: 2, stdout: "", stderr: "No Python" }, /No Python/],
    [{ status: 3, stdout: "non-JSON stdout", stderr: "" }, /non-JSON stdout/],
    [{ status: 4, stdout: "", stderr: "" }, /status 4/],
    [{ status: 5, stdout: '{"error":1}', stderr: "diagnostic" }, /diagnostic/],
    [{ status: 5, stdout: "null", stderr: "diagnostic" }, /diagnostic/],
    [{ status: 0, stdout: "invalid JSON", stderr: "" }, /JSON/],
    [{ error: new Error("ENOBUFS") }, /ENOBUFS/],
  ]) {
    response = result;
    assert.throws(() => python("schema", sandbox, { name: "Evidence" }), expected);
  }
  response = { status: 0, stdout: '{"ok":true}', stderr: "" };
  assert.deepEqual(python("snapshot", sandbox, { text: "α" }, "revision"), { ok: true });
  const [command, args, options] = mock.mock.calls.at(-1).arguments;
  assert.equal(command, "uv");
  assert.deepEqual(args.slice(-4), ["snapshot", sandbox, "--revision", "revision"]);
  assert.deepEqual(JSON.parse(options.input), { text: "α" });
  assert.equal(options.env.PYTHONIOENCODING, "utf-8");
  assert.equal(options.maxBuffer, 64 * 1024 * 1024);
});

test("Node version gate accepts supported boundaries and rejects unsupported releases", () => {
  const script = readFileSync(resolve("scripts/check-node-version.mjs"), "utf8");
  for (const [node, supported] of [
    ["20.20.0", false], ["22.18.9", false], ["22.19.0", true], ["22.99.0", true],
    ["23.0.0", true], ["24.0.0", true], ["24.99.0", true], ["25.0.0", false],
  ]) {
    const exits = [];
    const messages = [];
    runInNewContext(script, {
      process: { versions: { node }, exit: code => exits.push(code) },
      console: { error: text => messages.push(text) },
    });
    assert.deepEqual(exits, supported ? [] : [1], node);
    assert.equal(messages.length, supported ? 0 : 1);
    if (!supported) assert.ok(messages[0].includes(node));
  }
});

test("logo entrypoints print the banner and imports including the compatibility alias remain silent", () => {
  for (const name of ["logo.mjs", "logo.caps.mjs", "logo.latin.mjs"]) {
    const executed = spawnSync(process.execPath, [resolve(name)], { encoding: "utf8" });
    assert.equal(executed.status, 0, executed.stderr);
    if (name === "logo.latin.mjs") assert.equal(executed.stdout, "");
    else assert.ok(executed.stdout.trim().length > 0);
    const imported = spawnSync(process.execPath, ["--input-type=module", "-e", `import ${JSON.stringify(pathToFileURL(resolve(name)).href)}`], { encoding: "utf8" });
    assert.equal(imported.status, 0, imported.stderr);
    assert.equal(imported.stdout, "");
  }
});

function launcherFixture(bin = { pi: "cli.js" }) {
  const root = mkdtempSync(join(sandbox, "launcher-"));
  mkdirSync(join(root, "bin"));
  cpSync(resolve("bin/arlandria.js"), join(root, "bin/arlandria.js"));
  cpSync(resolve("logo.mjs"), join(root, "logo.mjs"));
  writeFileSync(join(root, "package.json"), JSON.stringify({ type: "module" }));
  const pkg = join(root, "node_modules/@earendil-works/pi-coding-agent");
  mkdirSync(pkg, { recursive: true });
  writeFileSync(join(pkg, "package.json"), JSON.stringify({
    name: "@earendil-works/pi-coding-agent", type: "module", exports: "./index.js", bin,
  }));
  writeFileSync(join(pkg, "index.js"), "");
  writeFileSync(join(pkg, "cli.js"),
    'console.log(JSON.stringify(process.argv.slice(2))); process.exit(Number(process.env.FIXTURE_EXIT || "0"));\n');
  return {
    root, pkg,
    run: (env = {}, args = []) => spawnSync(process.execPath, [join(root, "bin/arlandria.js"), ...args], {
      encoding: "utf8", timeout: 10000,
      env: { ...process.env, PATH: "", CALLIMACHUS_QUIET: "1", CALLIMACHUS_SKIP_UV_CHECK: "1", ...env },
    }),
  };
}

test("launcher bundles both skills, preserves arguments, and propagates child exit status", () => {
  for (const bin of [{ pi: "cli.js" }, "cli.js"]) {
    const fixture = launcherFixture(bin);
    const result = fixture.run({ FIXTURE_EXIT: "7" }, ["question with spaces", "--offline"]);
    assert.equal(result.status, 7, result.stderr);
    const args = JSON.parse(result.stdout);
    assert.deepEqual(args, [
      "-e", join(fixture.root, "extensions/callimachus/index.ts"),
      "-e", join(fixture.root, "extensions/hypatia/index.ts"),
      "--skill", join(fixture.root, "skills/callimachus"), "--skill", join(fixture.root, "skills/hypatia"),
      "question with spaces", "--offline",
    ]);
    const banner = fixture.run({ CALLIMACHUS_QUIET: "" });
    assert.ok(banner.stdout.includes(ARLANDRIA_ASCII_LOGO_TEXT));
  }
});

test("launcher fails clearly without uv or either Pi binary", () => {
  const fixture = launcherFixture();
  const noUv = fixture.run({ CALLIMACHUS_SKIP_UV_CHECK: "" });
  assert.equal(noUv.status, 1);
  assert.match(noUv.stderr, /needs `uv`/);
  rmSync(fixture.pkg, { recursive: true });
  const noPi = fixture.run();
  assert.equal(noPi.status, 1);
  assert.match(noPi.stderr, /Could not resolve bundled Pi/);
  assert.match(noPi.stderr, /Trying global pi/);
  assert.match(noPi.stderr, /Could not launch Pi/);
});

function executable(path, source) {
  writeFileSync(path, `#!${process.execPath}\n${source}\n`, { mode: 0o700 });
}

test("launcher falls back globally and probes uv without launching real services", { skip: process.platform === "win32" }, () => {
  const fixture = launcherFixture();
  const path = join(fixture.root, "executables");
  mkdirSync(path);
  executable(join(path, "uv"), 'process.exit(0);');
  executable(join(path, "pi"), 'console.log("global fixture"); process.exit(9);');
  for (const bin of [null, { pi: "missing.js" }, {}]) {
    writeFileSync(join(fixture.pkg, "package.json"), JSON.stringify({
      name: "@earendil-works/pi-coding-agent", exports: "./index.js", bin,
    }));
    const result = fixture.run({ PATH: path, CALLIMACHUS_SKIP_UV_CHECK: "" });
    assert.equal(result.status, 9, result.stderr);
    assert.match(result.stdout, /global fixture/);
  }
  writeFileSync(join(fixture.pkg, "package.json"), "{invalid JSON");
  const brokenPackage = fixture.run({ PATH: path });
  assert.equal(brokenPackage.status, 9);
  assert.match(brokenPackage.stderr, /Could not resolve bundled Pi/);
  executable(join(path, "uv"), "process.exit(1);");
  assert.equal(fixture.run({ PATH: path, CALLIMACHUS_SKIP_UV_CHECK: "" }).status, 1);
});

test("POSIX installer checks prerequisites and invokes only the mocked npm", { skip: process.platform === "win32" }, () => {
  const root = mkdtempSync(join(sandbox, "installer-"));
  executable(join(root, "node"), "process.exit(Number(process.env.FIXTURE_NODE_EXIT || 0));");
  executable(join(root, "npm"), 'console.log("npm fixture: " + process.argv.slice(2).join(" ")); process.exit(Number(process.env.FIXTURE_NPM_EXIT || 0));');
  const run = env => spawnSync("/bin/sh", [resolve("scripts/install/install.sh")], {
    encoding: "utf8", timeout: 10000, env: { ...process.env, PATH: root, ...env },
  });
  assert.equal(run({ FIXTURE_NODE_EXIT: "2" }).status, 2);
  const missingUv = run({});
  assert.equal(missingUv.status, 1);
  assert.match(missingUv.stderr, /uv not found/);
  assert.doesNotMatch(missingUv.stdout, /npm fixture/);
  executable(join(root, "uv"), "");
  assert.equal(run({ FIXTURE_NPM_EXIT: "3" }).status, 3);
  const success = run({});
  assert.equal(success.status, 0, success.stderr);
  assert.match(success.stdout, /npm fixture: install -g arlandria/);
  assert.match(success.stdout, /Done/);
});

const powershell = ["pwsh", "powershell"].find(command =>
  spawnSync(command, ["-NoProfile", "-NonInteractive", "-Command", "exit 0"], { timeout: 10000 }).status === 0);

test("PowerShell installer checks prerequisites, versions, and npm exit codes", { skip: !powershell && "PowerShell is not installed" }, () => {
  const script = `
    function Get-Command($Name, $ErrorAction) {
      if ($env:FIXTURE_MISSING -eq $Name) { return $null }
      return @{ Name = $Name }
    }
    function node {
      $global:LASTEXITCODE = [int]$env:FIXTURE_NODE_EXIT
      Write-Output $env:FIXTURE_NODE_VERSION
    }
    function npm {
      Write-Host ("npm fixture: " + ($args -join " "))
      $global:LASTEXITCODE = [int]$env:FIXTURE_NPM_EXIT
    }
    try {
      & '${resolve("scripts/install/install.ps1").replaceAll("'", "''")}'
      exit $LASTEXITCODE
    } catch {
      Write-Error $_
      exit 1
    }
  `;
  const run = env => spawnSync(powershell, ["-NoProfile", "-NonInteractive", "-Command", script], {
    encoding: "utf8", timeout: 10000,
    env: { ...process.env, FIXTURE_NODE_EXIT: "0", FIXTURE_NPM_EXIT: "0", FIXTURE_NODE_VERSION: "24.0.0", ...env },
  });
  for (const [env, code, message] of [
    [{ FIXTURE_MISSING: "node" }, 1, /Node not found/],
    [{ FIXTURE_NODE_EXIT: "3" }, 3, /Checking Node/],
    [{ FIXTURE_NODE_VERSION: "22.18.9" }, 1, /Need Node/],
    [{ FIXTURE_NODE_VERSION: "25.0.0" }, 1, /Need Node/],
    [{ FIXTURE_MISSING: "uv" }, 1, /uv not found/],
    [{ FIXTURE_NPM_EXIT: "4" }, 4, /npm fixture: install -g arlandria/],
    [{ FIXTURE_NODE_VERSION: "22.19.0" }, 0, /Done/],
    [{}, 0, /Done/],
  ]) {
    const result = run(env);
    assert.equal(result.status, code, result.stderr);
    assert.match(result.stdout + result.stderr, message);
  }
});
