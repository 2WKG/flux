import { build } from "esbuild";
import { cp, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const dist = new URL("../dist/", import.meta.url);
await rm(dist, { recursive: true, force: true }); await mkdir(new URL("assets/", dist), { recursive: true }); await cp(new URL("../index.html", import.meta.url), new URL("index.html", dist));
await build({ entryPoints: [fileURLToPath(new URL("../src/main.tsx", import.meta.url))], bundle: true, format: "esm", platform: "browser", target: "es2020", outfile: fileURLToPath(new URL("assets/app.js", dist)), sourcemap: true });
