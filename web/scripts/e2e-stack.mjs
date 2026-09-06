/**
 * The origin the browser proof drives.
 *
 * `gate/web-e2e` used to serve `dist/` alone, with no `FLUX_API_ORIGIN`. That
 * is not the shape the App ships in any more: the one App is server-backed
 * (docs/specs/00-overview.md), and `web/server.mjs` registers its read
 * allowlist either way -- so with no upstream configured, `/health`,
 * `/layers/{name}`, `/api/v1/grid/layers/{layer}` **and**
 * `/assets/flux-grid/...` all answer 503 `no_api_origin_configured` from the
 * proxy itself. The last of those shadows the runtime model pack that is
 * committed under `web/public/assets/flux-grid/`, which is why the Asset Lab
 * could never load a model in the gate.
 *
 * This boots the real FastAPI app (`copilot.app:app`) beside the static origin
 * and points the forward at it, so the proof drives the deployed shape.
 *
 * There is deliberately **no fixture database**. A fresh clone has no
 * `data/duck/grid.duckdb` (docs/runbooks: expected first-run state, not a
 * fault), so the API answers its own named `unavailable` envelopes -- artifact
 * `database`, reason `missing` -- and the specs assert those named states. That
 * is a different and stronger claim than the old one: with no API at all the
 * refusal came from the proxy and said `no_api_origin_configured`, so a spec
 * that only checked "something says unavailable" could not tell a booted API
 * from an absent one. `e2e/static-explorer.spec.ts` now pins the API's own
 * reason, and killing this process turns the suite red.
 *
 * Env:
 *   PORT                  static origin port (default 4173)
 *   FLUX_E2E_API_PORT     API port (default: a free port)
 *   FLUX_E2E_API_ORIGIN   use an already-running API and skip the boot
 *   FLUX_E2E_PYTHON       interpreter that can `import copilot.app`
 */
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
const webRoot = path.join(repoRoot, "web");

/** Children this process owns, torn down together. */
const children = [];
let shuttingDown = false;

function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
  }
  if (typeof code === "number") process.exit(code);
}
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(signal, () => shutdown(0));
process.on("exit", () => shutdown());

async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));
  return String(port);
}

/**
 * The interpreter that can import the API. Explicit env wins; then the repo's
 * own `.venv`; then `uv sync` creates it. A missing interpreter is a loud
 * failure naming the command that fixes it -- never a silent fall-back to the
 * API-less origin, which is the state this script exists to end.
 */
function resolvePython() {
  const named = process.env.FLUX_E2E_PYTHON;
  if (named) return named;
  const venv = path.join(repoRoot, ".venv", "bin", "python");
  if (existsSync(venv)) return venv;

  // The bootstrap lives here, not in `.github/workflows/pr-gates.yml`, because
  // the gate step already runs `npm run test:e2e` and this is what that reaches.
  // A maintainer with `workflow` scope should hoist it to `astral-sh/setup-uv`
  // plus a cache step; until then the gate installs uv itself. Ordered by cost:
  // already on PATH, already installed for this user, then the vendor installer.
  const local = path.join(process.env.HOME ?? "", ".local", "bin", "uv");
  let uv = "uv";
  if (spawnSync(uv, ["--version"], { stdio: "ignore" }).status !== 0) {
    if (existsSync(local)) uv = local;
    else {
      console.log("[e2e-stack] uv not found; installing it");
      // Not `pip install --user`: on the runner image the system Python is
      // externally managed (PEP 668) and that call fails.
      spawnSync("sh", ["-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"], { stdio: "inherit" });
      if (existsSync(local)) uv = local;
      else if (spawnSync("pipx", ["install", "uv"], { stdio: "inherit" }).status === 0 && existsSync(local)) uv = local;
    }
  }
  console.log(`[e2e-stack] ${uv} sync --frozen`);
  const sync = spawnSync(uv, ["sync", "--frozen"], { cwd: repoRoot, stdio: "inherit" });
  if (sync.status !== 0 || !existsSync(venv)) {
    throw new Error(
      "e2e-stack cannot find a Python that imports copilot.app. Run `uv sync --frozen` "
      + "at the repository root, or set FLUX_E2E_PYTHON to an interpreter that has it.",
    );
  }
  return venv;
}

function track(child, label) {
  children.push(child);
  child.stdout?.on("data", (chunk) => process.stdout.write(`[${label}] ${chunk}`));
  child.stderr?.on("data", (chunk) => process.stdout.write(`[${label}] ${chunk}`));
  child.on("exit", (code, signal) => {
    if (shuttingDown) return;
    console.error(`[e2e-stack] ${label} exited early (code ${code}, signal ${signal})`);
    shutdown(1);
  });
  return child;
}

/** Poll, never fixed-sleep: a cold `import copilot.app` compiles bytecode for ~25 s and prints nothing. */
async function waitForHealth(origin, deadlineMs) {
  const deadline = Date.now() + deadlineMs;
  while (Date.now() < deadline) {
    try {
      // Any answer proves the app is serving. Without a DuckDB this is a 503
      // `unavailable` envelope, which is the state the specs assert.
      const response = await fetch(`${origin}/health`, { signal: AbortSignal.timeout(3_000) });
      if (response.status < 500 || response.headers.get("content-type")?.includes("json")) return;
    } catch { /* not up yet */ }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`the API did not answer ${origin}/health within ${deadlineMs} ms`);
}

const apiOrigin = process.env.FLUX_E2E_API_ORIGIN ?? await (async () => {
  const python = resolvePython();
  const port = process.env.FLUX_E2E_API_PORT ?? await freePort();
  const origin = `http://127.0.0.1:${port}`;
  console.log(`[e2e-stack] booting copilot.app on ${origin} with ${python}`);
  track(spawn(python, ["-m", "uvicorn", "copilot.app:app", "--host", "127.0.0.1", "--port", port], {
    cwd: repoRoot,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  }), "api");
  await waitForHealth(origin, 300_000);
  console.log(`[e2e-stack] API answering at ${origin}`);
  return origin;
})();

track(spawn(process.execPath, ["server.mjs"], {
  cwd: webRoot,
  env: { ...process.env, FLUX_API_ORIGIN: apiOrigin },
  stdio: ["ignore", "pipe", "pipe"],
}), "web");
