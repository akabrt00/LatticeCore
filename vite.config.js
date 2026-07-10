import { execFile } from "node:child_process";
import fsSync from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

function resolvePythonExecutable() {
  const candidates = [
    process.env.LATTICECORE_PYTHON,
    path.join(rootDir, ".venv", "Scripts", "python.exe"),
    path.join(process.env.USERPROFILE ?? "", "Desktop", "LatticeCore", ".venv", "Scripts", "python.exe"),
    "py",
  ].filter(Boolean);

  return candidates.find((candidate) => candidate === "py" || fsSync.existsSync(candidate)) ?? "py";
}

function runPythonGenerator(args) {
  return new Promise((resolve, reject) => {
    execFile(resolvePythonExecutable(), args, { cwd: rootDir, timeout: 120000 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`${error.message}\n${stderr || stdout}`));
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

function readRequestBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function latticePythonPlugin() {
  return {
    name: "latticecore-python-generator",
    configureServer(server) {
      server.middlewares.use("/api/python-lattice", async (req, res) => {
        try {
          const requestUrl = new URL(req.url ?? "", "http://127.0.0.1");
          const outputPath = path.join(rootDir, "exports", "web_lattice_preview.stl");
          const points = Number(requestUrl.searchParams.get("points") ?? 80);
          const radius = Number(requestUrl.searchParams.get("radius") ?? 20);
          const tubeRadius = Number(requestUrl.searchParams.get("tubeRadius") ?? 0.225);
          const seed = Number(requestUrl.searchParams.get("seed") ?? 42);
          const isUploadedMeshRequest = req.method === "POST";
          const inputPath = path.join(rootDir, "exports", "web_lattice_input.stl");

          const generatorArgs = [
            "python_app/voronoi_sphere_lines_mvp.py",
            "--points",
            String(Math.round(points)),
            "--radius",
            String(radius),
            "--tube-radius",
            String(tubeRadius),
            "--surface-tube-radius",
            String(tubeRadius * 1.04),
            "--surface-points",
            "0",
            "--random-seed",
            String(Math.round(seed)),
            "--no-show",
            "--export-stl",
            outputPath,
          ];

          if (isUploadedMeshRequest) {
            const inputStl = await readRequestBody(req);
            if (inputStl.length === 0) {
              throw new Error("Uploaded STL request body is empty.");
            }
            await fs.writeFile(inputPath, inputStl);
            generatorArgs.splice(1, 0, "--input-stl", inputPath);
          } else {
            generatorArgs.splice(1, 0, "--shape", "box");
          }

          await runPythonGenerator(generatorArgs);

          const stl = await fs.readFile(outputPath);
          res.statusCode = 200;
          res.setHeader("Content-Type", "model/stl");
          res.setHeader("Cache-Control", "no-store");
          res.end(stl);
        } catch (error) {
          res.statusCode = 500;
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ error: error instanceof Error ? error.message : String(error) }));
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [latticePythonPlugin()],
});
