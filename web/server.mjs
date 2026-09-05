import express from "express";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const app = express();
const port = Number(process.env.PORT || 4173);
const dist = fileURLToPath(new URL("./dist/", import.meta.url));
const bundle = new URL("../data/demo/bundle.json", import.meta.url);

app.get("/api/demo", async (req, res) => {
  let payload;
  try {
    payload = JSON.parse(await readFile(bundle, "utf8"));
  } catch (error) {
    const unavailable = error?.code === "ENOENT";
    res.status(unavailable ? 503 : 500).json({
      status: unavailable ? "unavailable" : "failed",
      code: unavailable ? "DEMO_INPUT_UNAVAILABLE" : "DEMO_BUNDLE_INVALID",
      message: unavailable
        ? "The selected demo result is unavailable because the generated bundle is missing."
        : "Flux could not read the generated demo bundle.",
      nextStep: "Run python model/generate_demo.py and reload the page.",
    });
    return;
  }

  const selectedScenarioId = typeof req.query.scenario === "string" ? req.query.scenario : "baseline";
  if (!payload.scenarios?.[selectedScenarioId]) {
    res.status(404).json({
      status: "unavailable",
      code: "SCENARIO_NOT_FOUND",
      message: `The requested scenario '${selectedScenarioId}' is not in this source-backed bundle.`,
      nextStep: "Choose a scenario listed by the selector or regenerate the bundle.",
    });
    return;
  }

  res.json({status: "available", selectedScenarioId, data: payload});
});

app.use(express.static(dist));
app.get("/{*path}", (_req, res) => res.sendFile(`${dist}/index.html`));
app.listen(port, () => console.log(`Flux is running at http://localhost:${port}`));
