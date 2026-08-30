const DEBUG_LAYERS = new Set([
  "seed-points", "raw-volume-voronoi-edges", "clipped-interior-centerlines", "interior-nodes",
  "raw-surface-voronoi-segments", "smoothed-surface-centerlines", "placed-surface-centerlines",
  "surface-nodes", "surface-to-interior-connectors", "combined-centerline-graph",
  "final-implicit-mesh",
]);

const number = (params, name, fallback) => {
  const value = Number(params.get(name) ?? fallback);
  if (!Number.isFinite(value)) throw Object.assign(new Error(`Neplatný parametr ${name}.`), { statusCode: 400 });
  return value;
};

const choice = (params, name, choices, fallback) => {
  const value = params.get(name);
  return choices.includes(value) ? value : fallback;
};

export function buildWorkerJobRequest(params, paths, input = null) {
  const points = number(params, "points", 80);
  const radius = number(params, "radius", 20);
  const boxX = number(params, "boxSizeX", 0);
  const boxY = number(params, "boxSizeY", 0);
  const boxZ = number(params, "boxSizeZ", 0);
  const tubeRadius = number(params, "tubeRadius", 0.225);
  const surfaceDiameter = number(params, "surfaceStrutDiameterMm", tubeRadius * 2);
  const connectorDiameter = number(params, "connectorDiameterMm", tubeRadius * 2);
  const densityMode = params.get("densityControlMode") === "target-relative-density";
  const batchTargets = params.get("densityBatchTargetsPercent")?.trim() ?? "";
  const isBatch = densityMode && Boolean(batchTargets);
  const argumentsList = [
    "--points", String(Math.round(points)),
    "--radius", String(radius),
    "--box-size-x", String(boxX),
    "--box-size-y", String(boxY),
    "--box-size-z", String(boxZ),
    "--tube-radius", String(tubeRadius),
    "--surface-tube-radius", String(tubeRadius * 1.04),
    "--surface-points", "0",
    "--min-strut-length-mm", String(number(params, "minStrutLengthMm", 0)),
    "--random-seed", String(Math.round(number(params, "seed", 42))),
    "--boundary-mode", choice(params, "boundaryMode", ["centerline", "exact"], "exact"),
    "--mesh-engine", choice(params, "meshEngine", ["implicit-union", "legacy-primitives"], "legacy-primitives"),
    "--quality-preset", choice(params, "qualityPreset", ["preview", "standard", "high", "custom"], "standard"),
    "--voxel-size-mm", String(number(params, "voxelSizeMm", 0.15)),
    "--import-scale", String(number(params, "importScale", 1)),
    "--component-mode", choice(params, "componentMode", ["require-single", "keep-largest", "use-all-closed"], "use-all-closed"),
    "--final-component-mode", choice(params, "finalComponentMode", ["keep-largest", "keep-all"], "keep-all"),
    "--boundary-offset-mm", String(number(params, "boundaryOffsetMm", 0)),
    "--target-cell-size-mm", String(number(params, "targetCellSizeMm", 0)),
    "--maximum-sampling-attempts", String(Math.round(number(params, "maximumSamplingAttempts", 1_000_000))),
    "--boundary-structure-mode", choice(params, "boundaryStructureMode", ["conformal-surface", "open-volume"], "conformal-surface"),
    "--surface-sampling-mode", choice(params, "surfaceSamplingMode", ["custom", "automatic"], "automatic"),
    "--surface-sampling-step-mm", String(number(params, "surfaceSamplingStepMm", 0.5)),
    "--surface-strut-diameter-mm", String(surfaceDiameter),
    "--surface-placement-mode", choice(params, "surfacePlacementMode", ["on-surface-clipped", "inset-inside"], "inset-inside"),
    "--surface-inset-mode", choice(params, "surfaceInsetMode", ["custom", "automatic"], "automatic"),
    "--surface-inset-mm", String(number(params, "surfaceInsetMm", surfaceDiameter / 2)),
    "--surface-smoothing-iterations", String(Math.round(number(params, "surfaceSmoothingIterations", 2))),
    "--surface-smoothing-strength", String(number(params, "surfaceSmoothingStrength", 0.35)),
    "--surface-connector-spacing-mm", String(number(params, "connectorSpacingMm", 5)),
    "--surface-connector-maximum-length-mm", String(number(params, "connectorMaximumLengthMm", 15)),
    "--surface-connector-diameter-mm", String(connectorDiameter),
    "--no-show",
    "--export-stl", paths.outputPath,
    "--metadata-json", paths.metadataPath,
    "--material-density-g-per-cm3", String(Math.max(0, number(params, "materialDensityGPerCm3", 0))),
    "--cache-directory", paths.cacheDirectory,
  ];
  if (input) {
    argumentsList.unshift("--input-mesh", input.path, "--source-original-name", input.originalName);
  } else {
    argumentsList.unshift("--shape", "box");
    if (isBatch) argumentsList.unshift("--source-original-name", "parametric_box.stl");
  }
  if (params.get("removeDisconnectedComponents") === "true") argumentsList.push("--remove-disconnected-components");
  if (params.get("surfaceOnly") === "true") argumentsList.push("--surface-only");
  if (params.get("connectSurfaceToInterior") === "false") argumentsList.push("--no-connect-surface-to-interior");
  if (params.get("cacheEnabled") === "false") argumentsList.push("--no-cache-enabled");
  const debugMode = choice(params, "debugMode", ["requested", "all", "none"], "none");
  const debugLayers = (params.get("debugLayers") ?? "").split(",").filter((item) => DEBUG_LAYERS.has(item));
  if (debugMode === "all" || (debugMode === "requested" && debugLayers.length)) {
    argumentsList.push(
      "--debug-mode", debugMode,
      "--debug-layers", debugLayers.join(","),
      "--debug-maximum-points", String(Math.min(1_000_000, Math.max(1, number(params, "debugMaximumPoints", 100_000)))),
      "--debug-maximum-segments", String(Math.min(1_000_000, Math.max(1, number(params, "debugMaximumSegments", 200_000)))),
      "--debug-manifest-json", paths.debugManifestPath,
      "--debug-buffer-bin", paths.debugBufferPath,
    );
  }
  if (!densityMode) return { jobType: "generate-direct", arguments: argumentsList };

  const target = number(params, "targetRelativeDensity", 0.1);
  if (!(target > 0 && target <= 1)) throw Object.assign(new Error("Cílová hustota musí být mezi 0 a 1."), { statusCode: 400 });
  argumentsList.unshift(
    "--target-relative-density", String(target),
    "--density-tolerance-percent-points", String(number(params, "densityTolerancePercentPoints", 0.5)),
    "--density-minimum-scale", String(number(params, "densityMinimumScale", 0.25)),
    "--density-maximum-scale", String(number(params, "densityMaximumScale", 3)),
    "--density-maximum-iterations", String(Math.round(number(params, "densityMaximumIterations", 12))),
    "--density-solver-quality", choice(params, "densitySolverQuality", ["preview", "standard", "final-quality"], "standard"),
    "--density-scaling-policy", choice(params, "densityScalingPolicy", ["interior-only", "all-active-radii"], "all-active-radii"),
    "--maximum-final-correction-iterations", String(Math.max(0, Math.round(number(params, "maximumFinalCorrectionIterations", 4)))),
    "--final-scale-tolerance", String(number(params, "finalScaleTolerance", 0.0005)),
    params.get("verifyAtFinalQuality") === "false" ? "--no-verify-at-final-quality" : "--verify-at-final-quality",
    "--minimum-printable-strut-diameter-mm", String(number(params, "minimumPrintableStrutDiameterMm", 0.4)),
    "--maximum-allowed-strut-diameter-mm", String(number(params, "maximumAllowedStrutDiameterMm", 20)),
    "--density-csv", paths.densityCsvPath,
  );
  if (isBatch) {
    argumentsList.unshift(
      "--density-batch-targets-percent", batchTargets,
      "--batch-failure-policy", choice(params, "batchFailurePolicy", ["continue", "stop-on-error"], "continue"),
      "--batch-output-directory", paths.batchDirectory,
      "--batch-summary-json", paths.batchSummaryJsonPath,
      "--batch-summary-csv", paths.batchSummaryCsvPath,
      "--batch-zip", paths.batchZipPath,
    );
  }
  return {
    jobType: isBatch ? "solve-density-batch" : "solve-density-single",
    arguments: argumentsList,
  };
}
