import assert from "node:assert/strict";
import test from "node:test";

import { buildWorkerJobRequest } from "./latticeJobRequest.js";

const paths = {
  outputPath: "result.stl",
  metadataPath: "metadata.json",
  cacheDirectory: "cache",
  densityCsvPath: "density.csv",
  debugManifestPath: "debug.json",
  debugBufferPath: "debug.bin",
  batchDirectory: "batch",
  batchSummaryJsonPath: "batch.json",
  batchSummaryCsvPath: "batch.csv",
  batchZipPath: "batch.zip",
};

function argumentValue(argumentsList, flag) {
  const index = argumentsList.indexOf(flag);
  assert.notEqual(index, -1, `Missing worker argument ${flag}`);
  return argumentsList[index + 1];
}

test("worker defaults preserve all closed components and include conformal surface", () => {
  const request = buildWorkerJobRequest(new URLSearchParams(), paths);
  assert.equal(argumentValue(request.arguments, "--component-mode"), "use-all-closed");
  assert.equal(argumentValue(request.arguments, "--boundary-structure-mode"), "conformal-surface");
});

test("worker accepts explicit strict component and open-volume modes", () => {
  const params = new URLSearchParams({
    componentMode: "require-single",
    boundaryStructureMode: "open-volume",
  });
  const request = buildWorkerJobRequest(params, paths);
  assert.equal(argumentValue(request.arguments, "--component-mode"), "require-single");
  assert.equal(argumentValue(request.arguments, "--boundary-structure-mode"), "open-volume");
});
