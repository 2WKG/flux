// Static origin for the frozen demo. STACK-LOCK.md is the runtime contract: the built
// client bundles data/demo/bundle.json at build time and makes no runtime request, so this
// process serves files and nothing else. It exposes no API route by design (2WKG-300); do
// not add one here — the Copilot API is a separate FastAPI service (docs/specs/05-copilot.md).
import express from "express";
import { fileURLToPath, pathToFileURL } from "node:url";

const dist = fileURLToPath(new URL("./dist/", import.meta.url));

export function createApp() {
  const app = express();
  app.use(express.static(dist));
  // `root` + relative name, not an interpolated absolute path: under Express 5 on Windows
  // `res.sendFile("<abs>/index.html")` raises NotFoundError, which 404s every SPA client route.
  app.get("/{*path}", (_req, res) => res.sendFile("index.html", { root: dist }));
  return app;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const port = Number(process.env.PORT || 4173);
  createApp().listen(port, () => console.log(`Flux is running at http://localhost:${port}`));
}
