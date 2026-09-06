// The origin for the one App.
//
// It still hosts **no API of its own**: 2WKG-300 settled that, and the Copilot
// API remains a separate FastAPI service (docs/specs/05-copilot.md). What it now
// does, and only when `FLUX_API_ORIGIN` is set, is forward a fixed allowlist of
// that service's read paths from this same origin. That is a deployment seam,
// not an API: with the variable unset — which is the default, and the state of a
// fresh clone — every one of those paths falls through to the SPA shell exactly
// as before, and the page renders its named unavailable states.
//
// The seam exists because the page's own CSP is `connect-src 'self'`. A demo
// served beside a live Copilot needs the API on this origin or the browser
// blocks it; the alternative is a CORS exception and an off-origin CSP
// allowance, which is strictly worse.
import express from "express";
import { Readable } from "node:stream";
import { fileURLToPath, pathToFileURL } from "node:url";

const dist = fileURLToPath(new URL("./dist/", import.meta.url));

/**
 * The read paths that may be forwarded, and the methods each accepts. Nothing
 * else is proxied — a path not in this table is served the SPA shell, so a new
 * upstream route cannot be reached by accident.
 */
const PROXIED = [
  { pattern: /^\/api\/v1\/grid\/layers\/[^/]+$/, methods: ["GET"] },
  { pattern: /^\/health$/, methods: ["GET"] },
  { pattern: /^\/layers\/[^/]+$/, methods: ["GET"] },
  { pattern: /^\/scenarios$/, methods: ["GET"] },
  { pattern: /^\/scenarios\/[^/]+$/, methods: ["GET"] },
  { pattern: /^\/ask$/, methods: ["POST"] },
];

/** Upstream deadline. An upstream that never answers must not hold a socket open. */
export const PROXY_TIMEOUT_MS = 30_000;

function proxied(pathname, method) {
  return PROXIED.some((entry) => entry.pattern.test(pathname) && entry.methods.includes(method));
}

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

/**
 * The shared failure envelope, in the shape `web/src/data/validation.ts` reads
 * (`copilot/api/envelope.py`). It is the only thing this origin ever says about
 * an API path it cannot answer -- never an HTML page, and never a 200.
 */
export function unavailableEnvelope({ message, reason, requestId }) {
  return {
    status: "unavailable",
    data: null,
    error: {
      code: "unavailable",
      message,
      retryable: true,
      retry_after_s: 30,
      details: { reason },
    },
    meta: { api_version: "v1", request_id: requestId, generated_at: new Date().toISOString() },
  };
}

/** The named reason an allowlisted path carries when this deployment has no upstream at all. */
export const NO_API_ORIGIN_REASON = "no_api_origin_configured";

export function createApp({ apiOrigin = process.env.FLUX_API_ORIGIN ?? process.env.FLUX_GRID_API_ORIGIN } = {}) {
  const app = express();
  app.use((_req, res, next) => {
    res.setHeader("Content-Security-Policy", CONTENT_SECURITY_POLICY);
    next();
  });
  if (apiOrigin) {
    const upstream = new URL(apiOrigin);
    app.use((req, res, next) => {
      const url = new URL(req.originalUrl, upstream);
      if (!proxied(url.pathname, req.method)) return next();
      // Only the path and query cross; the upstream origin is this process's,
      // never the client's, so a caller cannot redirect the forward.
      const target = new URL(url.pathname + url.search, upstream);
      const headers = { accept: req.headers.accept ?? "application/json" };
      if (req.headers["content-type"]) headers["content-type"] = req.headers["content-type"];
      const body = req.method === "POST" ? req : undefined;
      fetch(target, {
        method: req.method,
        headers,
        body,
        duplex: body ? "half" : undefined,
        signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      }).then((response) => {
        res.status(response.status);
        const type = response.headers.get("content-type");
        if (type) res.setHeader("content-type", type);
        const retryAfter = response.headers.get("retry-after");
        if (retryAfter) res.setHeader("retry-after", retryAfter);
        if (!response.body) return res.end();
        // Streamed, so a text/event-stream answer is not buffered to completion
        // before the browser sees its first frame.
        Readable.fromWeb(response.body).pipe(res);
      }).catch((error) => {
        // The upstream's absence is reported in the shape the browser's own
        // validator reads, so it becomes a named unavailable state rather than
        // an HTML error page parsed as a malformed response.
        res.status(503).setHeader("content-type", "application/json");
        res.end(JSON.stringify(unavailableEnvelope({
          message: `The configured API origin did not answer: ${error instanceof Error ? error.message : String(error)}`,
          reason: "upstream_unreachable",
          requestId: "proxy-upstream-unreachable",
        })));
      });
    });
  } else {
    // No upstream is configured -- the default, and the state of a fresh clone.
    // These paths used to fall through to the SPA shell, so `GET /health`
    // answered 200 with `index.html`; the browser's validator could only call
    // that a *malformed* response, which is a different and weaker claim than
    // "this deployment has no API". The allowlist is registered either way and
    // refuses by name, so the offline case fails honestly and retryably.
    app.use((req, res, next) => {
      if (!proxied(new URL(req.originalUrl, "http://placeholder.invalid").pathname, req.method)) return next();
      res.status(503).setHeader("content-type", "application/json");
      res.end(JSON.stringify(unavailableEnvelope({
        message: "This origin serves the App only; no Copilot API origin is configured for this deployment, so this read has no upstream to serve it.",
        reason: NO_API_ORIGIN_REASON,
        requestId: "proxy-no-api-origin",
      })));
    });
  }
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
