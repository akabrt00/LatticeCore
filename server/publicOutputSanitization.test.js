import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import { LatticeWorkerManager, sanitizePublic } from "./latticeWorkerManager.js";

const PRIVATE_PATH = /(?:[A-Za-z]:\\(?:Users|Windows|ProgramData|Temp)\\|\/(?:home|Users|tmp)\/)/i;

function assertPathFree(value, label) {
  const serialized = typeof value === "string" ? value : JSON.stringify(value);
  assert.equal(PRIVATE_PATH.test(serialized), false, `${label} leaked a private path`);
}

function unsafeArchiveName(name) {
  const normalized = String(name).replaceAll("\\", "/");
  return normalized.startsWith("/")
    || /^[A-Za-z]:\//.test(normalized)
    || normalized.split("/").includes("..");
}

test("health, worker, SSE, job and result payloads stay path-free", () => {
  const privateRoot = "C:\\Users\\example\\AppData\\Local\\Temp\\LatticeCore";
  const health = sanitizePublic({
    status: "ok",
    cacheDirectory: `${privateRoot}\\cache`,
    worker: {
      status: "ready",
      pythonExecutable: `${privateRoot}\\.venv\\Scripts\\python.exe`,
      memory: { processWorkingSetBytes: 1234 },
    },
  });
  const event = sanitizePublic({
    type: "job-progress",
    phase: "mesh",
    outputPath: `${privateRoot}\\exports\\result.stl`,
    fraction: 0.5,
  });
  const job = sanitizePublic({
    jobId: "job-1",
    payload: { arguments: ["--input-mesh", `${privateRoot}\\input.stl`] },
    result: {
      resultId: "result-1",
      metadata: {
        sourceOriginalName: "Desktop organizer.stl",
        metadataPath: `${privateRoot}\\result.json`,
      },
      stlUrl: "/api/lattice-jobs/job-1/assets/result.stl",
    },
  });

  assertPathFree(health, "health");
  assertPathFree(event, "SSE event");
  assertPathFree(job, "job/result metadata");
  assert.equal(job.result.metadata.sourceOriginalName, "Desktop organizer.stl");
});

test("public errors remove Windows, Unix and temporary paths", () => {
  const manager = new LatticeWorkerManager({
    rootDir: path.resolve("."),
    pythonExecutable: "python",
  });
  const errors = [
    "failed at C:\\Users\\example\\Desktop\\private.stl",
    "failed at /home/example/private.stl",
    "failed at /tmp/latticecore/job.json",
    "failed at /Users/example/private.stl",
  ].map((message) => manager.sanitizeError(message));

  for (const message of errors) assertPathFree(message, "error response");
});

test("CSV, JSON and ZIP public export contracts reject path-shaped data", () => {
  const csv = "targetDensityPercent,stlFileName\n8,parametric_box_density_08pct.stl\n";
  const json = {
    resultId: "result-1",
    assets: {
      summary: "/api/lattice-jobs/job-1/assets/density_batch_summary.json",
    },
  };
  const zipNames = [
    "density_batch_summary.csv",
    "density_batch_summary.json",
    "parametric_box_density_08pct.stl",
    "parametric_box_density_08pct_metadata.json",
  ];

  assertPathFree(csv, "CSV");
  assertPathFree(json, "JSON");
  assert.equal(zipNames.some(unsafeArchiveName), false);
  assert.equal(unsafeArchiveName("../private/result.stl"), true);
  assert.equal(unsafeArchiveName("C:\\Users\\example\\result.stl"), true);
});
