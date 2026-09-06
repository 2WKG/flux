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
 *
 * This table is also the single definition of the *public* path surface
 * (2WKG-274). The Cloudflare Tunnel in `deploy/cloudflared/config.example.yml`
 * publishes exactly the GET entries below, derived by `INGRESS_PATH_PATTERN`,
 * so the edge cannot reach a path this same-origin forward refuses. `ingress`
 * is the same expression as `pattern`, written in the RE2 dialect cloudflared
 * uses and without the leading slash the joined alternation supplies;
 * `web/test/ingress-allowlist.test.mjs` asserts the two agree and that the
 * checked-in config carries the derived string verbatim.
 */
export const PROXIED = [
  { pattern: /^\/api\/v1\/grid\/layers\/[^/]+$/, ingress: "api/v1/grid/layers/[^/]+", methods: ["GET"] },
  { pattern: /^\/api\/v1\/grid\/asset-placements$/, ingress: "api/v1/grid/asset-placements", methods: ["GET"] },
  { pattern: /^\/assets\/flux-grid\/(?:manifest\.json|[A-Za-z0-9][A-Za-z0-9._/-]*)$/, ingress: "assets/flux-grid/(?:manifest\\.json|[A-Za-z0-9][A-Za-z0-9._/-]*)", methods: ["GET"] },
  { pattern: /^\/demo\/model$/, ingress: "demo/model", methods: ["GET"] },
  { pattern: /^\/health$/, ingress: "health", methods: ["GET"] },
  { pattern: /^\/layers\/[^/]+$/, ingress: "layers/[^/]+", methods: ["GET"] },
  { pattern: /^\/scenarios$/, ingress: "scenarios", methods: ["GET"] },
  { pattern: /^\/scenarios\/[^/]+$/, ingress: "scenarios/[^/]+", methods: ["GET"] },
  // POST. Cloudflared filters paths, not methods, so publishing this at the edge
  // would expose the Copilot ask surface to the public internet; it stays local.
  { pattern: /^\/ask$/, methods: ["POST"] },
];

/**
 * The `path:` regex the public edge must carry: exactly the GET half of
 * `PROXIED`, in table order. A path the edge admits but this forward refuses
 * would be a second, wider public API surface — the thing 2WKG-274 exists to
 * prevent.
 */
export const INGRESS_PATH_PATTERN =
  `^/(${PROXIED.filter((entry) => entry.methods.includes("GET")).map((entry) => entry.ingress).join("|")})$`;

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
  "connect-src 'self' blob:",
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
  // The static demo has no API implementation. Keep an API-shaped request out
  // of the client-side router so a caller receives an explicit unavailable
  // response rather than a successful HTML page that resembles an endpoint.
  const unavailableApi = (_req, res) => res
    .status(503)
    .type("text/plain")
    .send("The static Flux demo does not serve API routes.");
  app.get("/api", unavailableApi);
  app.get("/api/{*path}", unavailableApi);
  // `root` + relative name, not an interpolated absolute path: under Express 5 on Windows
  // `res.sendFile("<abs>/index.html")` raises NotFoundError, which 404s every SPA client route.
  app.get("/{*path}", (_req, res) => res.sendFile("index.html", { root: dist }));
  return app;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const port = Number(process.env.PORT || 4173);
  // Loopback by default. `listen(port)` with no host binds the unspecified address
  // (`::`, dual-stack), so this unauthenticated demo origin answered on the LAN while
  // README.md and docs/runbooks/local-startup.md promised loopback-only endpoints.
  // Binding an interface is now an explicit opt-in through HOST.
  const host = process.env.HOST || "127.0.0.1";
  const shown = host === "127.0.0.1" || host === "::1" ? "localhost" : host;
  createApp().listen(port, host, () => console.log(`Flux is running at http://${shown}:${port}`));
}
