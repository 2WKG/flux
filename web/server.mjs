// Static origin for the frozen demo. STACK-LOCK.md is the runtime contract: the built
// client bundles data/demo/bundle.json at build time and makes no runtime request, so this
// process serves files and nothing else. It exposes no API route by design (2WKG-300); do
// not add one here — the Copilot API is a separate FastAPI service (docs/specs/05-copilot.md).
import express from "express";
import { fileURLToPath, pathToFileURL } from "node:url";

const dist = fileURLToPath(new URL("./dist/", import.meta.url));
const mapDist = fileURLToPath(new URL("./dist-map/", import.meta.url));

/**
 * The offline demo's policy, sent as a header as well as the `index.html` meta tag.
 * A header covers `frame-ancestors` (which a meta tag cannot carry) and every
 * response, not just the shell. It names no off-origin source, so the basemap,
 * tiles, glyphs, sprites, and any API are all unreachable from the page.
 */
export const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "connect-src 'self'",
  "img-src 'self' data: blob:",
  "worker-src 'self' blob:",
  "child-src 'self' blob:",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'none'",
].join("; ");

export function createApp({ gridApiOrigin = process.env.FLUX_GRID_API_ORIGIN } = {}) {
  const app = express();
  app.use((_req, res, next) => {
    res.setHeader("Content-Security-Policy", CONTENT_SECURITY_POLICY);
    next();
  });
  // The normal static origin has no API. A configured local API is exposed only
  // through this same-origin, read-only proxy so the map browser never needs a
  // CORS exception or an off-origin CSP allowance.
  if (gridApiOrigin) {
    const origin = new URL(gridApiOrigin);
    app.get("/api/v1/grid/{*path}", async (req, res, next) => {
      try {
        const upstream = new URL(req.originalUrl, origin);
        const response = await fetch(upstream, { headers: { accept: "application/json" } });
        res.status(response.status);
        const type = response.headers.get("content-type");
        if (type) res.setHeader("content-type", type);
        res.send(Buffer.from(await response.arrayBuffer()));
      } catch (error) { next(error); }
    });
  }
  app.use("/map", express.static(mapDist));
  app.get("/map/{*path}", (_req, res) => res.sendFile("index.html", { root: mapDist }));
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
