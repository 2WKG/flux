import express from "express";
import { readFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const dist = fileURLToPath(new URL("./dist/", import.meta.url));
const defaultBundle = new URL("../data/demo/bundle.json", import.meta.url);

// Failure envelope for the Node stopgap API: {status, code, message, nextStep}. It predates
// copilot/api/envelope.py and is not the typed FastAPI contract; see docs/specs/10-minnesota-demo.md.
function problem(res, httpStatus, status, code, message, nextStep) {
  res.status(httpStatus).json({ status, code, message, nextStep });
}

export function createApp({ bundle = defaultBundle } = {}) {
  const app = express();

  app.get("/api/demo", async (req, res) => {
    let payload;
    try {
      payload = JSON.parse(await readFile(bundle, "utf8"));
    } catch (error) {
      const unavailable = error?.code === "ENOENT";
      problem(
        res,
        unavailable ? 503 : 500,
        unavailable ? "unavailable" : "failed",
        unavailable ? "DEMO_INPUT_UNAVAILABLE" : "DEMO_BUNDLE_INVALID",
        unavailable
          ? "The selected demo result is unavailable because the generated bundle is missing."
          : "Flux could not read the generated demo bundle.",
        "Run python model/generate_demo.py and reload the page.",
      );
      return;
    }

    const scenarios = payload?.scenarios;
    if (scenarios === null || typeof scenarios !== "object" || Array.isArray(scenarios)) {
      problem(res, 500, "failed", "DEMO_BUNDLE_INVALID",
        "The generated demo bundle has no scenario table.",
        "Run python model/generate_demo.py and reload the page.");
      return;
    }

    // The selector sends exactly one string. Repeated (`?scenario=a&scenario=b`) or
    // bracketed (`?scenario[]=a`) forms are malformed input and get a validation
    // envelope rather than a silent baseline default.
    const malformed = Object.keys(req.query).filter((key) => key !== "scenario" && /^scenario\b/.test(key));
    const raw = req.query.scenario;
    if (malformed.length > 0 || (raw !== undefined && typeof raw !== "string")) {
      problem(res, 400, "unavailable", "SCENARIO_ID_INVALID",
        "The scenario query parameter must be a single string value.",
        "Send at most one ?scenario=<id> using an id listed by the selector.");
      return;
    }

    const selectedScenarioId = raw ?? "baseline";
    // Own-property check: `constructor`, `__proto__`, `toString` are not scenarios.
    if (!Object.hasOwn(scenarios, selectedScenarioId) || !scenarios[selectedScenarioId]) {
      problem(res, 404, "unavailable", "SCENARIO_NOT_FOUND",
        `The requested scenario '${selectedScenarioId}' is not in this synthetic bundle.`,
        "Choose a scenario listed by the selector or regenerate the bundle.");
      return;
    }

    res.json({ status: "available", selectedScenarioId, data: payload });
  });

  app.use(express.static(dist));
  app.get("/{*path}", (_req, res) => res.sendFile(`${dist}/index.html`));
  return app;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const port = Number(process.env.PORT || 4173);
  createApp().listen(port, () => console.log(`Flux is running at http://localhost:${port}`));
}
