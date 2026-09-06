// Behavioural tests for scripts/dev/launch_demo.sh and its two node helpers.
//
// The launcher had no test at all: PR #282's review had to drive it by hand and
// found that `--stop` exited 0 while both servers kept serving, that the
// occupied-port guard probed a different address family than the server bound,
// that the demo answered on the LAN while the docs promised loopback only, and
// that the asset check could not fail because the SPA catch-all answers 200 for
// every path. Each of those is a case below, and each case is paired with a
// control that shows the probe can tell the two states apart.
//
// Every process these tests start is stopped in the same test.
import assert from "node:assert/strict";
import { execFile, spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repo = fileURLToPath(new URL("../../", import.meta.url));
const launcher = path.join(repo, "scripts/dev/launch_demo.sh");
const portFree = path.join(repo, "scripts/dev/port_free.mjs");
const healthReady = path.join(repo, "scripts/dev/health_ready.mjs");
const dist = path.join(repo, "web/dist");

const TIMEOUT = { timeout: 180_000 };

// Always async: these helpers talk to HTTP servers running in *this* process, and
// a synchronous spawn would block the event loop so the server never accepts.
function run(command, args, options = {}) {
  return new Promise((resolve) => {
    execFile(command, args, { encoding: "utf8", timeout: 170_000, maxBuffer: 16 * 1024 * 1024, ...options }, (error, stdout, stderr) => {
      resolve({ status: error ? (typeof error.code === "number" ? error.code : 1) : 0, stdout, stderr });
    });
  });
}

const launch = (args, options) => run("bash", [launcher, ...args], options);

function runDir() {
  return mkdtempSync(path.join(os.tmpdir(), "flux-launch-test-"));
}

/** An unused port, chosen by the kernel and released before we hand it over. */
function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function connects(host, port, timeoutMs = 2000) {
  return new Promise((resolve) => {
    let settled = false;
    const socket = net.connect({ host, port });
    const done = (value) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(value);
    };
    socket.setTimeout(timeoutMs, () => done(false));
    socket.once("connect", () => done(true));
    socket.once("error", () => done(false));
  });
}

const lanAddress = Object.values(os.networkInterfaces())
  .flat()
  .find((entry) => entry && entry.family === "IPv4" && !entry.internal)?.address;

function decoy(port, host, handler) {
  const server = http.createServer(handler ?? ((_req, res) => res.writeHead(200).end("decoy")));
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => resolve({
      close: () => new Promise((done) => server.close(() => done())),
    }));
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * A throwaway repo the launcher can be pointed at, so a test that needs a broken
 * build never mutates the shared `web/dist/` that the other test files read.
 * `repo` is resolved from the script's own location, so copying the scripts is
 * enough to move the launcher's idea of the repo root.
 */
function sandboxRepo({ withAppBundle }) {
  const root = mkdtempSync(path.join(os.tmpdir(), "flux-launch-sandbox-"));
  mkdirSync(path.join(root, "scripts/dev"), { recursive: true });
  for (const name of ["launch_demo.sh", "port_free.mjs", "health_ready.mjs"]) {
    cpSync(path.join(repo, "scripts/dev", name), path.join(root, "scripts/dev", name));
  }
  mkdirSync(path.join(root, "web"), { recursive: true });
  // A copy, not a symlink: server.mjs resolves dist/ from its own real path.
  cpSync(path.join(repo, "web/server.mjs"), path.join(root, "web/server.mjs"));
  symlinkSync(path.join(repo, "web/node_modules"), path.join(root, "web/node_modules"));
  cpSync(dist, path.join(root, "web/dist"), { recursive: true });
  if (!withAppBundle) rmSync(path.join(root, "web/dist/assets/app.js"));
  return root;
}

test("start, status, and stop leave no listener behind", TIMEOUT, async (t) => {
  assert.ok(existsSync(path.join(dist, "assets/app.js")), "run `npm run build` in web/ first");
  const dir = runDir();
  const port = await freePort();
  t.after(async () => {
    await launch(["--run-dir", dir, "--stop"]);
    rmSync(dir, { recursive: true, force: true });
  });

  const started = await launch(["--offline", "--skip-install", "--skip-build", "--web-port", String(port), "--run-dir", dir]);
  assert.equal(started.status, 0, started.stderr);
  assert.match(started.stdout, /Flux offline demo ready/);
  assert.equal(await connects("127.0.0.1", port), true, "the demo should be serving on loopback");

  const status = await launch(["--run-dir", dir, "--status"]);
  assert.equal(status.status, 0, status.stderr);
  assert.match(status.stdout, new RegExp(`web: recorded=\\[\\d+.*port=${port} listening=yes`));

  const stopped = await launch(["--run-dir", dir, "--stop"]);
  assert.equal(stopped.status, 0, stopped.stderr);
  // The whole point: the port is released, not just the PID file removed.
  assert.equal(await connects("127.0.0.1", port), false, "--stop must leave the web port free");
  assert.equal(existsSync(path.join(dir, "web.pid")), false, "a stopped process leaves no PID file");

  const afterStatus = await launch(["--run-dir", dir, "--status"]);
  assert.equal(afterStatus.status, 1);
  assert.match(afterStatus.stdout, /No live processes recorded/);
});

test("the default bind is loopback only; --bind is the opt-in", TIMEOUT, async (t) => {
  if (!lanAddress) return t.skip("no non-loopback IPv4 interface on this host");
  const dir = runDir();
  const port = await freePort();
  t.after(async () => {
    await launch(["--run-dir", dir, "--stop"]);
    rmSync(dir, { recursive: true, force: true });
  });

  const started = await launch(["--offline", "--skip-install", "--skip-build", "--web-port", String(port), "--run-dir", dir]);
  assert.equal(started.status, 0, started.stderr);
  assert.equal(await connects("127.0.0.1", port), true);
  assert.equal(
    await connects(lanAddress, port),
    false,
    `README.md and docs/runbooks/local-startup.md claim loopback only, but ${lanAddress}:${port} answered`,
  );
  assert.equal((await launch(["--run-dir", dir, "--stop"])).status, 0);

  // Control: the same probe must see a LAN listener when one is asked for, or the
  // assertion above proves nothing.
  const openPort = await freePort();
  const opened = await launch(["--offline", "--skip-install", "--skip-build", "--bind", "0.0.0.0", "--web-port", String(openPort), "--run-dir", dir]);
  assert.equal(opened.status, 0, opened.stderr);
  assert.equal(await connects(lanAddress, openPort), true, "the probe cannot distinguish the two binds");
  assert.equal((await launch(["--run-dir", dir, "--stop"])).status, 0);
  assert.equal(await connects(lanAddress, openPort), false);
});

test("the occupied-port guard sees a listener on the other address family", TIMEOUT, async (t) => {
  const dir = runDir();
  const port = await freePort();
  const held = await decoy(port, "::");
  t.after(async () => {
    await launch(["--run-dir", dir, "--stop"]);
    await held.close();
    rmSync(dir, { recursive: true, force: true });
  });

  const probe = await run("node", [portFree, String(port), "127.0.0.1"]);
  assert.equal(probe.status, 1, "a listener on :: must make the port unavailable");

  const started = await launch(["--offline", "--skip-install", "--skip-build", "--web-port", String(port), "--run-dir", dir]);
  assert.notEqual(started.status, 0, "the launcher must refuse a port another process is answering");
  assert.match(started.stderr, /Web port is already in use/);
  assert.equal(existsSync(path.join(dir, "web.pid")), false);

  // Control: the same guard passes on a port nobody holds.
  const openPort = await freePort();
  assert.equal((await run("node", [portFree, String(openPort), "127.0.0.1"])).status, 0);
});

test("the asset check fails when the bundle is missing instead of accepting the SPA shell", TIMEOUT, async (t) => {
  const broken = sandboxRepo({ withAppBundle: false });
  const dir = runDir();
  const port = await freePort();
  t.after(async () => {
    await run("bash", [path.join(broken, "scripts/dev/launch_demo.sh"), "--run-dir", dir, "--stop"]);
    rmSync(broken, { recursive: true, force: true });
    rmSync(dir, { recursive: true, force: true });
  });

  const brokenLauncher = path.join(broken, "scripts/dev/launch_demo.sh");
  const started = await run("bash", [brokenLauncher, "--offline", "--skip-install", "--skip-build", "--web-port", String(port), "--run-dir", dir]);
  assert.notEqual(started.status, 0, "GET /assets/app.js answers 200 with the SPA shell; the check must still fail");
  assert.match(started.stderr, /--skip-build needs an existing build|not JavaScript|SPA shell/);
  assert.equal(await connects("127.0.0.1", port), false, "a failed launch must not strand the web server");

  // Control: the identical sandbox with the bundle present launches cleanly, so
  // the failure above is about the missing bundle and nothing else.
  const whole = sandboxRepo({ withAppBundle: true });
  const okDir = runDir();
  const okPort = await freePort();
  t.after(async () => {
    await run("bash", [path.join(whole, "scripts/dev/launch_demo.sh"), "--run-dir", okDir, "--stop"]);
    rmSync(whole, { recursive: true, force: true });
    rmSync(okDir, { recursive: true, force: true });
  });
  const ok = await run("bash", [path.join(whole, "scripts/dev/launch_demo.sh"), "--offline", "--skip-install", "--skip-build", "--web-port", String(okPort), "--run-dir", okDir]);
  assert.equal(ok.status, 0, ok.stderr);
});

test("a readiness timeout reports failure and cleans up the process it started", TIMEOUT, async (t) => {
  const dir = runDir();
  const port = await freePort();
  t.after(async () => {
    await launch(["--run-dir", dir, "--stop"]);
    rmSync(dir, { recursive: true, force: true });
  });

  const started = await launch([
    "--offline", "--skip-install", "--skip-build",
    "--web-port", String(port), "--run-dir", dir, "--ready-timeout", "0",
  ]);
  assert.notEqual(started.status, 0);
  assert.match(started.stderr, /Web app did not start within 0s/);
  // The old cleanup killed the wrapper subshell, so the node server kept the port.
  await sleep(1500);
  assert.equal(await connects("127.0.0.1", port), false, "a timed-out launch must not strand a listener");
  assert.equal(existsSync(path.join(dir, "web.pid")), false);
});

test("--stop refuses to report success while the recorded port is still answered", TIMEOUT, async (t) => {
  const dir = runDir();
  const port = await freePort();
  // A dead PID with a live listener on the recorded port is exactly the orphan
  // state #282's review hit: the old --stop deleted the breadcrumb and exited 0.
  const corpse = spawn("bash", ["-c", "exit 0"]);
  await new Promise((resolve) => corpse.once("exit", resolve));
  writeFileSync(path.join(dir, "web.pid"), `${corpse.pid}\n`);
  writeFileSync(path.join(dir, "web.port"), `${port}\n`);
  const held = await decoy(port, "127.0.0.1");
  t.after(async () => {
    await held.close();
    rmSync(dir, { recursive: true, force: true });
  });

  const stopped = await launch(["--run-dir", dir, "--stop"]);
  assert.equal(stopped.status, 1, "--stop must not claim success while the port is in use");
  assert.match(stopped.stderr, /still in use after --stop/);
  assert.equal(existsSync(path.join(dir, "web.port")), true, "the breadcrumb survives a failed stop");

  // Control: with the port released, the same stop succeeds and clears the files.
  await held.close();
  const clean = await launch(["--run-dir", dir, "--stop"]);
  assert.equal(clean.status, 0, clean.stderr);
  assert.equal(existsSync(path.join(dir, "web.port")), false);
});

test("readiness reads the /health body, not just the status code", TIMEOUT, async (t) => {
  const cases = [
    ["plain 200 from an unrelated server", (_q, res) => res.writeHead(200).end("OK"), 1],
    ["200 JSON that is not a health body", (_q, res) => res.writeHead(200, { "content-type": "application/json" }).end('{"hello":1}'), 1],
    ["the success body", (_q, res) => res.writeHead(200, { "content-type": "application/json" }).end('{"ok":true,"duckdb_path":"/tmp/x.duckdb","tables":[]}'), 0, "ok"],
    [
      "the unavailable envelope",
      (_q, res) => res.writeHead(503, { "content-type": "application/json" })
        .end('{"status":"unavailable","data":null,"error":{"code":"unavailable"},"meta":{"api_version":"v1"}}'),
      0,
      "unavailable",
    ],
  ];
  for (const [name, handler, expected, word] of cases) {
    const port = await freePort();
    const server = await decoy(port, "127.0.0.1", handler);
    try {
      const result = await run("node", [healthReady, `http://127.0.0.1:${port}/health`]);
      assert.equal(result.status, expected, `${name}: ${result.stderr}`);
      if (word) assert.equal(result.stdout.trim(), word, name);
    } finally {
      await server.close();
    }
  }
  // Control: nothing listening is not ready either.
  const dead = await freePort();
  assert.equal((await run("node", [healthReady, `http://127.0.0.1:${dead}/health`])).status, 1);
});

test("--stop walks down to a listener the recorded PID only wraps", TIMEOUT, async (t) => {
  // `uv run uvicorn` execs uvicorn as a child, so the PID the shell records with
  // `$!` sits above the process that holds the port (and the DuckDB read handle).
  // #282's --stop killed the wrapper, reported success, and deleted the PID file.
  const dir = runDir();
  const port = await freePort();
  const serve = `require("http").createServer((q, r) => r.end("x")).listen(${port}, "127.0.0.1")`;
  const wrapper = spawn("bash", ["-c", `node -e '${serve}' & wait`], { stdio: "ignore" });
  t.after(async () => {
    await run("bash", ["-c", `pkill -P ${wrapper.pid} 2>/dev/null; kill -9 ${wrapper.pid} 2>/dev/null; true`]);
    rmSync(dir, { recursive: true, force: true });
  });
  for (let i = 0; i < 100 && !(await connects("127.0.0.1", port)); i += 1) await sleep(100);
  assert.equal(await connects("127.0.0.1", port), true, "the wrapped listener never came up");

  writeFileSync(path.join(dir, "web.pid"), `${wrapper.pid}\n`);
  writeFileSync(path.join(dir, "web.port"), `${port}\n`);
  const stopped = await launch(["--run-dir", dir, "--stop"]);
  assert.equal(stopped.status, 0, stopped.stderr);
  assert.equal(await connects("127.0.0.1", port), false, "--stop must kill the wrapped listener, not just its parent");
  assert.equal(existsSync(path.join(dir, "web.pid")), false);
});
