// The origin for the one App.
//
// It still hosts **no API of its own**: 2WKG-300 settled that, and the Copilot
// API remains a separate FastAPI service (docs/specs/05-copilot.md). What it now
// does, and only when `FLUX_API_ORIGIN` is set, is forward a fixed allowlist of
// that service's public paths from this same origin. That is a deployment seam,
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
 * The public paths that may be forwarded, and the methods each accepts. Nothing
 * else is proxied — a path not in this table is served by the static origin, so
 * a new upstream route cannot be reached by accident.
 */
const PROXIED = [
  { pattern: /^\/api\/v1\/grid\/layers\/[^/]+$/, methods: ["GET"] },
  { pattern: /^\/health$/, methods: ["GET"] },
  { pattern: /^\/layers\/[^/]+$/, methods: ["GET"] },
  { pattern: /^\/scenarios$/, methods: ["GET"] },
  { pattern: /^\/scenarios\/[^/]+$/, methods: ["GET"] },
  { pattern: /^\/site-score$/, methods: ["POST"] },
  // Persisted cascade reads and interactive simulation writes intentionally
  // share this one path, with their distinct methods pinned here. `POST /cascade`
  // is the interactive simulation route PR #331 registers upstream; the entry
  // below is this origin's half of that seam and reaches nothing until #331 lands.
  { pattern: /^\/cascade$/, methods: ["GET", "POST"] },
  { pattern: /^\/scenario\/edit$/, methods: ["POST"] },
  { pattern: /^\/balance$/, methods: ["GET"] },
  { pattern: /^\/redundancy$/, methods: ["GET"] },
  { pattern: /^\/siting\/search$/, methods: ["POST"] },
  { pattern: /^\/minnesota\/smr\/validate$/, methods: ["POST"] },
  { pattern: /^\/mn\/comparisons$/, methods: ["POST"] },
  { pattern: /^\/ask$/, methods: ["POST"] },
];

/** Upstream deadline. An upstream that never answers must not hold a socket open. */
export const PROXY_TIMEOUT_MS = 30_000;

/**
 * Path first, method second. A path on the table is *always* answered by this
 * seam: a method the table does not carry is refused by name (405) rather than
 * falling through to the static origin, which would answer an API-shaped path
 * with an Express HTML 404 or — for a `GET` on a `POST`-only path — an HTTP 200
 * `index.html`. Both are the malformed-response defect this suite already kills
 * for `GET /health`.
 */
function allowlisted(pathname) {
  return PROXIED.find((entry) => entry.pattern.test(pathname));
}

/** The largest request body this origin will forward. Beyond it, a named refusal. */
export const MAX_FORWARDED_BODY_BYTES = 1024 * 1024;

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

/**
 * The same envelope for a refusal this origin makes on its own account -- a
 * method the allowlist does not carry, a cross-origin forward, a body over the
 * cap. These are the caller's fault and never retryable, so they take the
 * `error`/`invalid_input` half of the shared vocabulary
 * (`copilot/api/envelope.py`, `web/src/data/validation.ts`) rather than
 * `unavailable`. Same shape, same media type: still never an HTML page and
 * never a 200.
 */
export function refusedEnvelope({ message, reason, requestId }) {
  return {
    status: "error",
    data: null,
    error: {
      code: "invalid_input",
      message,
      retryable: false,
      retry_after_s: null,
      details: { reason },
    },
    meta: { api_version: "v1", request_id: requestId, generated_at: new Date().toISOString() },
  };
}

/** The named reason an allowlisted path carries when this deployment has no upstream at all. */
export const NO_API_ORIGIN_REASON = "no_api_origin_configured";

/** The named reasons this origin refuses a forward on its own account. */
export const METHOD_NOT_ALLOWED_REASON = "method_not_allowed";
export const CROSS_ORIGIN_REASON = "cross_origin_forward_refused";
export const BODY_TOO_LARGE_REASON = "request_body_too_large";

function refuse(res, status, { message, reason, requestId }) {
  res.status(status).setHeader("content-type", "application/json");
  res.end(JSON.stringify(refusedEnvelope({ message, reason, requestId })));
}

/**
 * The forward's own guards, applied before any byte leaves this process.
 *
 * `Origin` is the one thing a browser attaches that this seam can check: the
 * upstream's own `CORSMiddleware` never sees the real caller, because only the
 * path and query cross. Without this, any page on the internet could drive the
 * writes on this table as CORS-simple requests. A present `Origin` that is not
 * this server's own is refused; an absent one (a same-origin `GET`, curl, a
 * health check) is not, because there is nothing to check.
 *
 * Returns `null` when the forward may proceed, or `{ status, message, reason }`.
 */
function forwardRefusal(req, entry) {
  if (!entry.methods.includes(req.method)) {
    return {
      status: 405,
      reason: METHOD_NOT_ALLOWED_REASON,
      message: `This origin forwards ${entry.methods.join(", ")} on this path; ${req.method} is not on its allowlist.`,
    };
  }
  const origin = req.headers.origin;
  if (origin !== undefined && origin !== `${req.protocol}://${req.headers.host}`) {
    return {
      status: 403,
      reason: CROSS_ORIGIN_REASON,
      message: "This origin forwards same-origin requests only; the request named a different origin.",
    };
  }
  return null;
}

/**
 * Read the request body, refusing past the cap. The body is buffered rather
 * than piped so the cap is enforced on the bytes themselves and not on a
 * `content-length` a caller controls. Only the *request* is buffered: the
 * upstream's response is still streamed, so an SSE answer is unaffected.
 */
function readCappedBody(req) {
  const tooLarge = () => {
    const error = new Error(`request body exceeds ${MAX_FORWARDED_BODY_BYTES} bytes`);
    error.code = "FLUX_BODY_TOO_LARGE";
    return error;
  };
  const declared = Number(req.headers["content-length"]);
  if (Number.isFinite(declared) && declared > MAX_FORWARDED_BODY_BYTES) {
    // Refused before a byte is read. The rest of the upload is still drained so
    // the socket closes cleanly and the caller reads the refusal rather than a
    // reset connection.
    req.resume();
    return Promise.reject(tooLarge());
  }
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let refused = false;
    req.on("data", (chunk) => {
      if (refused) return;
      size += chunk.length;
      if (size > MAX_FORWARDED_BODY_BYTES) {
        // A `content-length` the caller controls is not the cap; the bytes are.
        refused = true;
        chunks.length = 0;
        reject(tooLarge());
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      if (!refused) resolve(Buffer.concat(chunks));
    });
    req.on("error", (error) => {
      if (!refused) reject(error);
    });
  });
}

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
      const entry = allowlisted(url.pathname);
      if (!entry) return next();
      const refusal = forwardRefusal(req, entry);
      if (refusal) {
        return refuse(res, refusal.status, { ...refusal, requestId: `proxy-${refusal.reason}` });
      }
      // Only the path and query cross; the upstream origin is this process's,
      // never the client's, so a caller cannot redirect the forward.
      const target = new URL(url.pathname + url.search, upstream);
      const headers = { accept: req.headers.accept ?? "application/json" };
      if (req.headers["content-type"]) headers["content-type"] = req.headers["content-type"];
      const readBody = req.method === "POST" ? readCappedBody(req) : Promise.resolve(undefined);
      readBody.then((body) => fetch(target, {
        method: req.method,
        headers,
        body,
        signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      })).then((response) => {
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
        if (error && error.code === "FLUX_BODY_TOO_LARGE") {
          req.resume();
          res.setHeader("connection", "close");
          return refuse(res, 413, {
            message: `This origin forwards request bodies up to ${MAX_FORWARDED_BODY_BYTES} bytes; this one is larger.`,
            reason: BODY_TOO_LARGE_REASON,
            requestId: `proxy-${BODY_TOO_LARGE_REASON}`,
          });
        }
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
      const entry = allowlisted(new URL(req.originalUrl, "http://placeholder.invalid").pathname);
      if (!entry) return next();
      const refusal = forwardRefusal(req, entry);
      if (refusal) {
        return refuse(res, refusal.status, { ...refusal, requestId: `proxy-${refusal.reason}` });
      }
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
  createApp().listen(port, () => console.log(`Flux is running at http://localhost:${port}`));
}
