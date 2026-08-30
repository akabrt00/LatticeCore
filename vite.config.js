import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import fsSync from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import { LatticeWorkerManager, terminalJobStatuses } from "./server/latticeWorkerManager.js";
import { buildWorkerJobRequest } from "./server/latticeJobRequest.js";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

function resolvePythonExecutable() {
  const candidates = [
    process.env.LATTICECORE_PYTHON,
    path.join(rootDir, ".venv", "Scripts", "python.exe"),
    "python",
    "py",
  ].filter(Boolean);

  return candidates.find((candidate) => ["python", "py"].includes(candidate) || fsSync.existsSync(candidate)) ?? "python";
}

function runPythonGenerator(args, timeout = 300000) {
  return new Promise((resolve, reject) => {
    execFile(resolvePythonExecutable(), args, {
      cwd: rootDir,
      timeout,
      env: {
        ...process.env,
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1",
      },
    }, (error, stdout, stderr) => {
      if (error) {
        const diagnostic = String(stderr || stdout || error.message);
        const messages = [...diagnostic.matchAll(/(?:ValueError|RuntimeError):\s*([^\r\n]+)/g)];
        const publicMessage = messages.at(-1)?.[1] ?? "The geometry generator failed.";
        reject(Object.assign(new Error(publicMessage), { errorCode: "GENERATION_FAILED" }));
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const RESULT_TTL_MS = 60 * 60 * 1000;
const debugResults = new Map();
const batchResults = new Map();
const DEBUG_LAYERS = new Set([
  "seed-points", "raw-volume-voronoi-edges", "clipped-interior-centerlines", "interior-nodes",
  "raw-surface-voronoi-segments", "smoothed-surface-centerlines", "placed-surface-centerlines",
  "surface-nodes", "surface-to-interior-connectors", "combined-centerline-graph",
  "final-implicit-mesh",
]);

async function removeExpiredDebugResults() {
  const now = Date.now();
  for (const [resultId, result] of debugResults) {
    if (result.expiresAt > now) continue;
    debugResults.delete(resultId);
    await Promise.all([result.manifestPath, result.bufferPath].map((file) => fs.unlink(file).catch(() => {})));
  }
  for (const [resultId, result] of batchResults) {
    if (result.expiresAt > now) continue;
    batchResults.delete(resultId);
    await fs.rm(result.directory, { recursive: true, force: true }).catch(() => {});
  }
}

async function cacheStatus() {
  const cacheRoot = path.join(rootDir, "cache", "schema-v1");
  const entries = [];
  const levels = await fs.readdir(cacheRoot, { withFileTypes: true }).catch(() => []);
  for (const level of levels.filter((entry) => entry.isDirectory())) {
    const children = await fs.readdir(path.join(cacheRoot, level.name), { withFileTypes: true }).catch(() => []);
    for (const child of children.filter((entry) => entry.isDirectory())) {
      const entryPath = path.join(cacheRoot, level.name, child.name);
      const files = await fs.readdir(entryPath, { withFileTypes: true }).catch(() => []);
      let size = 0;
      for (const file of files.filter((entry) => entry.isFile())) {
        size += (await fs.stat(path.join(entryPath, file.name))).size;
      }
      entries.push({ entryPath, modified: (await fs.stat(entryPath)).mtimeMs, size });
    }
  }
  return {
    enabled: true,
    sizeBytes: entries.reduce((sum, entry) => sum + entry.size, 0),
    maximumSizeBytes: 5 * 1024 ** 3,
    itemCount: entries.length,
    oldestItem: entries.length ? new Date(Math.min(...entries.map((entry) => entry.modified))).toISOString() : null,
  };
}

function readRequestBody(req, maximumBytes = MAX_UPLOAD_BYTES) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > maximumBytes) {
        reject(Object.assign(new Error("Uploaded file exceeds the 100 MiB limit."), { errorCode: "FILE_TOO_LARGE" }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function parseMultipartFile(buffer, contentType) {
  const boundaryMatch = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType);
  if (!boundaryMatch) throw Object.assign(new Error("Multipart boundary is missing."), { errorCode: "INVALID_MULTIPART" });
  const delimiter = Buffer.from(`--${boundaryMatch[1] ?? boundaryMatch[2]}`);
  let cursor = 0;
  while ((cursor = buffer.indexOf(delimiter, cursor)) >= 0) {
    const headerStart = cursor + delimiter.length + 2;
    const headerEnd = buffer.indexOf(Buffer.from("\r\n\r\n"), headerStart);
    if (headerEnd < 0) break;
    const headers = buffer.subarray(headerStart, headerEnd).toString("utf8");
    const filenameMatch = /filename="([^"]*)"/i.exec(headers);
    const dataStart = headerEnd + 4;
    const nextBoundary = buffer.indexOf(delimiter, dataStart);
    if (filenameMatch && nextBoundary >= 0) {
      const dataEnd = Math.max(dataStart, nextBoundary - 2);
      return { originalName: path.basename(filenameMatch[1]), data: buffer.subarray(dataStart, dataEnd) };
    }
    cursor = headerEnd + 4;
  }
  throw Object.assign(new Error("Multipart request does not contain a file."), { errorCode: "MISSING_FILE" });
}

function latticePythonPlugin() {
  return {
    name: "latticecore-python-generator",
    configureServer(server) {
      const workerManager = new LatticeWorkerManager({
        rootDir,
        pythonExecutable: resolvePythonExecutable(),
      });
      workerManager.start().catch((error) => console.error("Lattice worker failed to start.", error));
      workerManager.cleanupExpired().catch(() => {});
      removeExpiredDebugResults().catch(() => {});
      const resultCleanupTimer = setInterval(() => {
        removeExpiredDebugResults().catch(() => {});
      }, 5 * 60 * 1000);
      resultCleanupTimer.unref();
      server.httpServer?.once("close", () => {
        clearInterval(resultCleanupTimer);
        workerManager.stop().catch(() => {});
      });

      server.middlewares.use("/api/lattice-worker/status", async (req, res) => {
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.setHeader("Cache-Control", "no-store");
        if (req.method === "GET") {
          res.end(JSON.stringify(workerManager.workerStatus()));
          return;
        }
        if (req.method === "POST") {
          try {
            const requestUrl = new URL(req.url ?? "", "http://127.0.0.1");
            res.end(JSON.stringify(await workerManager.clearMemoryCache(requestUrl.searchParams.get("scope") ?? "unused")));
          } catch (error) {
            res.statusCode = 503;
            res.end(JSON.stringify({ error: error.message }));
          }
          return;
        }
        res.statusCode = 405;
        res.end(JSON.stringify({ error: "Method not allowed." }));
      });

      server.middlewares.use("/api/lattice-worker/memory-sessions", async (req, res) => {
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.setHeader("Cache-Control", "no-store");
        if (req.method !== "GET") {
          res.statusCode = 405;
          res.end(JSON.stringify({ error: "Method not allowed." }));
          return;
        }
        try {
          res.end(JSON.stringify(await workerManager.memorySessions()));
        } catch (error) {
          res.statusCode = 503;
          res.end(JSON.stringify({ error: error.message }));
        }
      });

      server.middlewares.use("/api/health", async (_req, res) => {
        const worker = workerManager.workerStatus();
        const cacheDirectory = path.join(rootDir, "cache");
        const diskAvailable = await fs.access(cacheDirectory).then(() => true).catch(async () => {
          return fs.mkdir(cacheDirectory, { recursive: true }).then(() => true).catch(() => false);
        });
        const healthy = ["ready", "busy"].includes(worker.status);
        res.statusCode = healthy ? 200 : 503;
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.setHeader("Cache-Control", "no-store");
        res.end(JSON.stringify({
          status: healthy ? "ok" : "degraded",
          frontend: { status: "ok" },
          worker: {
            status: worker.status,
            responsiveness: worker.responsiveness,
            protocolVersion: worker.protocolVersion,
          },
          cache: {
            diskAvailable,
            memoryEnabled: true,
          },
          versions: {
            node: process.versions.node,
            ...(worker.versions ?? {
              python: null,
              numpy: null,
              scipy: null,
              pyvista: null,
              vtk: null,
            }),
          },
        }));
      });

      server.middlewares.use("/api/lattice-jobs", async (req, res) => {
        const requestUrl = new URL(req.url ?? "", "http://127.0.0.1");
        const pathname = requestUrl.pathname;
        res.setHeader("Cache-Control", "no-store");
        try {
          if ((pathname === "/" || pathname === "") && req.method === "POST") {
            const requestId = randomUUID();
            const exportsDirectory = path.join(rootDir, "exports");
            await fs.mkdir(exportsDirectory, { recursive: true });
            let input = null;
            const contentType = String(req.headers["content-type"] ?? "");
            if (contentType.startsWith("multipart/form-data")) {
              const upload = parseMultipartFile(await readRequestBody(req), contentType);
              const extension = path.extname(upload.originalName).toLowerCase();
              if (![".stl", ".obj"].includes(extension)) {
                throw Object.assign(new Error("Podporovány jsou pouze STL a OBJ."), { statusCode: 400 });
              }
              const inputPath = path.join(exportsDirectory, `job_input_${requestId}${extension}`);
              await fs.writeFile(inputPath, upload.data);
              input = { path: inputPath, originalName: upload.originalName };
            }
            const batchDirectory = path.join(exportsDirectory, `job_batch_${requestId}`);
            const paths = {
              outputPath: path.join(exportsDirectory, `job_result_${requestId}.stl`),
              metadataPath: path.join(exportsDirectory, `job_result_${requestId}.json`),
              densityCsvPath: path.join(exportsDirectory, `job_density_${requestId}.csv`),
              debugManifestPath: path.join(exportsDirectory, `job_debug_${requestId}.json`),
              debugBufferPath: path.join(exportsDirectory, `job_debug_${requestId}.bin`),
              batchDirectory,
              batchSummaryJsonPath: path.join(batchDirectory, "density_batch_summary.json"),
              batchSummaryCsvPath: path.join(batchDirectory, "density_batch_summary.csv"),
              batchZipPath: path.join(batchDirectory, "density_series.zip"),
              cacheDirectory: path.join(rootDir, "cache"),
            };
            const built = buildWorkerJobRequest(requestUrl.searchParams, paths, input);
            const job = workerManager.createJob(built.jobType, { arguments: built.arguments });
            res.statusCode = 202;
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            res.end(JSON.stringify(job));
            return;
          }

          const assetMatch = /^\/([^/]+)\/assets\/(.+)$/.exec(pathname);
          if (assetMatch && req.method === "GET") {
            const assetName = decodeURIComponent(assetMatch[2]);
            const asset = await workerManager.readAsset(assetMatch[1], assetName);
            if (!asset) {
              res.statusCode = 404;
              res.end(JSON.stringify({ error: "Výstupní soubor nebyl nalezen." }));
              return;
            }
            const extension = path.extname(asset.path).toLowerCase();
            const types = {
              ".stl": "model/stl",
              ".json": "application/json; charset=utf-8",
              ".csv": "text/csv; charset=utf-8",
              ".zip": "application/zip",
            };
            res.setHeader("Content-Type", types[extension] ?? "application/octet-stream");
            res.setHeader("Content-Disposition", `attachment; filename="${path.basename(asset.path)}"`);
            res.end(asset.data);
            return;
          }

          const eventsMatch = /^\/([^/]+)\/events$/.exec(pathname);
          if (eventsMatch && req.method === "GET") {
            const job = workerManager.jobs.get(eventsMatch[1]);
            if (!job) {
              res.statusCode = 404;
              res.end(JSON.stringify({ error: "Úloha nebyla nalezena." }));
              return;
            }
            res.statusCode = 200;
            res.setHeader("Content-Type", "text/event-stream; charset=utf-8");
            res.setHeader("Connection", "keep-alive");
            res.setHeader("X-Accel-Buffering", "no");
            const send = (event) => {
              if (!res.writableEnded) res.write(`data: ${JSON.stringify(event)}\n\n`);
            };
            send({ type: "job-state", ...workerManager.serializeJob(job) });
            for (const event of job.events) send(event);
            if (terminalJobStatuses.has(job.status)) {
              res.end();
              return;
            }
            const listener = (event) => {
              send(event);
              if (event.type === "terminal") cleanup(true);
            };
            const keepalive = setInterval(() => {
              if (!res.writableEnded) res.write(": keepalive\n\n");
            }, 12_000);
            keepalive.unref();
            const cleanup = (end = false) => {
              clearInterval(keepalive);
              workerManager.events.off(job.id, listener);
              if (end && !res.writableEnded) res.end();
            };
            workerManager.events.on(job.id, listener);
            req.once("close", () => cleanup());
            return;
          }

          const cancelMatch = /^\/([^/]+)\/cancel$/.exec(pathname);
          if (cancelMatch && req.method === "POST") {
            const job = workerManager.cancelJob(cancelMatch[1]);
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            if (!job) {
              res.statusCode = 404;
              res.end(JSON.stringify({ error: "Úloha nebyla nalezena." }));
            } else {
              res.end(JSON.stringify(job));
            }
            return;
          }

          const retryMatch = /^\/([^/]+)\/retry$/.exec(pathname);
          if (retryMatch && req.method === "POST") {
            const job = workerManager.retryJob(retryMatch[1]);
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            if (!job) {
              res.statusCode = 404;
              res.end(JSON.stringify({ error: "Úlohu nelze opakovat." }));
            } else {
              res.statusCode = 202;
              res.end(JSON.stringify(job));
            }
            return;
          }

          const jobMatch = /^\/([^/]+)$/.exec(pathname);
          if (jobMatch && req.method === "GET") {
            const job = workerManager.serializeJob(workerManager.jobs.get(jobMatch[1]));
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            if (!job) {
              res.statusCode = 404;
              res.end(JSON.stringify({ error: "Úloha nebyla nalezena." }));
            } else {
              res.end(JSON.stringify(job));
            }
            return;
          }
          res.statusCode = 404;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(JSON.stringify({ error: "Job endpoint nebyl nalezen." }));
        } catch (error) {
          res.statusCode = error.statusCode ?? 500;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(JSON.stringify({ error: error.message }));
        }
      });

      server.middlewares.use("/api/voronoi/result", async (req, res) => {
        await removeExpiredDebugResults();
        const match = /^\/([^/]+)\/(debug-manifest|debug-buffer)$/.exec(req.url?.split("?")[0] ?? "");
        const result = match ? debugResults.get(match[1]) : null;
        if (!result || result.expiresAt <= Date.now()) {
          res.statusCode = 404;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(JSON.stringify({ error: "Debug result was not found or has expired." }));
          return;
        }
        const target = match[2] === "debug-manifest" ? result.manifestPath : result.bufferPath;
        res.statusCode = 200;
        res.setHeader("Content-Type", match[2] === "debug-manifest" ? "application/json; charset=utf-8" : "application/octet-stream");
        res.setHeader("Cache-Control", "no-store");
        res.end(await fs.readFile(target));
      });

      server.middlewares.use("/api/voronoi/batch", async (req, res) => {
        await removeExpiredDebugResults();
        const match = /^\/([^/]+)\/(.+)$/.exec(req.url?.split("?")[0] ?? "");
        const result = match ? batchResults.get(match[1]) : null;
        const assetName = match ? decodeURIComponent(match[2]) : "";
        const target = result?.files.get(assetName);
        if (!result || !target || result.expiresAt <= Date.now()) {
          res.statusCode = 404;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(JSON.stringify({ error: "Batch result was not found or has expired." }));
          return;
        }
        const extension = path.extname(target).toLowerCase();
        const contentTypes = {
          ".stl": "model/stl",
          ".json": "application/json; charset=utf-8",
          ".csv": "text/csv; charset=utf-8",
          ".zip": "application/zip",
        };
        res.statusCode = 200;
        res.setHeader("Content-Type", contentTypes[extension] ?? "application/octet-stream");
        res.setHeader("Content-Disposition", `attachment; filename="${path.basename(target)}"`);
        res.setHeader("Cache-Control", "no-store");
        res.end(await fs.readFile(target));
      });

      server.middlewares.use("/api/lattice-cache", async (req, res) => {
        const requestUrl = new URL(req.url ?? "", "http://127.0.0.1");
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.setHeader("Cache-Control", "no-store");
        if (req.method === "GET") {
          res.end(JSON.stringify(await cacheStatus()));
          return;
        }
        const scope = requestUrl.searchParams.get("scope");
        const levels = scope === "final-mesh"
          ? ["final-mesh"]
          : scope === "surface"
            ? ["surface-working-mesh", "surface-labels", "surface-graph", "placed-surface", "connectors"]
            : scope === "all"
              ? null
              : undefined;
        if (levels === undefined) {
          res.statusCode = 400;
          res.end(JSON.stringify({ error: "Unsupported cache scope." }));
          return;
        }
        const cacheRoot = path.join(rootDir, "cache", "schema-v1");
        if (levels === null) {
          await fs.rm(cacheRoot, { recursive: true, force: true });
        } else {
          await Promise.all(levels.map((level) => fs.rm(path.join(cacheRoot, level), { recursive: true, force: true })));
        }
        res.end(JSON.stringify({ ok: true, scope }));
      });

      server.middlewares.use("/api/lattice-metadata", async (_req, res) => {
        try {
          const latestMetadataPath = path.join(rootDir, "exports", "web_lattice_preview.json");
          const metadata = await fs.readFile(latestMetadataPath, "utf8");
          res.statusCode = 200;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.setHeader("Cache-Control", "no-store");
          res.end(metadata);
        } catch (error) {
          res.statusCode = 404;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(JSON.stringify({ error: "No generated metadata is available yet." }));
        }
      });

      server.middlewares.use("/api/python-lattice", async (req, res) => {
        let cleanupPaths = [];
        let detectedFormat = null;
        let fileSizeBytes = 0;
        try {
          const requestUrl = new URL(req.url ?? "", "http://127.0.0.1");
          const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
          const outputPath = path.join(rootDir, "exports", `web_lattice_preview_${requestId}.stl`);
          const metadataPath = path.join(rootDir, "exports", `web_lattice_preview_${requestId}.json`);
          const debugManifestPath = path.join(rootDir, "exports", `web_lattice_debug_${requestId}.json`);
          const debugBufferPath = path.join(rootDir, "exports", `web_lattice_debug_${requestId}.bin`);
          const densityCsvPath = path.join(rootDir, "exports", `web_lattice_density_${requestId}.csv`);
          const batchDirectory = path.join(rootDir, "exports", `web_lattice_batch_${requestId}`);
          const batchSummaryJsonPath = path.join(batchDirectory, "density_batch_summary.json");
          const batchSummaryCsvPath = path.join(batchDirectory, "density_batch_summary.csv");
          const batchZipPath = path.join(batchDirectory, "density_series.zip");
          const latestOutputPath = path.join(rootDir, "exports", "web_lattice_preview.stl");
          const latestMetadataPath = path.join(rootDir, "exports", "web_lattice_preview.json");
          const points = Number(requestUrl.searchParams.get("points") ?? 80);
          const radius = Number(requestUrl.searchParams.get("radius") ?? 20);
          const boxSizeX = Number(requestUrl.searchParams.get("boxSizeX") ?? 0);
          const boxSizeY = Number(requestUrl.searchParams.get("boxSizeY") ?? 0);
          const boxSizeZ = Number(requestUrl.searchParams.get("boxSizeZ") ?? 0);
          const tubeRadius = Number(requestUrl.searchParams.get("tubeRadius") ?? 0.225);
          const minStrutLengthMm = Number(requestUrl.searchParams.get("minStrutLengthMm") ?? 0);
          const seed = Number(requestUrl.searchParams.get("seed") ?? 42);
          const boundaryMode = requestUrl.searchParams.get("boundaryMode") === "centerline" ? "centerline" : "exact";
          const meshEngine = requestUrl.searchParams.get("meshEngine") === "implicit-union" ? "implicit-union" : "legacy-primitives";
          const qualityPreset = ["preview", "standard", "high", "custom"].includes(requestUrl.searchParams.get("qualityPreset"))
            ? requestUrl.searchParams.get("qualityPreset")
            : "standard";
          const voxelSizeMm = Number(requestUrl.searchParams.get("voxelSizeMm") ?? 0.15);
          const importScale = Number(requestUrl.searchParams.get("importScale") ?? 1);
          const componentMode = ["require-single", "keep-largest", "use-all-closed"].includes(requestUrl.searchParams.get("componentMode"))
            ? requestUrl.searchParams.get("componentMode")
            : "use-all-closed";
          const finalComponentMode = requestUrl.searchParams.get("finalComponentMode") === "keep-largest" ? "keep-largest" : "keep-all";
          const boundaryOffsetMm = Number(requestUrl.searchParams.get("boundaryOffsetMm") ?? 0);
          const targetCellSizeMm = Number(requestUrl.searchParams.get("targetCellSizeMm") ?? 0);
          const maximumSamplingAttempts = Number(requestUrl.searchParams.get("maximumSamplingAttempts") ?? 1000000);
          if (!Number.isFinite(maximumSamplingAttempts) || maximumSamplingAttempts < 1000 || maximumSamplingAttempts > 5000000) {
            throw Object.assign(
              new Error("Maximum sampling attempts must be between 1,000 and 5,000,000."),
              { errorCode: "INVALID_PARAMETER" },
            );
          }
          const boundaryStructureMode = requestUrl.searchParams.get("boundaryStructureMode") === "conformal-surface"
            ? "conformal-surface"
            : requestUrl.searchParams.get("boundaryStructureMode") === "open-volume"
              ? "open-volume"
              : "conformal-surface";
          const surfaceSamplingMode = requestUrl.searchParams.get("surfaceSamplingMode") === "custom" ? "custom" : "automatic";
          const surfaceSamplingStepMm = Number(requestUrl.searchParams.get("surfaceSamplingStepMm") ?? 0.5);
          const surfaceStrutDiameterMm = Number(requestUrl.searchParams.get("surfaceStrutDiameterMm") ?? tubeRadius * 2);
          const surfacePlacementMode = requestUrl.searchParams.get("surfacePlacementMode") === "on-surface-clipped"
            ? "on-surface-clipped"
            : "inset-inside";
          const surfaceInsetMode = requestUrl.searchParams.get("surfaceInsetMode") === "custom" ? "custom" : "automatic";
          const surfaceInsetMm = Number(requestUrl.searchParams.get("surfaceInsetMm") ?? surfaceStrutDiameterMm / 2);
          const surfaceSmoothingIterations = Number(requestUrl.searchParams.get("surfaceSmoothingIterations") ?? 2);
          const surfaceSmoothingStrength = Number(requestUrl.searchParams.get("surfaceSmoothingStrength") ?? 0.35);
          const connectSurfaceToInterior = requestUrl.searchParams.get("connectSurfaceToInterior") !== "false";
          const connectorSpacingMm = Number(requestUrl.searchParams.get("connectorSpacingMm") ?? 5);
          const connectorMaximumLengthMm = Number(requestUrl.searchParams.get("connectorMaximumLengthMm") ?? 15);
          const connectorDiameterMm = Number(requestUrl.searchParams.get("connectorDiameterMm") ?? tubeRadius * 2);
          const removeDisconnectedComponents = requestUrl.searchParams.get("removeDisconnectedComponents") === "true";
          const surfaceOnly = requestUrl.searchParams.get("surfaceOnly") === "true";
          const cacheEnabled = requestUrl.searchParams.get("cacheEnabled") !== "false";
          const densityControlMode = requestUrl.searchParams.get("densityControlMode") === "target-relative-density"
            ? "target-relative-density"
            : "direct-dimensions";
          const targetRelativeDensity = Number(requestUrl.searchParams.get("targetRelativeDensity") ?? 0.1);
          const densityTolerancePercentPoints = Number(requestUrl.searchParams.get("densityTolerancePercentPoints") ?? 0.5);
          const densityMinimumScale = Number(requestUrl.searchParams.get("densityMinimumScale") ?? 0.25);
          const densityMaximumScale = Number(requestUrl.searchParams.get("densityMaximumScale") ?? 3);
          const densityMaximumIterations = Number(requestUrl.searchParams.get("densityMaximumIterations") ?? 12);
          const densitySolverQuality = ["preview", "standard", "final-quality"].includes(requestUrl.searchParams.get("densitySolverQuality"))
            ? requestUrl.searchParams.get("densitySolverQuality")
            : "standard";
          const densityScalingPolicy = requestUrl.searchParams.get("densityScalingPolicy") === "interior-only"
            ? "interior-only"
            : "all-active-radii";
          const verifyAtFinalQuality = requestUrl.searchParams.get("verifyAtFinalQuality") !== "false";
          const materialDensityGPerCm3 = Number(requestUrl.searchParams.get("materialDensityGPerCm3") ?? 0);
          const minimumPrintableStrutDiameterMm = Number(requestUrl.searchParams.get("minimumPrintableStrutDiameterMm") ?? 0.4);
          const maximumAllowedStrutDiameterMm = Number(requestUrl.searchParams.get("maximumAllowedStrutDiameterMm") ?? 20);
          const maximumFinalCorrectionIterations = Number(requestUrl.searchParams.get("maximumFinalCorrectionIterations") ?? 4);
          const finalScaleTolerance = Number(requestUrl.searchParams.get("finalScaleTolerance") ?? 0.0005);
          const densityBatchTargetsPercent = requestUrl.searchParams.get("densityBatchTargetsPercent") ?? "";
          const batchFailurePolicy = requestUrl.searchParams.get("batchFailurePolicy") === "stop-on-error"
            ? "stop-on-error"
            : "continue";
          const isDensityBatch = densityControlMode === "target-relative-density" && densityBatchTargetsPercent.trim() !== "";
          const debugMode = ["requested", "all"].includes(requestUrl.searchParams.get("debugMode"))
            ? requestUrl.searchParams.get("debugMode")
            : "none";
          const debugLayers = (requestUrl.searchParams.get("debugLayers") ?? "")
            .split(",").filter((name) => DEBUG_LAYERS.has(name));
          const debugMaximumPoints = Math.max(1, Math.min(1_000_000, Number(requestUrl.searchParams.get("debugMaximumPoints") ?? 100000)));
          const debugMaximumSegments = Math.max(1, Math.min(1_000_000, Number(requestUrl.searchParams.get("debugMaximumSegments") ?? 200000)));
          const isUploadedMeshRequest = req.method === "POST";
          cleanupPaths = [outputPath, metadataPath];

          const generatorArgs = [
            "python_app/voronoi_sphere_lines_mvp.py",
            "--points",
            String(Math.round(points)),
            "--radius",
            String(radius),
            "--box-size-x",
            String(boxSizeX),
            "--box-size-y",
            String(boxSizeY),
            "--box-size-z",
            String(boxSizeZ),
            "--tube-radius",
            String(tubeRadius),
            "--surface-tube-radius",
            String(tubeRadius * 1.04),
            "--surface-points",
            "0",
            "--min-strut-length-mm",
            String(minStrutLengthMm),
            "--random-seed",
            String(Math.round(seed)),
            "--boundary-mode",
            boundaryMode,
            "--mesh-engine",
            meshEngine,
            "--quality-preset",
            qualityPreset,
            "--voxel-size-mm",
            String(voxelSizeMm),
            "--import-scale",
            String(importScale),
            "--component-mode",
            componentMode,
            "--final-component-mode",
            finalComponentMode,
            "--boundary-offset-mm",
            String(boundaryOffsetMm),
            "--target-cell-size-mm",
            String(targetCellSizeMm),
            "--maximum-sampling-attempts",
            String(Math.round(maximumSamplingAttempts)),
            "--boundary-structure-mode",
            boundaryStructureMode,
            "--surface-sampling-mode",
            surfaceSamplingMode,
            "--surface-sampling-step-mm",
            String(surfaceSamplingStepMm),
            "--surface-strut-diameter-mm",
            String(surfaceStrutDiameterMm),
            "--surface-placement-mode",
            surfacePlacementMode,
            "--surface-inset-mode",
            surfaceInsetMode,
            "--surface-inset-mm",
            String(surfaceInsetMm),
            "--surface-smoothing-iterations",
            String(Math.round(surfaceSmoothingIterations)),
            "--surface-smoothing-strength",
            String(surfaceSmoothingStrength),
            "--surface-connector-spacing-mm",
            String(connectorSpacingMm),
            "--surface-connector-maximum-length-mm",
            String(connectorMaximumLengthMm),
            "--surface-connector-diameter-mm",
            String(connectorDiameterMm),
            "--no-show",
            "--export-stl",
            outputPath,
            "--metadata-json",
            metadataPath,
            "--material-density-g-per-cm3",
            String(Math.max(0, materialDensityGPerCm3)),
          ];
          if (densityControlMode === "target-relative-density") {
            if (!(targetRelativeDensity > 0 && targetRelativeDensity <= 1)) {
              throw Object.assign(new Error("Target relative density must be between 0 and 1."), { errorCode: "INVALID_PARAMETER" });
            }
            generatorArgs[0] = "python_app/density_runner.py";
            generatorArgs.splice(1, 0,
              "--target-relative-density", String(targetRelativeDensity),
              "--density-tolerance-percent-points", String(densityTolerancePercentPoints),
              "--density-minimum-scale", String(densityMinimumScale),
              "--density-maximum-scale", String(densityMaximumScale),
              "--density-maximum-iterations", String(Math.round(densityMaximumIterations)),
              "--density-solver-quality", densitySolverQuality,
              "--density-scaling-policy", densityScalingPolicy,
              "--maximum-final-correction-iterations", String(Math.max(0, Math.round(maximumFinalCorrectionIterations))),
              "--final-scale-tolerance", String(finalScaleTolerance),
              verifyAtFinalQuality ? "--verify-at-final-quality" : "--no-verify-at-final-quality",
              "--minimum-printable-strut-diameter-mm", String(minimumPrintableStrutDiameterMm),
              "--maximum-allowed-strut-diameter-mm", String(maximumAllowedStrutDiameterMm),
              "--density-csv", densityCsvPath,
            );
            cleanupPaths.push(densityCsvPath);
            if (isDensityBatch) {
              generatorArgs.splice(1, 0,
                "--density-batch-targets-percent", densityBatchTargetsPercent,
                "--batch-failure-policy", batchFailurePolicy,
                "--batch-output-directory", batchDirectory,
                "--batch-summary-json", batchSummaryJsonPath,
                "--batch-summary-csv", batchSummaryCsvPath,
                "--batch-zip", batchZipPath,
              );
              cleanupPaths.push(batchDirectory);
            }
          }
          if (debugMode !== "none" && (debugMode === "all" || debugLayers.length)) {
            generatorArgs.push(
              "--debug-mode", debugMode,
              "--debug-layers", debugLayers.join(","),
              "--debug-maximum-points", String(Math.round(debugMaximumPoints)),
              "--debug-maximum-segments", String(Math.round(debugMaximumSegments)),
              "--debug-manifest-json", debugManifestPath,
              "--debug-buffer-bin", debugBufferPath,
            );
          }
          if (removeDisconnectedComponents) {
            generatorArgs.push("--remove-disconnected-components");
          }
          if (surfaceOnly) {
            generatorArgs.push("--surface-only");
          }
          if (!connectSurfaceToInterior) {
            generatorArgs.push("--no-connect-surface-to-interior");
          }
          if (!cacheEnabled) {
            generatorArgs.push("--no-cache-enabled");
          }

          if (isUploadedMeshRequest) {
            const body = await readRequestBody(req);
            const contentType = String(req.headers["content-type"] ?? "");
            const upload = contentType.startsWith("multipart/form-data")
              ? parseMultipartFile(body, contentType)
              : { originalName: path.basename(String(req.headers["x-lattice-file-name"] ?? "upload.stl")), data: body };
            fileSizeBytes = upload.data.length;
            if (fileSizeBytes === 0) throw Object.assign(new Error("Uploaded mesh is empty."), { errorCode: "EMPTY_FILE" });
            const extension = path.extname(upload.originalName).toLowerCase();
            if (![".stl", ".obj"].includes(extension)) {
              throw Object.assign(new Error("Unsupported format. Upload STL or OBJ."), { errorCode: "UNSUPPORTED_FORMAT" });
            }
            detectedFormat = extension.slice(1);
            const inputPath = path.join(rootDir, "exports", `web_lattice_input_${requestId}${extension}`);
            await fs.writeFile(inputPath, upload.data);
            cleanupPaths.push(inputPath);
            generatorArgs.splice(1, 0, "--input-mesh", inputPath, "--source-original-name", upload.originalName);
          } else {
            generatorArgs.splice(1, 0, "--shape", "box");
            if (isDensityBatch) generatorArgs.splice(1, 0, "--source-original-name", "parametric_box.stl");
          }

          await runPythonGenerator(generatorArgs, isDensityBatch ? 30 * 60 * 1000 : 5 * 60 * 1000);

          if (isDensityBatch) {
            const summary = await fs.readFile(batchSummaryJsonPath, "utf8");
            const zip = await fs.readFile(batchZipPath);
            const resultId = randomUUID();
            const files = new Map([
              ["zip", batchZipPath],
              ["summary-json", batchSummaryJsonPath],
              ["summary-csv", batchSummaryCsvPath],
            ]);
            const batchFiles = await fs.readdir(batchDirectory);
            for (const fileName of batchFiles) files.set(fileName, path.join(batchDirectory, fileName));
            batchResults.set(resultId, {
              directory: batchDirectory,
              files,
              expiresAt: Date.now() + RESULT_TTL_MS,
            });
            cleanupPaths = cleanupPaths.filter((filePath) => filePath !== batchDirectory);
            await Promise.all(cleanupPaths.map((filePath) => fs.unlink(filePath).catch(() => {})));
            res.statusCode = 200;
            res.setHeader("Content-Type", "application/zip");
            res.setHeader("Cache-Control", "no-store");
            res.setHeader("X-Lattice-Batch-Summary", Buffer.from(summary, "utf8").toString("base64"));
            res.setHeader("X-Lattice-Batch-Result-Id", resultId);
            res.setHeader("X-Lattice-Batch-Zip-Bytes", String(zip.byteLength));
            res.end(zip);
            return;
          }

          const stl = await fs.readFile(outputPath);
          const metadata = await fs.readFile(metadataPath, "utf8");
          const densityCsv = fsSync.existsSync(densityCsvPath) ? await fs.readFile(densityCsvPath, "utf8") : "";
          let resultId = "";
          if (fsSync.existsSync(debugManifestPath) && fsSync.existsSync(debugBufferPath)) {
            resultId = randomUUID();
            debugResults.set(resultId, {
              manifestPath: debugManifestPath,
              bufferPath: debugBufferPath,
              expiresAt: Date.now() + RESULT_TTL_MS,
            });
          }
          await fs.copyFile(outputPath, latestOutputPath).catch(() => {});
          await fs.copyFile(metadataPath, latestMetadataPath).catch(() => {});
          await Promise.all(cleanupPaths.map((filePath) => fs.unlink(filePath).catch(() => {})));
          res.statusCode = 200;
          res.setHeader("Content-Type", "model/stl");
          res.setHeader("Cache-Control", "no-store");
          res.setHeader("X-Lattice-Metadata", Buffer.from(metadata, "utf8").toString("base64"));
          if (resultId) res.setHeader("X-Lattice-Result-Id", resultId);
          if (densityCsv) res.setHeader("X-Lattice-Density-CSV", Buffer.from(densityCsv, "utf8").toString("base64"));
          res.end(stl);
        } catch (error) {
          await Promise.all(cleanupPaths.map((filePath) => fs.rm(filePath, { recursive: true, force: true }).catch(() => {})));
          const errorMessage = error instanceof Error ? error.message : String(error);
          const errorCode = errorMessage.includes("boundary edges")
            ? "INPUT_NOT_WATERTIGHT"
            : errorMessage.includes("non-manifold")
              ? "INPUT_NON_MANIFOLD"
              : error?.errorCode ?? "GENERATION_FAILED";
          res.statusCode = errorCode === "FILE_TOO_LARGE" ? 413 : errorCode === "GENERATION_FAILED" ? 422 : 400;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(JSON.stringify({ errorCode, errorMessage, detectedFormat, fileSizeBytes }));
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [latticePythonPlugin()],
});
