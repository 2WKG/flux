import express from "express";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const app = express(), port = Number(process.env.PORT || 4173), dist = fileURLToPath(new URL("./dist/", import.meta.url)), bundle = new URL("../data/demo/bundle.json", import.meta.url);
app.get("/api/demo", async (_req, res) => { try { res.type("json").send(await readFile(bundle, "utf8")); } catch { res.status(503).json({ error: "Demo data unavailable. Run python model/generate_demo.py." }); } });
app.use(express.static(dist)); app.get("/{*path}", (_req, res) => res.sendFile(`${dist}/index.html`)); app.listen(port, () => console.log(`Flux is running at http://localhost:${port}`));
