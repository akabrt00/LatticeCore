import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { STLExporter } from "three/addons/exporters/STLExporter.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import {
  buildGenerationFingerprint,
  describeJobPhase,
  formatJobElapsed,
} from "./jobPresentation.js";

const viewport = document.querySelector("#viewport");
const fileInput = document.querySelector("#stl-input");
const fileDrop = document.querySelector(".file-drop");
const sampleCubeButton = document.querySelector("#sample-cube");
const paper122Button = document.querySelector("#preset-paper-122");
const paper80Button = document.querySelector("#preset-paper-80");
const sampleCylinderButton = document.querySelector("#sample-cylinder");
const previewButton = document.querySelector("#preview");
const resetButton = document.querySelector("#reset");
const exportButton = document.querySelector("#export");
const exportMetadataButton = document.querySelector("#export-metadata");
const exportDensityCsvButton = document.querySelector("#export-density-csv");
const exportBatchZipButton = document.querySelector("#export-batch-zip");
const exportBatchSummaryCsvButton = document.querySelector("#export-batch-summary-csv");
const exportBatchSummaryJsonButton = document.querySelector("#export-batch-summary-json");
const alignBuildPlateButton = document.querySelector("#align-build-plate");
const patternSelect = document.querySelector("#pattern");
const modeButtons = [...document.querySelectorAll("[data-mode]")];

const controlsConfig = {
  boxX: document.querySelector("#box-x"),
  boxY: document.querySelector("#box-y"),
  boxZ: document.querySelector("#box-z"),
  cellSize: document.querySelector("#cell-size"),
  depth: document.querySelector("#depth"),
  wall: document.querySelector("#wall"),
  minStrut: document.querySelector("#min-strut"),
  seed: document.querySelector("#seed"),
  boundaryMode: document.querySelector("#boundary-mode"),
  removeDisconnected: document.querySelector("#remove-disconnected"),
  meshEngine: document.querySelector("#mesh-engine"),
  qualityPreset: document.querySelector("#quality-preset"),
  voxelSize: document.querySelector("#voxel-size"),
  density: document.querySelector("#density"),
  smooth: document.querySelector("#smooth"),
};

const printControlsConfig = {
  support: document.querySelector("#print-support"),
  plane: document.querySelector("#print-plane"),
  rotateX: document.querySelector("#rotate-x"),
  rotateY: document.querySelector("#rotate-y"),
  rotateZ: document.querySelector("#rotate-z"),
  overhang: document.querySelector("#overhang"),
};

const labels = {
  boxX: document.querySelector("#box-x-value"),
  boxY: document.querySelector("#box-y-value"),
  boxZ: document.querySelector("#box-z-value"),
  cellSize: document.querySelector("#cell-size-value"),
  depth: document.querySelector("#depth-value"),
  wall: document.querySelector("#wall-value"),
  minStrut: document.querySelector("#min-strut-value"),
  seed: document.querySelector("#seed-value"),
  density: document.querySelector("#density-value"),
  smooth: document.querySelector("#smooth-value"),
  triangles: document.querySelector("#triangles"),
  dimensions: document.querySelector("#dimensions"),
  exportState: document.querySelector("#export-state"),
  status: document.querySelector("#status"),
  mode: document.querySelector("#mode-label"),
  pattern: document.querySelector("#pattern-label"),
  warning: document.querySelector("#warning-text"),
  printSupport: document.querySelector("#print-support-value"),
  rotateX: document.querySelector("#rotate-x-value"),
  rotateY: document.querySelector("#rotate-y-value"),
  rotateZ: document.querySelector("#rotate-z-value"),
  overhang: document.querySelector("#overhang-value"),
  printState: document.querySelector("#print-state"),
  printIslands: document.querySelector("#print-islands"),
  printFixed: document.querySelector("#print-fixed"),
  printStruts: document.querySelector("#print-struts"),
  statVoronoiVertices: document.querySelector("#stat-voronoi-vertices"),
  statStruts: document.querySelector("#stat-struts"),
  statRemovedShort: document.querySelector("#stat-removed-short"),
  statComponents: document.querySelector("#stat-components"),
  statIsolated: document.querySelector("#stat-isolated"),
  statAverageDegree: document.querySelector("#stat-average-degree"),
  statMaximumDegree: document.querySelector("#stat-maximum-degree"),
  statTotalLength: document.querySelector("#stat-total-length"),
  statOvershoot: document.querySelector("#stat-overshoot"),
  statSurfaceSegments: document.querySelector("#stat-surface-segments"),
  statSurfaceConnectors: document.querySelector("#stat-surface-connectors"),
  statUnconnectedSurface: document.querySelector("#stat-unconnected-surface"),
  validationWatertight: document.querySelector("#validation-watertight"),
  validationManifold: document.querySelector("#validation-manifold"),
  validationBoundary: document.querySelector("#validation-boundary"),
  validationNonManifold: document.querySelector("#validation-non-manifold"),
  validationComponents: document.querySelector("#validation-components"),
  validationVolume: document.querySelector("#validation-volume"),
  validationWarning: document.querySelector("#validation-warning"),
  voxelSize: document.querySelector("#voxel-size-value"),
  implicitEngine: document.querySelector("#implicit-engine"),
  implicitVoxel: document.querySelector("#implicit-voxel"),
  implicitGrid: document.querySelector("#implicit-grid"),
  implicitVoxels: document.querySelector("#implicit-voxels"),
  implicitMemory: document.querySelector("#implicit-memory"),
  implicitTime: document.querySelector("#implicit-time"),
  implicitClipping: document.querySelector("#implicit-clipping"),
};

const meshValidationPanel = document.querySelector("#mesh-validation-panel");
const meshEngineNote = document.querySelector("#mesh-engine-note");
const importControls = document.querySelector("#import-controls");
const importScale = document.querySelector("#import-scale");
const componentMode = document.querySelector("#component-mode");
const finalComponentMode = document.querySelector("#final-component-mode");
const boundaryOffset = document.querySelector("#boundary-offset");
const seedDefinition = document.querySelector("#seed-definition");
const targetCellSize = document.querySelector("#target-cell-size");
const targetCellSizeRow = document.querySelector("#target-cell-size-row");
const maximumSamplingAttempts = document.querySelector("#maximum-sampling-attempts");
const boundaryStructureMode = document.querySelector("#boundary-structure-mode");
const conformalParameters = document.querySelector("#conformal-parameters");
const surfaceStrutDiameter = document.querySelector("#surface-strut-diameter");
const surfaceSamplingMode = document.querySelector("#surface-sampling-mode");
const surfaceSamplingStep = document.querySelector("#surface-sampling-step");
const surfaceSamplingStepRow = document.querySelector("#surface-sampling-step-row");
const surfacePlacementMode = document.querySelector("#surface-placement-mode");
const surfaceInsetMode = document.querySelector("#surface-inset-mode");
const surfaceInset = document.querySelector("#surface-inset");
const surfaceInsetRow = document.querySelector("#surface-inset-row");
const surfaceSmoothingIterations = document.querySelector("#surface-smoothing-iterations");
const surfaceSmoothingStrength = document.querySelector("#surface-smoothing-strength");
const connectSurfaceToInterior = document.querySelector("#connect-surface-to-interior");
const connectorSpacing = document.querySelector("#connector-spacing");
const connectorMaximumLength = document.querySelector("#connector-maximum-length");
const connectorDiameter = document.querySelector("#connector-diameter");
const conformalLabels = {
  strutDiameter: document.querySelector("#surface-strut-diameter-value"),
  samplingStep: document.querySelector("#surface-sampling-step-value"),
  inset: document.querySelector("#surface-inset-value"),
  smoothingIterations: document.querySelector("#surface-smoothing-iterations-value"),
  smoothingStrength: document.querySelector("#surface-smoothing-strength-value"),
  connectorSpacing: document.querySelector("#connector-spacing-value"),
  connectorMaximumLength: document.querySelector("#connector-maximum-length-value"),
  connectorDiameter: document.querySelector("#connector-diameter-value"),
};
const previewVisibility = document.querySelector("#preview-visibility");
const showOriginalMesh = document.querySelector("#show-original-mesh");
const showFinalMesh = document.querySelector("#show-final-mesh");
const debugLayerInputs = [...document.querySelectorAll("[data-debug-layer]")];
const debugPresetButtons = [...document.querySelectorAll("[data-debug-preset]")];
const cacheEnabled = document.querySelector("#cache-enabled");
const cacheClearButtons = [...document.querySelectorAll("[data-cache-clear]")];
const jobUi = {
  worker: document.querySelector("#worker-status"),
  status: document.querySelector("#job-status"),
  phase: document.querySelector("#job-phase"),
  target: document.querySelector("#job-target"),
  iteration: document.querySelector("#job-iteration"),
  density: document.querySelector("#job-density"),
  cache: document.querySelector("#job-cache"),
  memory: document.querySelector("#worker-memory"),
  time: document.querySelector("#job-time"),
  progress: document.querySelector("#job-progress"),
  progressLabel: document.querySelector("#job-progress-label"),
  progressPercent: document.querySelector("#job-progress-percent"),
  hint: document.querySelector("#job-hint"),
  messages: document.querySelector("#job-messages"),
  cancel: document.querySelector("#cancel-job"),
  clearMemory: document.querySelector("#clear-memory-cache"),
  memoryScope: document.querySelector("#memory-cache-scope"),
};
const densityControls = {
  mode: document.querySelector("#density-control-mode"),
  panel: document.querySelector("#density-solver-controls"),
  targetMode: document.querySelector("#density-target-mode"),
  singlePanel: document.querySelector("#density-single-controls"),
  batchPanel: document.querySelector("#density-batch-controls"),
  batchTargets: document.querySelector("#density-batch-targets"),
  batchValidation: document.querySelector("#density-batch-validation"),
  batchFailurePolicy: document.querySelector("#batch-failure-policy"),
  target: document.querySelector("#target-density"),
  targetLabel: document.querySelector("#target-density-value"),
  tolerance: document.querySelector("#density-tolerance"),
  minimumScale: document.querySelector("#density-min-scale"),
  maximumScale: document.querySelector("#density-max-scale"),
  maximumIterations: document.querySelector("#density-max-iterations"),
  quality: document.querySelector("#density-solver-quality"),
  verify: document.querySelector("#verify-final-density"),
  maximumFinalCorrections: document.querySelector("#maximum-final-corrections"),
  finalScaleTolerance: document.querySelector("#final-scale-tolerance"),
  policy: document.querySelector("#density-scaling-policy"),
  materialDensity: document.querySelector("#material-density"),
  minimumPrintableDiameter: document.querySelector("#minimum-printable-diameter"),
};
const importLabels = {
  boundaryOffset: document.querySelector("#boundary-offset-value"),
  name: document.querySelector("#import-file-name"),
  size: document.querySelector("#import-file-size"),
  format: document.querySelector("#import-format"),
  validation: document.querySelector("#import-validation"),
  targetCellSize: document.querySelector("#target-cell-size-value"),
};

const state = {
  mode: "volume",
  geometry: null,
  originalGeometry: null,
  mesh: null,
  volumeGroup: null,
  supportGroup: null,
  printDiagnosticGroup: null,
  previewTimer: null,
  uploadedStlBuffer: null,
  uploadedFile: null,
  generatedStlBuffer: null,
  densityCsv: null,
  batchSummary: null,
  batchResultId: null,
  batchAssets: null,
  batchZip: null,
  batchZipBytes: 0,
  debugGroup: null,
  debugResultId: null,
  debugManifest: null,
  generationId: 0,
  generationPending: false,
  loadRequestId: 0,
  printOffset: new THREE.Vector3(),
  activeJobId: null,
  activeJobStartedAt: 0,
  activeJobLastEventAt: 0,
  activeJobHint: "",
  activeJobEvents: [],
  workerQueueCount: 0,
  lastJobElapsedSeconds: 0,
  lastCompletedGenerationKey: null,
};

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
camera.up.set(0, 0, 1);
camera.position.set(85, -92, 72);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
viewport.appendChild(renderer.domElement);

const orbit = new OrbitControls(camera, renderer.domElement);
orbit.enableDamping = true;
orbit.dampingFactor = 0.06;

scene.add(new THREE.HemisphereLight(0xffffff, 0x26313a, 2.2));

const key = new THREE.DirectionalLight(0xffffff, 2.4);
key.position.set(90, 120, 80);
scene.add(key);

const fill = new THREE.DirectionalLight(0x72fff0, 0.9);
fill.position.set(-90, 40, -80);
scene.add(fill);

const grid = new THREE.GridHelper(140, 28, 0x3a4550, 0x232b33);
grid.rotation.x = Math.PI / 2;
grid.position.z = -24;
scene.add(grid);

const surfaceMaterial = new THREE.MeshStandardMaterial({
  color: 0xd9e3e8,
  metalness: 0.05,
  roughness: 0.54,
  transparent: true,
  opacity: 0.16,
  side: THREE.DoubleSide,
});

const latticeMaterial = new THREE.MeshStandardMaterial({
  color: 0x2f2923,
  metalness: 0.15,
  roughness: 0.46,
});

const supportMaterial = new THREE.MeshStandardMaterial({
  color: 0x4fd2c5,
  metalness: 0.1,
  roughness: 0.5,
});

const riskMaterial = new THREE.MeshStandardMaterial({
  color: 0xff3f55,
  metalness: 0.02,
  roughness: 0.5,
});

const anchorMaterial = new THREE.MeshStandardMaterial({
  color: 0x3d8bff,
  metalness: 0.08,
  roughness: 0.48,
});

init();

function init() {
  bindEvents();
  printControlsConfig.plane.value = "xy";
  printControlsConfig.support.checked = false;
  const initialOptions = getInitialOptions();
  state.mode = initialOptions.mode;
  syncModeButtons();
  updateLabels();
  updateConformalLabels();
  updateDensityControls();
  refreshCacheStatus();
  refreshWorkerStatus();
  window.setInterval(refreshWorkerStatus, 5000);
  window.setInterval(updateActiveJobClock, 1000);
  if (initialOptions.sample === "cylinder") {
    loadSampleCylinder({ generate: false });
  } else {
    loadSampleCube({ generate: false });
  }
  resize();
  animate();
}

function bindEvents() {
  window.addEventListener("resize", resize);

  fileInput.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) loadStlFile(file);
  });

  ["dragenter", "dragover"].forEach((name) => {
    fileDrop.addEventListener(name, (event) => {
      event.preventDefault();
      fileDrop.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((name) => {
    fileDrop.addEventListener(name, () => fileDrop.classList.remove("drag-over"));
  });

  fileDrop.addEventListener("drop", (event) => {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file && /\.(stl|obj)$/i.test(file.name)) loadStlFile(file);
  });

  importScale.addEventListener("change", () => {
    if (state.uploadedFile) loadStlFile(state.uploadedFile);
  });
  componentMode.addEventListener("change", scheduleStructurePreview);
  finalComponentMode.addEventListener("change", scheduleStructurePreview);
  boundaryOffset.addEventListener("input", () => {
    importLabels.boundaryOffset.textContent = `${Number(boundaryOffset.value).toFixed(1)} mm`;
    scheduleStructurePreview();
  });
  seedDefinition.addEventListener("change", () => {
    targetCellSizeRow.hidden = seedDefinition.value !== "cell-size";
    scheduleStructurePreview();
  });
  targetCellSize.addEventListener("input", () => {
    importLabels.targetCellSize.textContent = `${Number(targetCellSize.value).toFixed(1)} mm`;
    scheduleStructurePreview();
  });
  maximumSamplingAttempts.addEventListener("change", scheduleStructurePreview);
  const conformalInputs = [
    surfaceStrutDiameter,
    surfaceSamplingMode,
    surfaceSamplingStep,
    surfacePlacementMode,
    surfaceInsetMode,
    surfaceInset,
    surfaceSmoothingIterations,
    surfaceSmoothingStrength,
    connectSurfaceToInterior,
    connectorSpacing,
    connectorMaximumLength,
    connectorDiameter,
  ];
  boundaryStructureMode.addEventListener("change", () => {
    conformalParameters.hidden = boundaryStructureMode.value !== "conformal-surface";
    updateConformalLabels();
    scheduleStructurePreview();
  });
  conformalInputs.forEach((input) => {
    input.addEventListener("input", () => {
      updateConformalLabels();
      scheduleStructurePreview();
    });
    input.addEventListener("change", updateConformalLabels);
  });
  showOriginalMesh?.addEventListener("change", updatePreviewVisibility);
  showFinalMesh?.addEventListener("change", updatePreviewVisibility);
  debugLayerInputs.forEach((input) => input.addEventListener("change", updateDebugVisibility));
  debugPresetButtons.forEach((button) => button.addEventListener("click", () => applyDebugPreset(button.dataset.debugPreset)));
  cacheClearButtons.forEach((button) => button.addEventListener("click", () => clearCache(button.dataset.cacheClear)));
  jobUi.cancel.addEventListener("click", cancelActiveJob);
  jobUi.clearMemory.addEventListener("click", clearWorkerMemoryCache);

  sampleCubeButton.addEventListener("click", () => loadSampleCube());
  paper122Button.addEventListener("click", () => loadPaperReferencePreset(122));
  paper80Button.addEventListener("click", () => loadPaperReferencePreset(80));
  sampleCylinderButton.addEventListener("click", () => loadSampleCylinder());
  previewButton.addEventListener("click", applyStructure);
  resetButton.addEventListener("click", resetGeometry);
  exportButton.addEventListener("click", exportStl);
  exportMetadataButton.addEventListener("click", exportMetadata);
  exportDensityCsvButton.addEventListener("click", exportDensityCsv);
  exportBatchZipButton.addEventListener("click", () => exportBatchAsset("zip"));
  exportBatchSummaryCsvButton.addEventListener("click", () => exportBatchAsset("summary-csv"));
  exportBatchSummaryJsonButton.addEventListener("click", () => exportBatchAsset("summary-json"));
  Object.values(densityControls).filter((control) => control instanceof HTMLInputElement || control instanceof HTMLSelectElement).forEach((control) => {
    control.addEventListener("input", () => {
      updateDensityControls();
      if (densityControls.targetMode.value === "batch"
        || control === densityControls.mode
        || control === densityControls.targetMode) {
        window.clearTimeout(state.previewTimer);
        state.previewTimer = null;
        labels.status.textContent = densityControls.targetMode.value === "batch"
          ? "Batch parametry jsou připravené. Spusť sérii tlačítkem Přepočítat náhled."
          : "Parametry cílové hustoty jsou připravené. Spusť solver tlačítkem Přepočítat náhled.";
        return;
      }
      scheduleStructurePreview();
    });
  });

  patternSelect.addEventListener("change", () => {
    updateLabels();
    scheduleStructurePreview();
  });

  Object.values(controlsConfig).forEach((input) => {
    input.addEventListener("input", () => {
      updateLabels();
      scheduleStructurePreview();
    });
  });

  Object.values(printControlsConfig).forEach((input) => {
    input.addEventListener("input", () => {
      updateLabels();
      applyPrintTransforms();
      rebuildPrintSupports();
      applyPrintTransforms();
      updateStats();
    });
  });

  alignBuildPlateButton.addEventListener("click", () => {
    alignCurrentObjectToBuildPlate();
    updateLabels();
    rebuildPrintSupports();
    applyPrintTransforms();
    updateStats();
  });

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.mode;
      syncModeButtons();
      updateLabels();
      applyStructure();
    });
  });
}

function updateConformalLabels() {
  conformalParameters.hidden = boundaryStructureMode.value !== "conformal-surface";
  surfaceSamplingStepRow.hidden = surfaceSamplingMode.value !== "custom";
  surfaceInsetRow.hidden = surfaceInsetMode.value !== "custom";
  conformalLabels.strutDiameter.textContent = `${Number(surfaceStrutDiameter.value).toFixed(2)} mm`;
  conformalLabels.samplingStep.textContent = `${Number(surfaceSamplingStep.value).toFixed(2)} mm`;
  conformalLabels.inset.textContent = `${Number(surfaceInset.value).toFixed(2)} mm`;
  conformalLabels.smoothingIterations.textContent = surfaceSmoothingIterations.value;
  conformalLabels.smoothingStrength.textContent = Number(surfaceSmoothingStrength.value).toFixed(2);
  conformalLabels.connectorSpacing.textContent = `${Number(connectorSpacing.value).toFixed(1)} mm`;
  conformalLabels.connectorMaximumLength.textContent = `${Number(connectorMaximumLength.value).toFixed(1)} mm`;
  conformalLabels.connectorDiameter.textContent = `${Number(connectorDiameter.value).toFixed(2)} mm`;
}

function updateDensityControls() {
  densityControls.panel.hidden = densityControls.mode.value !== "target-relative-density";
  const isBatch = densityControls.targetMode.value === "batch";
  densityControls.singlePanel.hidden = isBatch;
  densityControls.batchPanel.hidden = !isBatch;
  densityControls.targetLabel.textContent = `${Number(densityControls.target.value).toFixed(1)} %`;
  validateBatchTargets();
}

function validateBatchTargets() {
  const values = densityControls.batchTargets.value
    .split(/[,;\s]+/)
    .filter(Boolean)
    .map(Number);
  const unique = new Set(values);
  const valid = values.length >= 2 && values.length <= 10
    && unique.size >= 2 && values.every((value) => Number.isFinite(value) && value > 0 && value <= 100);
  densityControls.batchValidation.textContent = valid
    ? `${unique.size} cílů · pořadí solveru bude vzestupné`
    : "Zadej 2 až 10 unikátních hodnot větších než 0 a nejvýše 100 %.";
  densityControls.batchValidation.classList.toggle("invalid", !valid);
  return valid;
}

function getInitialOptions() {
  const params = new URLSearchParams(window.location.search);
  const mode = params.get("mode") === "surface" ? "surface" : "volume";
  const sample = params.get("sample") === "cylinder" ? "cylinder" : "cube";
  return { mode, sample };
}

function syncModeButtons() {
  modeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === state.mode);
  });
}

function loadSampleCube({ generate = true } = {}) {
  state.loadRequestId += 1;
  state.uploadedStlBuffer = null;
  state.uploadedFile = null;
  state.generatedStlBuffer = null;
  importControls.hidden = true;
  if (previewVisibility) previewVisibility.hidden = true;
  const params = getLatticeParams();
  const geometry = new THREE.BoxGeometry(params.boxX, params.boxY, params.boxZ, 72, 72, 56);
  geometry.userData.latticeShape = "box";
  setGeometry(geometry, "Parametrická Voronoi kostka je připravená.", { generate });
}

function loadPaperReferencePreset(seedCount) {
  controlsConfig.boxX.value = "30";
  controlsConfig.boxY.value = "30";
  controlsConfig.boxZ.value = "24";
  controlsConfig.cellSize.value = String(seedCount);
  controlsConfig.wall.value = "1.0";
  controlsConfig.minStrut.value = "2.0";
  controlsConfig.seed.value = seedCount === 122 ? "1221" : "801";
  controlsConfig.boundaryMode.value = "exact";
  controlsConfig.removeDisconnected.checked = false;
  controlsConfig.meshEngine.value = "legacy-primitives";
  controlsConfig.qualityPreset.value = "preview";
  boundaryStructureMode.value = "conformal-surface";
  conformalParameters.hidden = false;
  state.mode = "volume";
  syncModeButtons();
  updateLabels();
  loadSampleCube();
}

function loadSampleCylinder({ generate = true } = {}) {
  state.loadRequestId += 1;
  state.uploadedStlBuffer = null;
  state.uploadedFile = null;
  state.generatedStlBuffer = null;
  importControls.hidden = true;
  if (previewVisibility) previewVisibility.hidden = true;
  const geometry = new THREE.CylinderGeometry(16, 16, 46, 72, 18, false);
  geometry.userData.latticeShape = "cylinder";
  setGeometry(geometry, "Ukázkový válec je připravený.", { generate });
}

function loadStlFile(file) {
  const loadRequestId = (state.loadRequestId += 1);
  const reader = new FileReader();
  reader.onload = () => {
    if (loadRequestId !== state.loadRequestId) return;

    try {
      const extension = file.name.split(".").pop()?.toLowerCase();
      let geometry;
      if (extension === "obj") {
        const object = new OBJLoader().parse(new TextDecoder().decode(reader.result));
        object.updateMatrixWorld(true);
        const geometries = [];
        object.traverse((item) => {
          if (!item.isMesh || !item.geometry?.attributes?.position) return;
          const childGeometry = item.geometry.clone();
          childGeometry.applyMatrix4(item.matrixWorld);
          geometries.push(childGeometry);
        });
        geometry = mergeGeometries(geometries, false);
        if (!geometry) throw new Error("OBJ neobsahuje polygonální geometrii.");
      } else {
        geometry = new STLLoader().parse(reader.result);
      }
      geometry.scale(Number(importScale.value), Number(importScale.value), Number(importScale.value));
      geometry.userData.latticeShape = "mesh";
      geometry.userData.originalFileName = file.name;
      state.uploadedStlBuffer = reader.result.slice(0);
      state.uploadedFile = file;
      state.generatedStlBuffer = null;
      state.mode = "volume";
      syncModeButtons();
      importControls.hidden = false;
      if (previewVisibility) previewVisibility.hidden = false;
      importLabels.name.textContent = file.name;
      importLabels.size.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MiB`;
      importLabels.format.textContent = extension?.toUpperCase() ?? "-";
      importLabels.validation.textContent = "Čeká na generování";
      geometry.computeVertexNormals();
      setGeometry(geometry, `Načteno: ${file.name}`);
    } catch (error) {
      console.error(error);
      labels.status.textContent = "STL/OBJ se nepodařilo načíst. Zkus jiný soubor.";
    }
  };
  reader.readAsArrayBuffer(file);
}

function setGeometry(geometry, message, { generate = true } = {}) {
  state.generationId += 1;
  state.lastCompletedGenerationKey = null;
  state.printOffset.set(0, 0, 0);
  const userData = { ...geometry.userData };
  if (geometry.index) geometry = geometry.toNonIndexed();
  geometry.userData = { ...geometry.userData, ...userData };
  geometry.computeBoundingBox();
  const sourceCenter = new THREE.Vector3();
  geometry.boundingBox.getCenter(sourceCenter);
  geometry.userData.sourceCenter = sourceCenter.toArray();
  geometry.center();
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();

  state.originalGeometry = geometry.clone();
  state.geometry = geometry.clone();

  if (state.mesh) scene.remove(state.mesh);
  disposeVolumeGroup();

  state.mesh = new THREE.Mesh(state.geometry, surfaceMaterial);
  scene.add(state.mesh);
  applyPrintTransforms();
  fitCameraToGeometry(state.geometry);
  if (generate) applyStructure();
  else updateStats();
  labels.status.textContent = message;
}

function resetGeometry() {
  if (!state.originalGeometry || !state.mesh) return;
  state.generationId += 1;
  state.lastCompletedGenerationKey = null;
  state.printOffset.set(0, 0, 0);
  state.geometry.dispose();
  state.geometry = state.originalGeometry.clone();
  state.mesh.geometry = state.geometry;
  state.mesh.visible = true;
  disposeVolumeGroup();
  applyPrintTransforms();
  updateStats();
  labels.status.textContent = "Model vrácen do původního stavu.";
}

function scheduleStructurePreview() {
  if (!state.originalGeometry) return;
  window.clearTimeout(state.previewTimer);
  state.previewTimer = null;
  labels.status.textContent = "Parametry byly změněny. Spusť výpočet tlačítkem Přepočítat náhled.";
}

async function applyStructure() {
  if (!state.originalGeometry || !state.mesh) return;
  if (state.generationPending || state.activeJobId) {
    labels.status.textContent = "Jeden výpočet už běží. Počkej na dokončení nebo jej zruš v panelu Výpočetní úloha.";
    return;
  }
  const generationKey = getGenerationRequestKey();
  if (generationKey === state.lastCompletedGenerationKey && state.volumeGroup) {
    labels.status.textContent = "Aktuální výsledek už odpovídá těmto parametrům.";
    labels.warning.textContent = "Stejný výpočet nebyl spuštěn znovu. Změň parametr nebo model, pokud chceš nový výsledek.";
    return;
  }
  state.generationPending = true;
  previewButton.disabled = true;
  const generationId = (state.generationId += 1);
  window.clearTimeout(state.previewTimer);
  state.previewTimer = null;
  labels.status.textContent = "Přepočítávám náhled...";

  state.geometry.dispose();
  state.geometry = state.originalGeometry.clone();
  labels.warning.textContent =
    state.mode === "surface"
      ? "Povrchový režim vytváří samostatnou Voronoi lattice síť nad skutečným povrchem modelu."
      : state.uploadedFile
        ? "Nahraný model používá konformní povrchovou síť spojenou s objemovou výplní uvnitř jeho skutečné obálky."
        : "Objemový režim kombinuje povrchovou Voronoi síť a vnitřní lattice výplň.";

  if (generationId !== state.generationId) {
    state.generationPending = false;
    previewButton.disabled = false;
    return;
  }
  state.geometry.computeVertexNormals();
  state.geometry.computeBoundingBox();
  try {
    if (state.mode === "surface") {
      state.mesh.visible = true;
      disposeVolumeGroup();
      const quickSurfaceGroup = createSurfaceLattice(state.originalGeometry);
      quickSurfaceGroup.name = "LatticeCore quick surface preview";
      quickSurfaceGroup.userData.isQuickPreview = true;
      quickSurfaceGroup.userData.previewKind = "surface";
      state.volumeGroup = quickSurfaceGroup;
      scene.add(state.volumeGroup);
      applyPrintTransforms();
      const useServerSurface =
        state.originalGeometry.userData?.latticeShape === "mesh" &&
        state.uploadedStlBuffer &&
        getLatticeParams().meshEngine === "implicit-union";
      if (useServerSurface) {
        labels.status.textContent = "Pracovní povrchová síť je připravená. Počítám finální konformní mesh...";
        const nextVolumeGroup = await createPythonVolumeLattice(state.originalGeometry, { surfaceOnly: true });
        if (generationId !== state.generationId) {
          disposeGroup(nextVolumeGroup);
          state.generationPending = false;
          previewButton.disabled = false;
          return;
        }
        disposeVolumeGroup();
        state.volumeGroup = nextVolumeGroup;
        scene.add(state.volumeGroup);
      }
      rebuildPrintSupports();
      applyPrintTransforms();
      labels.warning.textContent =
        "Plošný režim je nyní Voronoi-only: ze seed bodů na povrchu vzniká samostatná síť, původní STL zůstává jen jako reference.";
    } else {
      state.mesh.visible = true;
      disposeVolumeGroup();
      const quickVolumeGroup = createLegacyVolumeLattice(state.originalGeometry);
      quickVolumeGroup.name = "LatticeCore quick volume preview";
      quickVolumeGroup.userData.isQuickPreview = true;
      quickVolumeGroup.userData.previewKind = "volume";
      state.volumeGroup = quickVolumeGroup;
      scene.add(state.volumeGroup);
      applyPrintTransforms();
      if (getLatticeParams().meshEngine === "implicit-union") {
        labels.status.textContent = "Rychlý náhled je připravený. Počítám finální watertight mesh...";
        const nextVolumeGroup = await createVolumeLattice(state.originalGeometry);
        if (generationId !== state.generationId) {
          disposeGroup(nextVolumeGroup);
          state.generationPending = false;
          previewButton.disabled = false;
          return;
        }
        disposeVolumeGroup();
        state.volumeGroup = nextVolumeGroup;
        scene.add(state.volumeGroup);
        labels.warning.textContent = "Finální implicitní mesh nahradil pracovní náhled.";
      } else {
        state.generatedStlBuffer = null;
        labels.warning.textContent = state.uploadedFile
          ? "Pracovní povrchová a vnitřní síť kopíruje nahraný model a je připravená k rychlému STL exportu."
          : "Pracovní výsledek obsahuje povrchovou i vnitřní Voronoi síť a je připravený k rychlému STL exportu.";
      }
      rebuildPrintSupports();
      applyPrintTransforms();
    }
  } catch (error) {
    if (generationId !== state.generationId) return;
    console.error(error);
    const preservedQuickPreview = Boolean(state.volumeGroup?.userData.isQuickPreview);
    if (!preservedQuickPreview) disposeVolumeGroup();
    state.generatedStlBuffer = null;
    if (showOriginalMesh) showOriginalMesh.checked = true;
    state.mesh.visible = true;
    const publicError = formatGenerationError(error);
    labels.status.textContent = publicError.message;
    if (state.uploadedFile) importLabels.validation.textContent = publicError.importStatus;
    labels.warning.textContent = preservedQuickPreview
      ? "Finální výpočet se nepodařil. Pracovní lattice náhled zůstává zobrazený, ale není finálním exportním meshem."
      : "Lattice nevznikla. Původní model zůstává zobrazený beze změny.";
    updatePreviewVisibility();
    updateStats();
    state.generationPending = false;
    previewButton.disabled = false;
    return;
  }

  state.geometry.computeVertexNormals();
  state.geometry.computeBoundingBox();
  state.mesh.geometry = state.geometry;
  updateStats();
  state.lastCompletedGenerationKey = generationKey;
  labels.warning.textContent = state.volumeGroup?.userData.isQuickPreview
    ? state.volumeGroup.userData.previewKind === "surface"
      ? "Pracovní povrchová Voronoi síť je hotová. Pro finální watertight STL použij implicitní výpočet."
      : state.uploadedFile
        ? "Povrchová a vnitřní síť kopíruje nahraný model. Rychlý STL export je připravený."
        : "Výsledek obsahuje povrchovou i vnitřní Voronoi síť. Rychlý STL export je připravený."
    : formatOptimizationSummary(state.volumeGroup?.userData.optimization);
  if (state.uploadedFile && state.volumeGroup?.userData.isQuickPreview) {
    importLabels.validation.textContent = "Pracovní náhled hotový";
  }
  labels.status.textContent = "Náhled přepočítán.";
  updatePreviewVisibility();
  state.generationPending = false;
  previewButton.disabled = false;
}

function formatGenerationError(error) {
  const message = error instanceof Error ? error.message : "Generování selhalo.";
  const componentMatch = message.match(/has (\d+) components; require-single accepts exactly one/i);
  if (componentMatch) {
    const count = Number(componentMatch[1]);
    return {
      message: `Model obsahuje ${count} oddělených komponent. Zvol „Použít všechny uzavřené“ nebo „Ponechat největší“ a přepočítej náhled.`,
      importStatus: `${count} oddělených komponent`,
    };
  }
  if (/Every component must be closed and edge-manifold/i.test(message)) {
    return {
      message: "Některá komponenta modelu není uzavřená nebo manifold. Zkus „Ponechat největší“, případně oprav vstupní STL.",
      importStatus: "Neuzavřená komponenta",
    };
  }
  if (/imported model is open/i.test(message)) {
    return {
      message: "Nahraný model není uzavřený, takže nemá jednoznačný vnitřní objem. Oprav mesh a nahraj jej znovu.",
      importStatus: "Otevřený mesh",
    };
  }
  if (/non-manifold/i.test(message)) {
    return {
      message: "Nahraný model obsahuje non-manifold hrany. Před generováním je potřeba mesh opravit.",
      importStatus: "Non-manifold mesh",
    };
  }
  return { message, importStatus: "Generování selhalo" };
}

function updatePreviewVisibility() {
  if (state.mesh) state.mesh.visible = !state.uploadedFile || Boolean(showOriginalMesh?.checked);
  if (state.volumeGroup) state.volumeGroup.visible = !state.uploadedFile || Boolean(showFinalMesh?.checked);
}

function formatOptimizationSummary(stats = {}) {
  if (stats.pythonGenerator) {
    return "Pouzit Python STL generator: stejny pipeline jako testovany export.";
  }

  const removedNodes = stats.removedNodes ?? 0;
  const removedEdges = stats.removedEdges ?? 0;
  const surfaceRemovedNodes = stats.surfaceRemovedNodes ?? 0;
  const surfaceRemovedEdges = stats.surfaceRemovedEdges ?? 0;
  const totalRemovedNodes = removedNodes + surfaceRemovedNodes;
  const totalRemovedEdges = removedEdges + surfaceRemovedEdges;
  return `Optimalizace: slouceno ${totalRemovedNodes} blizkych uzlu, odstraneno ${totalRemovedEdges} kratkych prutu.`;
}

function createSurfaceLattice(sourceGeometry) {
  const group = new THREE.Group();
  group.name = "LatticeCore surface lattice";

  const bbox = sourceGeometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(sourceGeometry.attributes.position);
  const params = getLatticeParams();
  const radius = getLatticeRadius(bbox);
  const surfaceInset = Math.max(params.surfaceOffset, radius * 1.15);
  const rawSamples = sampleSurfacePoints(sourceGeometry, getSurfaceLatticeCount(), -surfaceInset);
  const samples = mergeCloseSamples(rawSamples, getNodeMergeDistance(bbox, radius));
  if (sourceGeometry.userData?.latticeShape === "box") {
    const safeMin = bbox.min.clone().addScalar(radius * 1.16);
    const safeMax = bbox.max.clone().addScalar(-radius * 1.16);
    samples.forEach((sample) => sample.position.clamp(safeMin, safeMax));
  }
  const rawEdges = createSurfaceEdges(samples, bbox);
  const edges = filterIndexedEdgesByLength(rawEdges, samples.map((sample) => sample.position), getMinimumStrutLength(bbox, radius));
  const nodes = samples.map((sample) => sample.position.clone());
  const finalEdges = edges.map(([aIndex, bIndex]) => [aIndex, bIndex]);

  if (sourceGeometry.userData?.latticeShape === "box") {
    const frameInset = radius * 1.15;
    const min = bbox.min.clone().addScalar(frameInset);
    const max = bbox.max.clone().addScalar(-frameInset);
    const frameOffset = nodes.length;
    nodes.push(
      new THREE.Vector3(min.x, min.y, min.z), new THREE.Vector3(max.x, min.y, min.z),
      new THREE.Vector3(max.x, max.y, min.z), new THREE.Vector3(min.x, max.y, min.z),
      new THREE.Vector3(min.x, min.y, max.z), new THREE.Vector3(max.x, min.y, max.z),
      new THREE.Vector3(max.x, max.y, max.z), new THREE.Vector3(min.x, max.y, max.z),
    );
    for (const [aIndex, bIndex] of [
      [0, 1], [1, 2], [2, 3], [3, 0],
      [4, 5], [5, 6], [6, 7], [7, 4],
      [0, 4], [1, 5], [2, 6], [3, 7],
    ]) finalEdges.push([frameOffset + aIndex, frameOffset + bIndex]);
  }
  group.userData.optimization = {
    rawNodes: rawSamples.length,
    nodes: samples.length,
    removedNodes: rawSamples.length - samples.length,
    rawEdges: rawEdges.length,
    edges: finalEdges.length,
    removedEdges: rawEdges.length - edges.length,
  };
  group.userData.latticeNodes = nodes;
  group.userData.latticeEdges = finalEdges;

  for (const [aIndex, bIndex] of finalEdges) {
    addTube(group, nodes[aIndex], nodes[bIndex], radius);
  }

  const nodeGeometry = new THREE.SphereGeometry(radius * 1.1, 10, 8);
  for (const point of nodes) {
    const node = new THREE.Mesh(nodeGeometry, latticeMaterial);
    node.position.copy(point);
    group.add(node);
  }

  return group;
}

function getLatticeRadius(bbox) {
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  const params = getLatticeParams();
  return Math.max(maxAxis * 0.0045, params.strutDiameter * 0.5);
}

function getLatticeParams() {
  return {
    boxX: Number(controlsConfig.boxX.value),
    boxY: Number(controlsConfig.boxY.value),
    boxZ: Number(controlsConfig.boxZ.value),
    cellCount: Number(controlsConfig.cellSize.value),
    surfaceOffset: Number(controlsConfig.depth.value),
    strutDiameter: Number(controlsConfig.wall.value),
    minStrutLength: Number(controlsConfig.minStrut.value),
    randomSeed: Number(controlsConfig.seed.value),
    boundaryMode: controlsConfig.boundaryMode.value,
    removeDisconnectedComponents: controlsConfig.removeDisconnected.checked,
    meshEngine: controlsConfig.meshEngine.value,
    qualityPreset: controlsConfig.qualityPreset.value,
    voxelSizeMm: Number(controlsConfig.voxelSize.value),
    edgeReach: Number(controlsConfig.density.value),
    randomness: Number(controlsConfig.smooth.value),
  };
}

function getGenerationRequestKey() {
  const ignoredControlIds = new Set([
    "show-original-mesh",
    "show-final-mesh",
    "memory-cache-scope",
    "stl-input",
  ]);
  const controls = Object.fromEntries(
    [...document.querySelectorAll("input[id], select[id]")]
      .filter((element) => !ignoredControlIds.has(element.id))
      .sort((left, right) => left.id.localeCompare(right.id))
      .map((element) => [
        element.id,
        element.type === "checkbox" ? element.checked : element.value,
      ]),
  );
  const model = state.uploadedFile
    ? {
        kind: "upload",
        name: state.uploadedFile.name,
        size: state.uploadedFile.size,
        lastModified: state.uploadedFile.lastModified,
      }
    : {
        kind: state.originalGeometry?.userData?.latticeShape ?? "unknown",
        vertices: state.originalGeometry?.attributes?.position?.count ?? 0,
      };
  return buildGenerationFingerprint({ controls, mode: state.mode, model });
}

function getSurfaceLatticeCount() {
  return getLatticeParams().cellCount;
}

function sampleSurfacePoints(geometry, count, offset) {
  const positions = geometry.attributes.position;
  const random = mulberry32(5003 + getSeedSalt());
  const triangles = [];
  let totalArea = 0;
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  const ab = new THREE.Vector3();
  const ac = new THREE.Vector3();
  const normal = new THREE.Vector3();

  for (let index = 0; index < positions.count; index += 3) {
    a.fromBufferAttribute(positions, index);
    b.fromBufferAttribute(positions, index + 1);
    c.fromBufferAttribute(positions, index + 2);
    ab.subVectors(b, a);
    ac.subVectors(c, a);
    const area = ab.cross(ac).length() * 0.5;
    if (area <= 0) continue;
    totalArea += area;
    triangles.push({ index, cumulative: totalArea });
  }

  const samples = [];
  for (let sampleIndex = 0; sampleIndex < count && triangles.length > 0; sampleIndex += 1) {
    const pick = random() * totalArea;
    const triangle = triangles.find((item) => item.cumulative >= pick) ?? triangles[triangles.length - 1];
    a.fromBufferAttribute(positions, triangle.index);
    b.fromBufferAttribute(positions, triangle.index + 1);
    c.fromBufferAttribute(positions, triangle.index + 2);

    let u = random();
    let v = random();
    if (u + v > 1) {
      u = 1 - u;
      v = 1 - v;
    }

    const point = a
      .clone()
      .add(new THREE.Vector3().subVectors(b, a).multiplyScalar(u))
      .add(new THREE.Vector3().subVectors(c, a).multiplyScalar(v));
    normal.crossVectors(new THREE.Vector3().subVectors(b, a), new THREE.Vector3().subVectors(c, a)).normalize();
    point.add(normal.clone().multiplyScalar(offset));
    samples.push({ position: point, normal: normal.clone() });
  }

  return samples;
}

function createSurfaceEdges(samples, bbox) {
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  const params = getLatticeParams();
  const neighborCount = Math.round(params.edgeReach);
  const averageSpacing = 1 / Math.sqrt(Math.max(samples.length, 1));
  const maxDistance = maxAxis * THREE.MathUtils.clamp(averageSpacing * params.edgeReach * 1.55, 0.16, 0.54);
  return createNearestEdgesFromSamples(samples, neighborCount, maxDistance);
}

async function createVolumeLattice(sourceGeometry) {
  const canUsePythonGenerator =
    sourceGeometry.userData?.latticeShape === "box" ||
    (sourceGeometry.userData?.latticeShape === "mesh" && state.uploadedStlBuffer);

  if (canUsePythonGenerator) {
    try {
      return await createPythonVolumeLattice(sourceGeometry);
    } catch (error) {
      console.error(error);
      if (state.uploadedFile) throw error;
      labels.warning.textContent = "Python generator selhal, zobrazuji starsi JS nahled.";
    }
  }

  return createLegacyVolumeLattice(sourceGeometry);
}

function createLegacyVolumeLattice(sourceGeometry) {
  const group = new THREE.Group();
  group.name = "LatticeCore volume lattice";

  const bbox = sourceGeometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(sourceGeometry.attributes.position);
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  const params = getLatticeParams();
  const radius = getLatticeRadius(bbox);
  const surfaceGroup = createSurfaceLattice(sourceGeometry);
  group.add(surfaceGroup);

  const rawPoints = createInteriorPoints(sourceGeometry, bbox);
  const points = mergeClosePoints(rawPoints, getNodeMergeDistance(bbox, radius));
  const rawEdges = createNearestEdges(points, maxAxis, params.edgeReach, sourceGeometry);
  const edges = filterIndexedEdgesByLength(rawEdges, points, getMinimumStrutLength(bbox, radius));
  const surfaceOptimization = surfaceGroup.userData.optimization ?? {};
  const surfaceNodes = surfaceGroup.userData.latticeNodes ?? [];
  const surfaceEdges = surfaceGroup.userData.latticeEdges ?? [];
  const connectorEdges = createSurfaceInteriorConnectors(surfaceNodes, points, sourceGeometry, maxAxis, params.cellCount);
  const latticeNodes = [...surfaceNodes.map((point) => point.clone()), ...points.map((point) => point.clone())];
  const surfaceNodeOffset = 0;
  const innerNodeOffset = surfaceNodes.length;
  group.userData.optimization = {
    rawNodes: rawPoints.length,
    nodes: points.length,
    removedNodes: rawPoints.length - points.length,
    rawEdges: rawEdges.length,
    edges: edges.length,
    removedEdges: rawEdges.length - edges.length,
    surfaceRemovedNodes: surfaceOptimization.removedNodes ?? 0,
    surfaceRemovedEdges: surfaceOptimization.removedEdges ?? 0,
  };
  group.userData.latticeNodes = latticeNodes;
  group.userData.latticeEdges = [
    ...surfaceEdges.map(([aIndex, bIndex]) => [aIndex + surfaceNodeOffset, bIndex + surfaceNodeOffset]),
    ...edges.map(([aIndex, bIndex]) => [aIndex + innerNodeOffset, bIndex + innerNodeOffset]),
    ...connectorEdges.map(([surfaceIndex, innerIndex]) => [surfaceIndex, innerIndex + innerNodeOffset]),
  ];

  for (const [aIndex, bIndex] of edges) {
    addTube(group, points[aIndex], points[bIndex], radius);
  }
  for (const [surfaceIndex, innerIndex] of connectorEdges) {
    addTube(group, surfaceNodes[surfaceIndex], points[innerIndex], radius * 0.92);
  }

  const nodeGeometry = new THREE.SphereGeometry(radius * 1.16, 10, 8);
  for (const point of points) {
    const node = new THREE.Mesh(nodeGeometry, latticeMaterial);
    node.position.copy(point);
    group.add(node);
  }

  return group;
}

function createSurfaceInteriorConnectors(surfaceNodes, innerNodes, sourceGeometry, maxAxis, cellCount) {
  if (surfaceNodes.length === 0 || innerNodes.length === 0) return [];
  const insideTester = createInsideTester(sourceGeometry);
  const desiredCount = THREE.MathUtils.clamp(Math.round(cellCount * 0.3), 8, 42);
  const stride = Math.max(1, Math.floor(surfaceNodes.length / desiredCount));
  const maximumLength = maxAxis * 0.34;
  const connectors = [];

  for (let surfaceIndex = 0; surfaceIndex < surfaceNodes.length; surfaceIndex += stride) {
    const candidates = innerNodes
      .map((point, innerIndex) => ({ innerIndex, distance: point.distanceTo(surfaceNodes[surfaceIndex]) }))
      .filter((candidate) => candidate.distance <= maximumLength)
      .sort((left, right) => left.distance - right.distance)
      .slice(0, 8);
    const accepted = candidates.find((candidate) =>
      isSegmentInside(surfaceNodes[surfaceIndex], innerNodes[candidate.innerIndex], insideTester)
    );
    if (accepted) connectors.push([surfaceIndex, accepted.innerIndex]);
    if (connectors.length >= desiredCount) break;
  }

  return connectors;
}

function isSegmentInside(start, end, insideTester) {
  const probe = new THREE.Vector3();
  for (const ratio of [0.2, 0.4, 0.6, 0.8]) {
    probe.copy(start).lerp(end, ratio);
    if (!insideTester(probe)) return false;
  }
  return true;
}

async function createPythonVolumeLattice(sourceGeometry, options = {}) {
  const bbox = sourceGeometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(sourceGeometry.attributes.position);
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  const params = getLatticeParams();
  const radius = maxAxis * 0.5;
  const query = new URLSearchParams({
    points: String(Math.round(params.cellCount)),
    radius: String(radius),
    boxSizeX: String(params.boxX),
    boxSizeY: String(params.boxY),
    boxSizeZ: String(params.boxZ),
    tubeRadius: String(Math.max(params.strutDiameter * 0.5, maxAxis * 0.0045)),
    minStrutLengthMm: String(params.minStrutLength),
    seed: String(Math.round(params.randomSeed)),
    boundaryMode: params.boundaryMode,
    removeDisconnectedComponents: String(params.removeDisconnectedComponents),
    meshEngine: params.meshEngine,
    qualityPreset: params.qualityPreset,
    voxelSizeMm: String(params.voxelSizeMm),
    importScale: importScale.value,
    componentMode: componentMode.value,
    finalComponentMode: finalComponentMode.value,
    boundaryOffsetMm: boundaryOffset.value,
    targetCellSizeMm: seedDefinition.value === "cell-size" ? targetCellSize.value : "0",
    maximumSamplingAttempts: maximumSamplingAttempts.value,
    boundaryStructureMode: boundaryStructureMode.value,
    surfaceSamplingMode: surfaceSamplingMode.value,
    surfaceSamplingStepMm: surfaceSamplingStep.value,
    surfaceStrutDiameterMm: surfaceStrutDiameter.value,
    surfacePlacementMode: surfacePlacementMode.value,
    surfaceInsetMode: surfaceInsetMode.value,
    surfaceInsetMm: surfaceInset.value,
    surfaceSmoothingIterations: surfaceSmoothingIterations.value,
    surfaceSmoothingStrength: surfaceSmoothingStrength.value,
    connectSurfaceToInterior: String(connectSurfaceToInterior.checked),
    connectorSpacingMm: connectorSpacing.value,
    connectorMaximumLengthMm: connectorMaximumLength.value,
    connectorDiameterMm: connectorDiameter.value,
  });
  if (options.surfaceOnly) query.set("surfaceOnly", "true");
  const requestedDebugLayers = debugLayerInputs.filter((input) => input.checked && !input.disabled).map((input) => input.dataset.debugLayer);
  query.set("debugMode", requestedDebugLayers.length ? "requested" : "none");
  query.set("debugLayers", requestedDebugLayers.join(","));
  query.set("debugMaximumPoints", "100000");
  query.set("debugMaximumSegments", "200000");
  query.set("cacheEnabled", String(cacheEnabled?.checked ?? true));
  query.set("densityControlMode", densityControls.mode.value);
  query.set("targetRelativeDensity", String(Number(densityControls.target.value) / 100));
  query.set("densityTolerancePercentPoints", densityControls.tolerance.value);
  query.set("densityMinimumScale", densityControls.minimumScale.value);
  query.set("densityMaximumScale", densityControls.maximumScale.value);
  query.set("densityMaximumIterations", densityControls.maximumIterations.value);
  query.set("densitySolverQuality", densityControls.quality.value);
  query.set("densityScalingPolicy", densityControls.policy.value);
  query.set("verifyAtFinalQuality", String(densityControls.verify.checked));
  query.set("maximumFinalCorrectionIterations", densityControls.maximumFinalCorrections.value);
  query.set("finalScaleTolerance", densityControls.finalScaleTolerance.value);
  query.set("materialDensityGPerCm3", densityControls.materialDensity.value || "0");
  query.set("minimumPrintableStrutDiameterMm", densityControls.minimumPrintableDiameter.value);
  const isDensityBatch = densityControls.mode.value === "target-relative-density"
    && densityControls.targetMode.value === "batch";
  if (isDensityBatch) {
    if (!validateBatchTargets()) throw new Error("Neplatný seznam cílových hustot.");
    query.set("densityBatchTargetsPercent", densityControls.batchTargets.value);
    query.set("batchFailurePolicy", densityControls.batchFailurePolicy.value);
  }

  const hasUploadedMesh = sourceGeometry.userData?.latticeShape === "mesh" && state.uploadedStlBuffer;
  labels.status.textContent = hasUploadedMesh
    ? options.surfaceOnly
      ? "Python generuje povrchovou sit podle nahraneho STL..."
      : "Python generuje lattice podle nahraneho STL..."
    : "Python generuje Voronoi STL...";
  const uploadBody = hasUploadedMesh ? new FormData() : undefined;
  if (uploadBody) uploadBody.append("file", state.uploadedFile, state.uploadedFile.name);
  const job = await createAndWaitForJob(query, uploadBody);
  const debugResultId = null;
  state.densityCsv = null;
  exportDensityCsvButton.disabled = true;
  let metadata = null;
  let buffer = null;
  if (job.result?.mode === "batch") {
    state.batchSummary = job.result.summary;
    state.batchResultId = job.jobId;
    state.batchAssets = job.result.assets;
    const zipResponse = await fetch(job.result.zipUrl, { cache: "no-store" });
    state.batchZip = await zipResponse.arrayBuffer();
    state.batchZipBytes = state.batchZip.byteLength;
    renderBatchResults(state.batchSummary);
    const firstResult = state.batchSummary.results.find((item) => item.stlFileName);
    if (!firstResult) throw new Error("Batch nedokončil žádný exportovatelný cíl.");
    const [stlResponse, metadataResponse] = await Promise.all([
      fetch(state.batchAssets[firstResult.stlFileName], { cache: "no-store" }),
      fetch(state.batchAssets[firstResult.metadataFileName], { cache: "no-store" }),
    ]);
    if (!stlResponse.ok || !metadataResponse.ok) throw new Error("Náhled batch výsledku již není dostupný.");
    buffer = await stlResponse.arrayBuffer();
    metadata = await metadataResponse.json();
    labels.status.textContent = `Série dokončena: ${state.batchSummary.results.length} cílů.`;
  } else {
    state.batchSummary = null;
    state.batchResultId = null;
    state.batchZip = null;
    state.batchZipBytes = 0;
    state.batchAssets = null;
    renderBatchResults(null);
    metadata = job.result?.metadata ?? null;
    const stlResponse = await fetch(job.result?.stlUrl, { cache: "no-store" });
    if (!stlResponse.ok) throw new Error("Výsledné STL již není dostupné.");
    buffer = await stlResponse.arrayBuffer();
  }
  state.generatedStlBuffer = buffer.slice(0);
  const geometry = new STLLoader().parse(buffer);
  if (metadata?.inputMeshValidation?.bounds) {
    const { min, max } = metadata.inputMeshValidation.bounds;
    geometry.translate(
      -(min[0] + max[0]) * 0.5,
      -(min[1] + max[1]) * 0.5,
      -(min[2] + max[2]) * 0.5,
    );
  } else {
    geometry.center();
  }
  geometry.computeVertexNormals();

  const mesh = new THREE.Mesh(geometry, latticeMaterial);
  const group = new THREE.Group();
  group.name = options.surfaceOnly ? "LatticeCore Python surface lattice" : "LatticeCore Python volume lattice";
  group.add(mesh);
  group.userData.optimization = {
    pythonGenerator: true,
    removedNodes: 0,
    removedEdges: 0,
  };
  group.userData.metadata = metadata;
  if (debugResultId) {
    state.debugResultId = debugResultId;
    await loadDebugGeometry(debugResultId, geometry.boundingBox, metadata);
  } else {
    disposeDebugGroup();
  }
  if (metadata?.inputMeshValidation) {
    const validation = metadata.inputMeshValidation;
    importLabels.validation.textContent = validation.isWatertight && validation.isEdgeManifold
      ? `Platný objem · ${validation.triangleCount.toLocaleString("cs-CZ")} trojúhelníků`
      : `${validation.boundaryEdgeCount} otevřených hran`;
  }
  return group;
}

function getNodeMergeDistance(bbox, radius) {
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  return Math.max(radius * 3.15, maxAxis * 0.018);
}

function getMinimumStrutLength(bbox, radius) {
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  return Math.max(radius * 3.6, maxAxis * 0.024);
}

function mergeCloseSamples(samples, mergeDistance) {
  const points = samples.map((sample) => sample.position);
  const clusters = createPointClusters(points, mergeDistance);
  return clusters.map((cluster) => {
    const position = averageVectors(cluster.indices.map((index) => samples[index].position));
    const normal = averageVectors(cluster.indices.map((index) => samples[index].normal)).normalize();
    return { position, normal };
  });
}

function mergeClosePoints(points, mergeDistance) {
  return createPointClusters(points, mergeDistance).map((cluster) =>
    averageVectors(cluster.indices.map((index) => points[index]))
  );
}

function createPointClusters(points, mergeDistance) {
  const clusters = [];
  const mergeDistanceSq = mergeDistance * mergeDistance;

  for (let pointIndex = 0; pointIndex < points.length; pointIndex += 1) {
    const point = points[pointIndex];
    let bestCluster = null;
    let bestDistanceSq = Infinity;

    for (const cluster of clusters) {
      const distanceSq = cluster.center.distanceToSquared(point);
      if (distanceSq < mergeDistanceSq && distanceSq < bestDistanceSq) {
        bestCluster = cluster;
        bestDistanceSq = distanceSq;
      }
    }

    if (!bestCluster) {
      clusters.push({ center: point.clone(), indices: [pointIndex] });
      continue;
    }

    bestCluster.indices.push(pointIndex);
    bestCluster.center.copy(averageVectors(bestCluster.indices.map((index) => points[index])));
  }

  return clusters;
}

function averageVectors(vectors) {
  const result = new THREE.Vector3();
  for (const vector of vectors) result.add(vector);
  if (vectors.length > 0) result.multiplyScalar(1 / vectors.length);
  return result;
}

function filterIndexedEdgesByLength(edges, points, minLength) {
  return edges.filter(([aIndex, bIndex]) => points[aIndex].distanceTo(points[bIndex]) >= minLength);
}

function createInteriorPoints(sourceGeometry, bbox) {
  const points = [];
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  bbox.getSize(size);
  bbox.getCenter(center);

  const params = getLatticeParams();
  const targetCount = THREE.MathUtils.clamp(Math.round(params.cellCount * 0.72), 12, 140);
  const random = mulberry32(8101 + Math.round(params.cellCount * 13 + params.edgeReach * 97 + params.randomness * 1000));
  const clearance = getLatticeRadius(bbox) * 1.2;
  const sampleBounds = bbox.clone().expandByScalar(-clearance);
  if (sampleBounds.isEmpty()) sampleBounds.copy(bbox);
  const insideTester = createInsideTester(sourceGeometry, clearance);

  let attempts = 0;
  const maxAttempts = targetCount * 18;
  while (points.length < targetCount && attempts < maxAttempts) {
    attempts += 1;
    const point = new THREE.Vector3(
      THREE.MathUtils.lerp(sampleBounds.min.x, sampleBounds.max.x, random()),
      THREE.MathUtils.lerp(sampleBounds.min.y, sampleBounds.max.y, random()),
      THREE.MathUtils.lerp(sampleBounds.min.z, sampleBounds.max.z, random())
    );
    if (insideTester(point)) points.push(point);
  }

  if (points.length < 6) {
    points.push(center.clone());
  }

  return points;
}

function createInsideTester(sourceGeometry, clearance = 0) {
  const bbox = (sourceGeometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(sourceGeometry.attributes.position)).clone();
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  bbox.getSize(size);
  bbox.getCenter(center);
  const safeBounds = bbox.clone().expandByScalar(-Math.max(0, clearance));
  const boundsTester = (point) => !safeBounds.isEmpty() && safeBounds.containsPoint(point);
  const shape = sourceGeometry.userData?.latticeShape;

  if (shape === "box") {
    return boundsTester;
  }

  const axes = [
    { name: "x", size: size.x },
    { name: "y", size: size.y },
    { name: "z", size: size.z },
  ].sort((left, right) => right.size - left.size);

  const longest = axes[0];
  const mid = axes[1];
  const shortest = axes[2];

  if (shape === "cylinder") {
    const axialLimit = Math.max(longest.size * 0.5 - clearance, 0);
    const radialASize = Math.max(mid.size * 0.5 - clearance, 1e-6);
    const radialBSize = Math.max(shortest.size * 0.5 - clearance, 1e-6);
    return (point) => {
      const local = point.clone().sub(center);
      const axial = Math.abs(local[longest.name]);
      const radialA = local[mid.name] / radialASize;
      const radialB = local[shortest.name] / radialBSize;
      return axial <= axialLimit && radialA * radialA + radialB * radialB <= 1;
    };
  }

  // Imported STL meshes use an indexed +X ray test. Binning triangle projections
  // in YZ keeps interactive previews fast even for meshes with many triangles.
  const positions = sourceGeometry.attributes.position;
  const triangleCount = Math.floor(positions.count / 3);
  const gridSize = THREE.MathUtils.clamp(Math.round(Math.sqrt(triangleCount / 8)), 12, 64);
  const spanY = Math.max(size.y, 1e-6);
  const spanZ = Math.max(size.z, 1e-6);
  const bins = Array.from({ length: gridSize * gridSize }, () => []);
  const triangles = [];
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  const cellIndex = (y, z) => {
    const iy = THREE.MathUtils.clamp(Math.floor(((y - bbox.min.y) / spanY) * gridSize), 0, gridSize - 1);
    const iz = THREE.MathUtils.clamp(Math.floor(((z - bbox.min.z) / spanZ) * gridSize), 0, gridSize - 1);
    return [iy, iz];
  };

  for (let triangleIndex = 0; triangleIndex < triangleCount; triangleIndex += 1) {
    a.fromBufferAttribute(positions, triangleIndex * 3);
    b.fromBufferAttribute(positions, triangleIndex * 3 + 1);
    c.fromBufferAttribute(positions, triangleIndex * 3 + 2);
    const triangle = {
      ax: a.x, ay: a.y, az: a.z,
      bx: b.x, by: b.y, bz: b.z,
      cx: c.x, cy: c.y, cz: c.z,
    };
    const storedIndex = triangles.push(triangle) - 1;
    const [minY, minZ] = cellIndex(Math.min(a.y, b.y, c.y), Math.min(a.z, b.z, c.z));
    const [maxY, maxZ] = cellIndex(Math.max(a.y, b.y, c.y), Math.max(a.z, b.z, c.z));
    for (let iy = minY; iy <= maxY; iy += 1) {
      for (let iz = minZ; iz <= maxZ; iz += 1) bins[iz * gridSize + iy].push(storedIndex);
    }
  }

  const epsilon = Math.max(longest.size * 1e-7, 1e-6);

  return (point) => {
    if (!boundsTester(point)) return false;
    const rayY = point.y + epsilon * 3.1;
    const rayZ = point.z + epsilon * 5.7;
    const [iy, iz] = cellIndex(rayY, rayZ);
    const hitPositions = [];
    for (const triangleIndex of bins[iz * gridSize + iy]) {
      const triangle = triangles[triangleIndex];
      const denominator = (triangle.bz - triangle.cz) * (triangle.ay - triangle.cy)
        + (triangle.cy - triangle.by) * (triangle.az - triangle.cz);
      if (Math.abs(denominator) <= epsilon) continue;
      const u = ((triangle.bz - triangle.cz) * (rayY - triangle.cy)
        + (triangle.cy - triangle.by) * (rayZ - triangle.cz)) / denominator;
      const v = ((triangle.cz - triangle.az) * (rayY - triangle.cy)
        + (triangle.ay - triangle.cy) * (rayZ - triangle.cz)) / denominator;
      const w = 1 - u - v;
      if (u < -epsilon || v < -epsilon || w < -epsilon) continue;
      const hitX = u * triangle.ax + v * triangle.bx + w * triangle.cx;
      if (hitX > point.x + epsilon) hitPositions.push(hitX);
    }
    hitPositions.sort((left, right) => left - right);
    let uniqueHits = 0;
    let previousHit = -Infinity;
    for (const hit of hitPositions) {
      if (Math.abs(hit - previousHit) <= epsilon * 20) continue;
      uniqueHits += 1;
      previousHit = hit;
    }
    return uniqueHits % 2 === 1;
  };
}

function createNearestEdgesFromPositions(points, neighborCount, maxDistance, insideTester = null) {
  const edges = [];
  const edgeKeys = new Set();
  const midpoint = new THREE.Vector3();

  for (let a = 0; a < points.length; a += 1) {
    const nearest = points
      .map((point, index) => ({ index, distance: point.distanceTo(points[a]) }))
      .filter((item) => item.index !== a && item.distance <= maxDistance)
      .sort((left, right) => left.distance - right.distance)
      .slice(0, neighborCount);

    for (const item of nearest) {
      if (insideTester) {
        let segmentInside = true;
        for (const ratio of [0.25, 0.5, 0.75]) {
          midpoint.copy(points[a]).lerp(points[item.index], ratio);
          if (!insideTester(midpoint)) {
            segmentInside = false;
            break;
          }
        }
        if (!segmentInside) continue;
      }

      const low = Math.min(a, item.index);
      const high = Math.max(a, item.index);
      const key = `${low}:${high}`;
      if (!edgeKeys.has(key)) {
        edgeKeys.add(key);
        edges.push([low, high]);
      }
    }
  }

  return edges;
}

function createNearestEdgesFromSamples(samples, neighborCount, maxDistance) {
  const edges = [];
  const edgeKeys = new Set();

  for (let a = 0; a < samples.length; a += 1) {
    const nearest = samples
      .map((sample, index) => ({
        index,
        distance: sample.position.distanceTo(samples[a].position),
        normalDot: sample.normal.dot(samples[a].normal),
      }))
      .filter((item) => item.index !== a && item.distance <= maxDistance && item.normalDot > -0.12)
      .sort((left, right) => left.distance - right.distance)
      .slice(0, neighborCount);

    for (const item of nearest) {
      const low = Math.min(a, item.index);
      const high = Math.max(a, item.index);
      const key = `${low}:${high}`;
      if (!edgeKeys.has(key)) {
        edgeKeys.add(key);
        edges.push([low, high]);
      }
    }
  }

  return edges;
}

function createVolumePoints(bbox, density, cellSize, smooth) {
  const points = [];
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  bbox.getSize(size);
  bbox.getCenter(center);

  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  const random = mulberry32(9001 + Math.round(density * 13 + cellSize * 29 + smooth * 101));
  const cellFactor = THREE.MathUtils.clamp((42 - cellSize) / 36, 0, 1);
  const pointCount = THREE.MathUtils.clamp(Math.round(30 + density * 1.25 + cellFactor * 70), 30, 190);
  const fill = THREE.MathUtils.lerp(0.72, 0.98, Number(controlsConfig.depth.value) / 4);

  for (let index = 0; index < pointCount; index += 1) {
    const jitter = 0.08 + smooth * 0.18;
    points.push(
      new THREE.Vector3(
        center.x + (random() - 0.5 + (random() - 0.5) * jitter) * size.x * fill,
        center.y + (random() - 0.5 + (random() - 0.5) * jitter) * size.y * fill,
        center.z + (random() - 0.5 + (random() - 0.5) * jitter) * size.z * fill
      )
    );
  }

  const faceSteps = Math.max(4, Math.min(9, Math.round(maxAxis / cellSize) + 4));
  for (let face = 0; face < 6; face += 1) {
    for (let u = 0; u < faceSteps; u += 1) {
      for (let v = 0; v < faceSteps; v += 1) {
        const fu = faceSteps === 1 ? 0.5 : u / (faceSteps - 1);
        const fv = faceSteps === 1 ? 0.5 : v / (faceSteps - 1);
        points.push(facePoint(bbox, face, fu, fv, random, smooth));
      }
    }
  }

  return points;
}

function facePoint(bbox, face, u, v, random, smooth) {
  const x = THREE.MathUtils.lerp(bbox.min.x, bbox.max.x, u);
  const y = THREE.MathUtils.lerp(bbox.min.y, bbox.max.y, v);
  const z = THREE.MathUtils.lerp(bbox.min.z, bbox.max.z, u);
  const jitter = smooth * 0.9;

  if (face === 0) return new THREE.Vector3(bbox.min.x, y, z).add(randomOffset(random, jitter));
  if (face === 1) return new THREE.Vector3(bbox.max.x, y, z).add(randomOffset(random, jitter));
  if (face === 2) return new THREE.Vector3(x, bbox.min.y, z).add(randomOffset(random, jitter));
  if (face === 3) return new THREE.Vector3(x, bbox.max.y, z).add(randomOffset(random, jitter));
  if (face === 4) return new THREE.Vector3(x, y, bbox.min.z).add(randomOffset(random, jitter));
  return new THREE.Vector3(x, y, bbox.max.z).add(randomOffset(random, jitter));
}

function randomOffset(random, amount) {
  return new THREE.Vector3(random() - 0.5, random() - 0.5, random() - 0.5).multiplyScalar(amount);
}

function createNearestEdges(points, maxAxis, edgeReach, sourceGeometry = null) {
  const neighborCount = Math.round(edgeReach + 1);
  const averageSpacing = 1 / Math.cbrt(Math.max(points.length, 1));
  const maxDistance = maxAxis * THREE.MathUtils.clamp(averageSpacing * edgeReach * 1.8, 0.2, 0.72);
  const insideTester = sourceGeometry ? createInsideTester(sourceGeometry) : null;
  return createNearestEdgesFromPositions(points, neighborCount, maxDistance, insideTester);
}

function addBoundingFrame(group, bbox, radius) {
  const corners = [
    new THREE.Vector3(bbox.min.x, bbox.min.y, bbox.min.z),
    new THREE.Vector3(bbox.max.x, bbox.min.y, bbox.min.z),
    new THREE.Vector3(bbox.max.x, bbox.max.y, bbox.min.z),
    new THREE.Vector3(bbox.min.x, bbox.max.y, bbox.min.z),
    new THREE.Vector3(bbox.min.x, bbox.min.y, bbox.max.z),
    new THREE.Vector3(bbox.max.x, bbox.min.y, bbox.max.z),
    new THREE.Vector3(bbox.max.x, bbox.max.y, bbox.max.z),
    new THREE.Vector3(bbox.min.x, bbox.max.y, bbox.max.z),
  ];

  const edges = [
    [0, 1],
    [1, 2],
    [2, 3],
    [3, 0],
    [4, 5],
    [5, 6],
    [6, 7],
    [7, 4],
    [0, 4],
    [1, 5],
    [2, 6],
    [3, 7],
  ];

  for (const [a, b] of edges) addTube(group, corners[a], corners[b], radius);
}

function addTube(group, start, end, radius, material = latticeMaterial) {
  const direction = new THREE.Vector3().subVectors(end, start);
  const length = direction.length();
  if (length < 0.001) return;

  const geometry = new THREE.CylinderGeometry(radius, radius, length, 10, 1, false);
  const tube = new THREE.Mesh(geometry, material);
  const midpoint = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
  const quaternion = new THREE.Quaternion().setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    direction.clone().normalize()
  );

  tube.position.copy(midpoint);
  tube.quaternion.copy(quaternion);
  group.add(tube);
}

function addSupportStrut(group, start, end, radius) {
  if (start.distanceTo(end) < getMinimumUsefulSupportLength(radius)) return false;
  addTube(group, start, end, radius, supportMaterial);
  const nodeGeometry = new THREE.SphereGeometry(radius * 1.18, 10, 8);
  const startNode = new THREE.Mesh(nodeGeometry, supportMaterial);
  startNode.position.copy(start);
  group.add(startNode);
  const endNode = new THREE.Mesh(nodeGeometry.clone(), supportMaterial);
  endNode.position.copy(end);
  group.add(endNode);
  return true;
}

function getMinimumUsefulSupportLength(radius) {
  return Math.max(radius * 5.5, 0.65);
}

function disposeVolumeGroup() {
  state.supportGroup = null;
  disposePrintDiagnosticGroup();
  disposeDebugGroup();
  if (!state.volumeGroup) return;
  disposeGroup(state.volumeGroup);
  state.volumeGroup = null;
}

const DEBUG_COLORS = {
  "seed-points": 0xffca5a,
  "raw-volume-voronoi-edges": 0x7d8790,
  "clipped-interior-centerlines": 0x42d3c4,
  "interior-nodes": 0x5eb7ff,
  "raw-surface-voronoi-segments": 0xff7a67,
  "smoothed-surface-centerlines": 0xd790ff,
  "placed-surface-centerlines": 0xf2f5f7,
  "surface-nodes": 0xff4f74,
  "surface-to-interior-connectors": 0x62e36d,
  "combined-centerline-graph": 0xffd166,
  "final-implicit-mesh": 0x9aa8b2,
};

async function loadDebugGeometry(resultId, finalBounds, metadata) {
  disposeDebugGroup();
  const [manifestResponse, bufferResponse] = await Promise.all([
    fetch(`/api/voronoi/result/${encodeURIComponent(resultId)}/debug-manifest`, { cache: "no-store" }),
    fetch(`/api/voronoi/result/${encodeURIComponent(resultId)}/debug-buffer`, { cache: "no-store" }),
  ]);
  if (!manifestResponse.ok || !bufferResponse.ok) return;
  const manifest = await manifestResponse.json();
  const buffer = await bufferResponse.arrayBuffer();
  const group = new THREE.Group();
  group.name = "LatticeCore diagnostic layers";
  const sourceBounds = metadata?.inputMeshValidation?.bounds;
  if (sourceBounds) {
    const { min, max } = sourceBounds;
    group.position.set(-(min[0] + max[0]) * 0.5, -(min[1] + max[1]) * 0.5, -(min[2] + max[2]) * 0.5);
  } else if (finalBounds) {
    const center = new THREE.Vector3();
    finalBounds.getCenter(center);
    group.position.copy(center).multiplyScalar(-1);
  }
  for (const [name, layer] of Object.entries(manifest.layers)) {
    const positions = new Float32Array(buffer, layer.byteOffset, layer.elementCount);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
    const color = DEBUG_COLORS[name] ?? 0xffffff;
    const object = layer.primitive === "points"
      ? new THREE.Points(geometry, new THREE.PointsMaterial({ color, size: 0.9, sizeAttenuation: true }))
      : layer.primitive === "triangles"
        ? new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.2, side: THREE.DoubleSide }))
        : new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.92 }));
    object.name = `debug:${name}`;
    object.userData.debugLayer = name;
    object.visible = Boolean(document.querySelector(`[data-debug-layer="${name}"]`)?.checked);
    group.add(object);
    const count = document.querySelector(`[data-debug-count="${name}"]`);
    if (count) {
      const size = layer.byteLength / 1024;
      count.textContent = `${layer.returnedElementCount.toLocaleString("cs-CZ")} prvků · ${size.toFixed(1)} KiB${layer.isDownsampled ? " · redukováno" : ""}`;
    }
  }
  state.debugManifest = manifest;
  state.debugGroup = group;
  scene.add(group);
}

function disposeDebugGroup() {
  if (!state.debugGroup) return;
  disposeGroup(state.debugGroup);
  state.debugGroup = null;
  state.debugManifest = null;
}

function updateDebugVisibility() {
  state.debugGroup?.children.forEach((object) => {
    const input = document.querySelector(`[data-debug-layer="${object.userData.debugLayer}"]`);
    object.visible = Boolean(input?.checked);
  });
}

function applyDebugPreset(preset) {
  const layers = preset === "interior"
    ? new Set(["clipped-interior-centerlines", "interior-nodes"])
    : preset === "surface"
      ? new Set(["placed-surface-centerlines", "surface-nodes"])
      : preset === "connectors"
        ? new Set(["surface-to-interior-connectors"])
        : new Set();
  debugLayerInputs.forEach((input) => { input.checked = layers.has(input.dataset.debugLayer); });
  if (preset === "final") {
    if (showFinalMesh) showFinalMesh.checked = true;
  }
  updateDebugVisibility();
  updatePreviewVisibility();
}

async function refreshCacheStatus() {
  const response = await fetch("/api/lattice-cache", { cache: "no-store" }).catch(() => null);
  if (!response?.ok) return;
  const status = await response.json();
  document.querySelector("#cache-size").textContent = `${(status.sizeBytes / 1024 / 1024).toFixed(1)} MiB`;
  document.querySelector("#cache-limit").textContent = `${(status.maximumSizeBytes / 1024 ** 3).toFixed(1)} GiB`;
  document.querySelector("#cache-items").textContent = status.itemCount.toLocaleString("cs-CZ");
  document.querySelector("#cache-oldest").textContent = status.oldestItem ? new Date(status.oldestItem).toLocaleString("cs-CZ") : "-";
}

async function refreshWorkerStatus() {
  const response = await fetch("/api/lattice-worker/status", { cache: "no-store" }).catch(() => null);
  if (!response?.ok) {
    jobUi.worker.textContent = "Nedostupný";
    return;
  }
  const status = await response.json();
  state.workerQueueCount = status.queuedJobCount ?? 0;
  const delayed = ["heartbeat-delayed", "busy-native-operation"].includes(status.responsiveness);
  jobUi.worker.textContent = `${status.status}${status.workerPid ? ` · PID ${status.workerPid}` : ""}${delayed ? " · heartbeat čeká" : ""}`;
  const workingSet = status.memory?.processWorkingSetBytes;
  const peak = status.memory?.processPeakWorkingSetBytes;
  jobUi.memory.textContent = workingSet == null
    ? "nedostupná"
    : `${(workingSet / 1024 ** 2).toFixed(0)} MiB${peak == null ? "" : ` · peak ${(peak / 1024 ** 2).toFixed(0)} MiB`}`;
  updateActiveJobClock();
}

function updateActiveJobClock() {
  const active = Boolean(state.activeJobId && state.activeJobStartedAt);
  const elapsed = active
    ? (performance.now() - state.activeJobStartedAt) / 1000
    : state.lastJobElapsedSeconds;
  jobUi.time.textContent = `${formatJobElapsed(elapsed)} · fronta ${state.workerQueueCount}`;
  if (!active) return;
  const quietSeconds = state.activeJobLastEventAt
    ? (performance.now() - state.activeJobLastEventAt) / 1000
    : 0;
  jobUi.hint.textContent = quietSeconds > 20
    ? `${state.activeJobHint} Worker stále počítá; poslední zpráva před ${formatJobElapsed(quietSeconds)}.`
    : state.activeJobHint;
}

function updateJobPanel(event) {
  const metrics = event.metrics ?? {};
  if (event.status) jobUi.status.textContent = event.status;
  if (event.phase) {
    const phaseLabel = describeJobPhase(event.phase);
    jobUi.phase.textContent = phaseLabel;
    jobUi.progressLabel.textContent = phaseLabel;
  }
  if (metrics.targetIndex != null || event.targetIndex != null) {
    const index = metrics.targetIndex ?? event.targetIndex;
    const count = metrics.targetCount ?? event.targetCount ?? "?";
    const target = metrics.targetDensityPercent ?? event.targetDensityPercent;
    jobUi.target.textContent = `${index}/${count}${target != null ? ` · ${target} %` : ""}`;
  }
  const iteration = metrics.iteration ?? event.iteration;
  if (iteration != null) jobUi.iteration.textContent = String(iteration);
  const scale = metrics.scale ?? event.scale;
  const density = metrics.achievedDensityPercent ?? event.achievedDensityPercent;
  if (scale != null || density != null) {
    jobUi.density.textContent = `${scale != null ? Number(scale).toFixed(4) : "-"} / ${density != null ? `${Number(density).toFixed(3)} %` : "-"}`;
  }
  const cacheHit = metrics.cacheHit ?? event.cacheHit ?? metrics.memoryCacheHit;
  if (cacheHit != null) jobUi.cache.textContent = cacheHit ? "hit" : "miss";
  if (Number.isFinite(event.fraction)) {
    jobUi.progress.hidden = false;
    const fraction = Math.min(1, Math.max(0, event.fraction));
    jobUi.progress.value = fraction;
    jobUi.progressPercent.textContent = `${Math.round(fraction * 100)} %`;
  }
  if (event.message) {
    state.activeJobLastEventAt = performance.now();
    state.activeJobEvents.push(event.message);
    state.activeJobEvents = state.activeJobEvents.slice(-8);
    jobUi.messages.replaceChildren(...state.activeJobEvents.map((message) => {
      const item = document.createElement("li");
      item.textContent = message;
      return item;
    }));
    labels.status.textContent = event.message;
  }
}

async function createAndWaitForJob(query, uploadBody) {
  const workerResponse = await fetch("/api/lattice-worker/status", { cache: "no-store" }).catch(() => null);
  if (workerResponse?.ok) {
    const worker = await workerResponse.json();
    if (worker.status === "busy") {
      throw new Error("Výpočetní worker právě dokončuje jinou úlohu. Počkej na její dokončení nebo ji zruš v záložce, která ji spustila.");
    }
  }
  const response = await fetch(`/api/lattice-jobs?${query.toString()}`, {
    method: "POST",
    body: uploadBody,
    cache: "no-store",
  });
  if (!response.ok) {
    const failure = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
    throw new Error(failure.error ?? `HTTP ${response.status}`);
  }
  const created = await response.json();
  state.activeJobId = created.jobId;
  state.activeJobStartedAt = performance.now();
  state.activeJobLastEventAt = performance.now();
  state.activeJobHint = query.get("meshEngine") === "implicit-union"
    ? "Finální implicitní mesh může u složitých modelů trvat několik minut. Pracovní náhled zůstává zobrazený."
    : "Výpočet probíhá na lokálním Python workeru.";
  state.activeJobEvents = [];
  state.lastJobElapsedSeconds = 0;
  jobUi.status.textContent = created.status;
  jobUi.cancel.disabled = false;
  jobUi.progress.hidden = true;
  jobUi.progressLabel.textContent = "Čekání na první fázi";
  jobUi.progressPercent.textContent = "-";
  jobUi.hint.textContent = state.activeJobHint;
  await refreshWorkerStatus();
  return new Promise((resolve, reject) => {
    const stream = new EventSource(`/api/lattice-jobs/${encodeURIComponent(created.jobId)}/events`);
    let settled = false;
    let checking = false;
    let pollTimer = null;
    const cleanup = () => {
      stream.close();
      if (pollTimer != null) window.clearInterval(pollTimer);
    };
    const finish = async () => {
      if (settled || checking) return;
      checking = true;
      try {
        const resultResponse = await fetch(`/api/lattice-jobs/${encodeURIComponent(created.jobId)}`, { cache: "no-store" });
        if (!resultResponse.ok) return;
        const job = await resultResponse.json();
        updateJobPanel(job.latestEvent ?? job);
        if (!["completed", "failed", "cancelled", "worker-lost"].includes(job.status)) return;
        settled = true;
        cleanup();
        state.lastJobElapsedSeconds = (performance.now() - state.activeJobStartedAt) / 1000;
        state.activeJobId = null;
        state.activeJobStartedAt = 0;
        state.activeJobLastEventAt = 0;
        jobUi.cancel.disabled = true;
        jobUi.status.textContent = job.status;
        jobUi.hint.textContent = job.status === "completed"
          ? `Dokončeno za ${formatJobElapsed(state.lastJobElapsedSeconds)}.`
          : `Úloha skončila stavem ${job.status}.`;
        updateActiveJobClock();
        if (job.status === "completed") resolve(job);
        else reject(new Error(job.error?.message ?? (job.status === "cancelled" ? "Výpočet byl zrušen." : "Výpočet selhal.")));
      } finally {
        checking = false;
      }
    };
    pollTimer = window.setInterval(() => finish().catch(() => {}), 3000);
    stream.onmessage = (message) => {
      const event = JSON.parse(message.data);
      updateJobPanel(event);
      if (event.type === "terminal" || ["job-complete", "job-failed", "job-cancelled"].includes(event.type)) {
        finish().catch(reject);
      }
    };
    stream.onerror = () => {
      finish().catch(() => {});
    };
  });
}

async function cancelActiveJob() {
  if (!state.activeJobId) return;
  jobUi.cancel.disabled = true;
  jobUi.status.textContent = "cancelling";
  await fetch(`/api/lattice-jobs/${encodeURIComponent(state.activeJobId)}/cancel`, { method: "POST" });
}

async function clearWorkerMemoryCache() {
  jobUi.clearMemory.disabled = true;
  try {
    const scope = jobUi.memoryScope?.value ?? "unused";
    const response = await fetch(`/api/lattice-worker/status?scope=${encodeURIComponent(scope)}`, { method: "POST" });
    const result = await response.json();
    labels.status.textContent = `RAM cache: odstraněno ${result.removedSessionCount ?? 0}, aktivní ponecháno ${result.retainedActiveSessionCount ?? 0}.`;
    await refreshWorkerStatus();
  } finally {
    jobUi.clearMemory.disabled = false;
  }
}

async function clearCache(scope) {
  if (!["final-mesh", "surface", "all"].includes(scope)) return;
  if (!window.confirm("Opravdu odstranit vybranou lokální výpočetní cache?")) return;
  const response = await fetch(`/api/lattice-cache?scope=${encodeURIComponent(scope)}`, { method: "POST" });
  if (!response.ok) {
    labels.status.textContent = "Cache se nepodařilo vymazat.";
    return;
  }
  labels.status.textContent = "Vybraná lokální cache byla odstraněna.";
  await refreshCacheStatus();
}

function disposeGroup(group) {
  if (!group) return;
  if (group.parent) group.parent.remove(group);
  scene.remove(group);
  group.traverse((object) => {
    if (object.geometry) object.geometry.dispose();
  });
}

function getPrintSettings() {
  return {
    support: Boolean(printControlsConfig.support.checked),
    plane: printControlsConfig.plane.value,
    rotateX: Number(printControlsConfig.rotateX.value),
    rotateY: Number(printControlsConfig.rotateY.value),
    rotateZ: Number(printControlsConfig.rotateZ.value),
    overhang: Number(printControlsConfig.overhang.value),
  };
}

function getBuildNormal(settings = getPrintSettings()) {
  if (settings.plane === "xy") return new THREE.Vector3(0, 0, 1);
  if (settings.plane === "yz") return new THREE.Vector3(1, 0, 0);
  return new THREE.Vector3(0, 1, 0);
}

function getPrintEuler(settings = getPrintSettings()) {
  return new THREE.Euler(
    THREE.MathUtils.degToRad(settings.rotateX),
    THREE.MathUtils.degToRad(settings.rotateY),
    THREE.MathUtils.degToRad(settings.rotateZ),
    "XYZ"
  );
}

function applyPrintTransforms() {
  const euler = getPrintEuler();
  for (const object of [state.mesh, state.volumeGroup, state.printDiagnosticGroup]) {
    if (!object) continue;
    object.rotation.copy(euler);
    object.position.copy(state.printOffset);
    object.updateMatrixWorld(true);
  }
}

function alignCurrentObjectToBuildPlate() {
  const object = state.volumeGroup ?? state.mesh;
  if (!object) return;
  applyPrintTransforms();
  const normal = getBuildNormal();
  const box = new THREE.Box3().setFromObject(object);
  const corners = [
    new THREE.Vector3(box.min.x, box.min.y, box.min.z),
    new THREE.Vector3(box.min.x, box.min.y, box.max.z),
    new THREE.Vector3(box.min.x, box.max.y, box.min.z),
    new THREE.Vector3(box.min.x, box.max.y, box.max.z),
    new THREE.Vector3(box.max.x, box.min.y, box.min.z),
    new THREE.Vector3(box.max.x, box.min.y, box.max.z),
    new THREE.Vector3(box.max.x, box.max.y, box.min.z),
    new THREE.Vector3(box.max.x, box.max.y, box.max.z),
  ];
  const minProjection = Math.min(...corners.map((corner) => corner.dot(normal)));
  state.printOffset.add(normal.multiplyScalar(-minProjection));
  labels.status.textContent = "Model srovnán na tiskovou rovinu.";
}

function rebuildPrintSupports() {
  disposePrintSupportGroup();
  disposePrintDiagnosticGroup();
  if (!state.volumeGroup) {
    updatePrintAnalysisLabels(null, 0);
    return;
  }

  const analysis = analyzeLayerPrintability(state.volumeGroup);

  if (!printControlsConfig.support.checked) {
    showPrintDiagnosticGroup(analysis);
    updatePrintAnalysisLabels(analysis, 0);
    return;
  }

  const supportGroup = createPrintSupportGroup(state.volumeGroup, analysis);
  if (supportGroup.children.length === 0) {
    showPrintDiagnosticGroup(analysis);
    updatePrintAnalysisLabels(analysis, 0);
    return;
  }

  state.volumeGroup.add(supportGroup);
  state.supportGroup = supportGroup;
  const finalAnalysis = analyzeLayerPrintability(state.volumeGroup, { includeSupports: true });
  showPrintDiagnosticGroup(finalAnalysis);
  updatePrintAnalysisLabels(finalAnalysis, supportGroup.userData.supportStats?.addedStruts ?? supportGroup.children.length);
}

function showPrintDiagnosticGroup(analysis) {
  disposePrintDiagnosticGroup();
  const diagnosticGroup = createPrintDiagnosticGroup(analysis);
  if (diagnosticGroup.children.length === 0) return;
  state.printDiagnosticGroup = diagnosticGroup;
  scene.add(diagnosticGroup);
  applyPrintTransforms();
}

function disposePrintSupportGroup() {
  if (!state.supportGroup) return;
  disposeGroup(state.supportGroup);
  state.supportGroup = null;
}

function disposePrintDiagnosticGroup() {
  if (!state.printDiagnosticGroup) return;
  disposeGroup(state.printDiagnosticGroup);
  state.printDiagnosticGroup = null;
}

function updatePrintAnalysisLabels(analysis, addedStruts) {
  const islands = analysis?.islands ?? 0;
  const fixed = analysis?.regions?.filter((region) => region.anchor).length ?? 0;
  const unresolved = Math.max((analysis?.regions?.length ?? 0) - fixed, 0);
  if (labels.printIslands) labels.printIslands.textContent = String(islands);
  if (labels.printFixed) labels.printFixed.textContent = String(fixed);
  if (labels.printStruts) labels.printStruts.textContent = String(addedStruts);
  if (!labels.printState) return;

  if (!analysis) {
    labels.printState.textContent = printControlsConfig.support.checked ? "Bez zásahu" : "Vypnuto";
  } else if (analysis.regions.length === 0) {
    labels.printState.textContent = "Bez zjištěných nepodepřených oblastí";
  } else if (unresolved > 0) {
    labels.printState.textContent = `Rizika ${analysis.regions.length}, nevyřešeno ${unresolved}`;
  } else if (printControlsConfig.support.checked) {
    labels.printState.textContent = `Přidáno ${addedStruts} prutů`;
  } else {
    labels.printState.textContent = `Analýza: ${analysis.regions.length} oblastí`;
  }
}

function createPrintDiagnosticGroup(analysis) {
  const group = new THREE.Group();
  group.name = "LatticeCore printability diagnostics";
  if (!analysis) return group;

  const riskGeometry = new THREE.SphereGeometry(analysis.markerRadius, 10, 8);
  const anchorGeometry = new THREE.SphereGeometry(analysis.markerRadius * 0.85, 10, 8);
  const limit = 140;
  for (const region of selectRegionsAcrossHeight(analysis.regions, limit)) {
    const risk = new THREE.Mesh(riskGeometry, riskMaterial);
    const anchorTooClose =
      region.anchor && region.anchor.distanceTo(region.target) < Math.max(analysis.markerRadius * 2.35, 0.75);
    risk.position.copy(anchorTooClose ? averageVectors([region.target, region.anchor]) : region.target);
    group.add(risk);

    if (region.anchor && !anchorTooClose) {
      const anchor = new THREE.Mesh(anchorGeometry, anchorMaterial);
      anchor.position.copy(region.anchor);
      group.add(anchor);
    }
  }
  return group;
}

function selectRegionsAcrossHeight(regions, limit) {
  if (regions.length <= limit) return regions;
  const sorted = [...regions].sort((a, b) => a.height - b.height);
  const selected = [];
  const used = new Set();

  for (let index = 0; index < limit; index += 1) {
    const sourceIndex = Math.round((index * (sorted.length - 1)) / Math.max(limit - 1, 1));
    if (used.has(sourceIndex)) continue;
    used.add(sourceIndex);
    selected.push(sorted[sourceIndex]);
  }

  for (let index = 0; selected.length < limit && index < sorted.length; index += 1) {
    if (used.has(index)) continue;
    used.add(index);
    selected.push(sorted[index]);
  }

  return selected;
}

function analyzeLayerPrintability(sourceGroup, options = {}) {
  const settings = getPrintSettings();
  const normalWorld = getBuildNormal(settings).normalize();
  const inverseRotation = new THREE.Quaternion().setFromEuler(getPrintEuler(settings)).invert();
  const normal = normalWorld.clone().applyQuaternion(inverseRotation).normalize();
  const params = getLatticeParams();
  const box = new THREE.Box3().setFromObject(sourceGroup);
  const size = new THREE.Vector3();
  box.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  const averageRadius = Math.max(params.strutDiameter * 0.5, maxAxis * 0.0045);
  const layerHeight = Math.max(0.18, Math.min(0.32, averageRadius * 0.8));
  const cellSize = Math.max(averageRadius * 2.4, layerHeight * 1.8);
  const maxAngleFromVerticalDeg = THREE.MathUtils.clamp(settings.overhang, 25, 75);
  const dilationRadius = layerHeight * Math.tan(THREE.MathUtils.degToRad(maxAngleFromVerticalDeg));
  const dilationCells = Math.max(1, Math.ceil(dilationRadius / cellSize));
  const basis = createPrintBasis(normal);
  const points = collectPrintAnalysisPoints(sourceGroup, normal, basis, cellSize, options);

  if (points.length === 0) {
    return {
      islands: 0,
      regions: [],
      markerRadius: Math.max(averageRadius * 1.7, 0.55),
      layerHeight,
      dilationRadius,
    };
  }

  const minProjection = Math.min(...points.map((point) => point.z));
  const layers = new Map();
  for (const point of points) {
    const layer = Math.max(0, Math.floor((point.z - minProjection) / layerHeight));
    const ix = Math.round(point.x / cellSize);
    const iy = Math.round(point.y / cellSize);
    const key = `${ix}:${iy}`;
    if (!layers.has(layer)) layers.set(layer, new Map());
    const layerCells = layers.get(layer);
    if (!layerCells.has(key)) {
      layerCells.set(key, { ix, iy, layer, points: [], supported: false });
    }
    layerCells.get(key).points.push(point.position);
  }

  const layerIds = [...layers.keys()].sort((a, b) => a - b);
  let previousSupported = new Map();
  const unsupportedCells = [];
  const supportedAnchorPoints = [];

  for (const layer of layerIds) {
    const layerCells = layers.get(layer);
    const currentSupported = new Map();
    for (const [key, cell] of layerCells) {
      const onBuildPlate = layer === layerIds[0];
      const supported = onBuildPlate || hasDilatedSupport(cell, previousSupported, dilationCells);
      cell.supported = supported;
      const point = averageVectors(cell.points);
      if (supported) {
        currentSupported.set(key, cell);
        supportedAnchorPoints.push(point);
      } else {
        unsupportedCells.push({ ...cell, point });
      }
    }
    previousSupported = currentSupported;
  }

  const regions = groupUnsupportedLayerCells(unsupportedCells, normal);
  const candidateData = getSelfSupportCandidateData(sourceGroup, normal, Math.max(averageRadius * 2.2, cellSize * 0.55));
  const anchorPool = [
    ...candidateData.anchorCandidates.map((candidate) => candidate.point),
    ...supportedAnchorPoints,
  ];
  const maxSupportLength = Math.max(maxAxis * 0.32, averageRadius * 20);
  const minSupportLength = getMinimumUsefulSupportLength(averageRadius);
  const minSupportAngleFromPlate = 90 - maxAngleFromVerticalDeg;

  for (const region of regions) {
    region.anchor = findLayerSupportAnchor(region.target, anchorPool, normal, minSupportAngleFromPlate, maxSupportLength, minSupportLength);
  }

  return {
    islands: regions.length,
    regions,
    markerRadius: Math.max(averageRadius * 1.7, 0.55),
    layerHeight,
    dilationRadius,
  };
}

function createPrintBasis(normal) {
  const helper = Math.abs(normal.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0);
  const u = new THREE.Vector3().crossVectors(helper, normal).normalize();
  const v = new THREE.Vector3().crossVectors(normal, u).normalize();
  return { u, v };
}

function collectPrintAnalysisPoints(group, normal, basis, cellSize, options = {}) {
  const samples = [];
  group.updateMatrixWorld(true);
  group.traverse((object) => {
    if (!object.isMesh || !object.geometry?.attributes?.position) return;
    if (!options.includeSupports && object.parent?.name === "LatticeCore self-support struts") return;
    const position = object.geometry.attributes.position;
    const matrixToGroup = new THREE.Matrix4().copy(group.matrixWorld).invert().multiply(object.matrixWorld);
    const point = new THREE.Vector3();
    const step = Math.max(1, Math.floor(position.count / 18000));
    for (let index = 0; index < position.count; index += step) {
      point.fromBufferAttribute(position, index).applyMatrix4(matrixToGroup);
      samples.push({
        position: point.clone(),
        x: point.dot(basis.u),
        y: point.dot(basis.v),
        z: point.dot(normal),
      });
    }
  });
  return samples;
}

function hasDilatedSupport(cell, previousSupported, dilationCells) {
  for (let dx = -dilationCells; dx <= dilationCells; dx += 1) {
    for (let dy = -dilationCells; dy <= dilationCells; dy += 1) {
      if (dx * dx + dy * dy > dilationCells * dilationCells) continue;
      if (previousSupported.has(`${cell.ix + dx}:${cell.iy + dy}`)) return true;
    }
  }
  return false;
}

function groupUnsupportedLayerCells(cells, normal) {
  const cellMap = new Map();
  for (const cell of cells) {
    cell.key = `${cell.layer}:${cell.ix}:${cell.iy}`;
    cellMap.set(cell.key, cell);
  }

  const visited = new Set();
  const regions = [];
  for (const cell of cells) {
    if (visited.has(cell.key)) continue;
    const queue = [cell];
    const regionCells = [];
    visited.add(cell.key);

    while (queue.length > 0) {
      const current = queue.pop();
      regionCells.push(current);
      for (let dz = -1; dz <= 1; dz += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          for (let dy = -1; dy <= 1; dy += 1) {
            if (dx === 0 && dy === 0 && dz === 0) continue;
            const neighborKey = `${current.layer + dz}:${current.ix + dx}:${current.iy + dy}`;
            if (visited.has(neighborKey) || !cellMap.has(neighborKey)) continue;
            visited.add(neighborKey);
            queue.push(cellMap.get(neighborKey));
          }
        }
      }
    }

    const points = regionCells.map((item) => item.point);
    const target = points.reduce((lowest, point) => (point.dot(normal) < lowest.dot(normal) ? point : lowest), points[0]).clone();
    regions.push({
      target,
      cells: regionCells,
      anchor: null,
      height: target.dot(normal),
    });
  }

  return regions.sort((a, b) => a.target.dot(normal) - b.target.dot(normal));
}

function findLayerSupportAnchor(target, candidates, normal, minSupportAngleFromPlateDeg, maxSupportLength, minSupportLength = 0.001) {
  let best = null;
  let bestScore = Infinity;
  const minRiseRatio = Math.sin(THREE.MathUtils.degToRad(minSupportAngleFromPlateDeg));
  const targetProjection = target.dot(normal);
  const seen = new Set();

  for (const candidate of candidates) {
    const key = candidate.toArray().map((value) => value.toFixed(2)).join(":");
    if (seen.has(key)) continue;
    seen.add(key);

    const drop = targetProjection - candidate.dot(normal);
    if (drop <= 0.001) continue;
    const direction = new THREE.Vector3().subVectors(target, candidate);
    const length = direction.length();
    if (length < minSupportLength || length > maxSupportLength) continue;
    const riseRatio = Math.abs(direction.dot(normal)) / length;
    if (riseRatio < minRiseRatio) continue;

    const lateral = Math.sqrt(Math.max(length * length - drop * drop, 0));
    const score = length + lateral * 0.35 + (riseRatio - minRiseRatio) * -2;
    if (score < bestScore) {
      bestScore = score;
      best = candidate;
    }
  }

  return best ? best.clone() : null;
}


function createPrintSupportGroup(sourceGroup, analysis = null) {
  const settings = getPrintSettings();
  const supportGroup = new THREE.Group();
  supportGroup.name = "LatticeCore self-support struts";
  supportGroup.userData.supportStats = {
    risks: 0,
    unresolved: 0,
    source: "mesh",
    addedStruts: 0,
    mergedCloseNodes: 0,
  };
  const normalWorld = getBuildNormal(settings).normalize();
  const inverseRotation = new THREE.Quaternion().setFromEuler(getPrintEuler(settings)).invert();
  const normalLocal = normalWorld.clone().applyQuaternion(inverseRotation).normalize();
  const params = getLatticeParams();
  const radius = Math.max(params.strutDiameter * 0.42, 0.08);
  const overhangThreshold = -Math.sin(THREE.MathUtils.degToRad(settings.overhang));
  const box = new THREE.Box3().setFromObject(sourceGroup);
  const size = new THREE.Vector3();
  box.getSize(size);
  const spacing = Math.max(Math.max(size.x, size.y, size.z) * 0.055, radius * 8);
  const candidateData = getSelfSupportCandidateData(sourceGroup, normalLocal, Math.max(radius * 2.2, spacing * 0.18));
  const candidates = candidateData.candidates.sort((a, b) => b.projection - a.projection);
  supportGroup.userData.supportStats.source = candidateData.source;
  const usedCells = new Set();
  const maxSupports = 160;
  const maxNodeSupports = 96;
  const minDrop = Math.max(radius * 5, spacing * 0.18);
  const maxLength = Math.max(spacing * 2.9, radius * 22);
  const minPrintableRise = Math.sin(THREE.MathUtils.degToRad(38));
  const minProjection = candidates.reduce((lowest, candidate) => Math.min(lowest, candidate.projection), Infinity);
  const nodeCellSize = Math.max(spacing * 0.66, radius * 8);
  const faceCellSize = Math.max(spacing * 0.62, radius * 8);

  const layerSupportRegions = selectSupportRegions(analysis?.regions ?? [], maxSupports);
  for (const region of layerSupportRegions) {
    if (supportGroup.userData.supportStats.addedStruts >= maxSupports) break;
    supportGroup.userData.supportStats.risks += 1;
    if (!region.anchor) {
      supportGroup.userData.supportStats.unresolved += 1;
      continue;
    }
    const key = region.target.clone().divideScalar(nodeCellSize).floor().toArray().join(":");
    if (usedCells.has(key)) continue;
    usedCells.add(key);
    if (addSupportStrut(supportGroup, region.anchor, region.target, radius)) {
      supportGroup.userData.supportStats.addedStruts += 1;
    } else {
      supportGroup.userData.supportStats.mergedCloseNodes += 1;
    }
  }

  sourceGroup.updateMatrixWorld(true);
  sourceGroup.traverse((object) => {
    if (supportGroup.userData.supportStats.addedStruts >= maxSupports) return;
    if (!object.isMesh || !object.geometry?.attributes?.position) return;
    if (object.parent?.name === supportGroup.name) return;

    const position = object.geometry.attributes.position;
    const step = Math.max(1, Math.floor(position.count / 4200));
    const matrixToGroup = new THREE.Matrix4().copy(sourceGroup.matrixWorld).invert().multiply(object.matrixWorld);
    const a = new THREE.Vector3();
    const b = new THREE.Vector3();
    const c = new THREE.Vector3();
    const normal = new THREE.Vector3();
    const center = new THREE.Vector3();

    for (let index = 0; index < position.count - 2 && supportGroup.userData.supportStats.addedStruts < maxSupports; index += 3 * step) {
      a.fromBufferAttribute(position, index).applyMatrix4(matrixToGroup);
      b.fromBufferAttribute(position, index + 1).applyMatrix4(matrixToGroup);
      c.fromBufferAttribute(position, index + 2).applyMatrix4(matrixToGroup);
      normal.crossVectors(new THREE.Vector3().subVectors(b, a), new THREE.Vector3().subVectors(c, a)).normalize();
      if (normal.dot(normalLocal) >= overhangThreshold) continue;
      supportGroup.userData.supportStats.risks += 1;

      center.copy(a).add(b).add(c).multiplyScalar(1 / 3);
      const centerProjection = center.dot(normalLocal);

      const key = center.clone().divideScalar(faceCellSize).floor().toArray().join(":");
      if (usedCells.has(key)) continue;

      const anchor = findSelfSupportAnchor(
        center,
        centerProjection,
        candidateData.anchorCandidates,
        normalLocal,
        minDrop,
        maxLength,
        minPrintableRise,
      );
      if (!anchor) {
        supportGroup.userData.supportStats.unresolved += 1;
        continue;
      }

      usedCells.add(key);
      if (addSupportStrut(supportGroup, anchor, center, radius)) {
        supportGroup.userData.supportStats.addedStruts += 1;
      } else {
        supportGroup.userData.supportStats.mergedCloseNodes += 1;
      }
    }
  });

  let nodeSupports = 0;
  for (const candidate of candidates) {
    if (supportGroup.userData.supportStats.addedStruts >= maxSupports) break;
    if (nodeSupports >= maxNodeSupports) break;
    if (candidate.weight < candidateData.strongWeight) continue;
    if (candidate.projection - minProjection < minDrop * 1.35) continue;
    if (
      hasExistingLowerSupport(
        candidate,
        candidates,
        normalLocal,
        minDrop,
        Math.max(radius * 4, spacing * 0.18),
        minPrintableRise,
        candidateData.edgeMap,
      )
    ) {
      continue;
    }
    supportGroup.userData.supportStats.risks += 1;

    const key = candidate.point.clone().divideScalar(nodeCellSize).floor().toArray().join(":");
    if (usedCells.has(key)) continue;

    const anchor = findSelfSupportAnchor(
      candidate.point,
      candidate.projection,
      candidateData.anchorCandidates,
      normalLocal,
      minDrop,
      maxLength,
      minPrintableRise,
    );
    if (!anchor) {
      supportGroup.userData.supportStats.unresolved += 1;
      continue;
    }

    usedCells.add(key);
    if (addSupportStrut(supportGroup, anchor, candidate.point, radius)) {
      supportGroup.userData.supportStats.addedStruts += 1;
      nodeSupports += 1;
    } else {
      supportGroup.userData.supportStats.mergedCloseNodes += 1;
    }
  }

  return supportGroup;
}

function selectSupportRegions(regions, limit) {
  const anchored = regions.filter((region) => region.anchor);
  const unresolved = regions.filter((region) => !region.anchor);
  const selected = selectRegionsAcrossHeight(anchored, limit);
  if (selected.length >= limit) return selected;
  return [...selected, ...selectRegionsAcrossHeight(unresolved, limit - selected.length)];
}

function getSelfSupportCandidateData(group, normal, mergeDistance) {
  const metadataCandidates = collectMetadataSelfSupportCandidates(group, normal);
  if (metadataCandidates.length > 0) {
    return {
      candidates: metadataCandidates,
      anchorCandidates: metadataCandidates,
      edgeMap: createMetadataEdgeMap(group.userData?.latticeEdges),
      source: "graph",
      strongWeight: 1,
    };
  }

  const candidates = collectSelfSupportCandidates(group, normal, mergeDistance);
  const weights = candidates.map((candidate) => candidate.weight).sort((a, b) => a - b);
  const strongWeight = weights.length > 0 ? weights[Math.floor(weights.length * 0.62)] : 1;
  const strongWeightFloor = Math.max(strongWeight, 2);
  const anchorCandidates = candidates.filter((candidate) => candidate.weight >= strongWeightFloor);
  return {
    candidates,
    anchorCandidates: anchorCandidates.length > 0 ? anchorCandidates : candidates,
    edgeMap: null,
    source: "mesh",
    strongWeight: strongWeightFloor,
  };
}

function collectMetadataSelfSupportCandidates(group, normal) {
  const nodes = group.userData?.latticeNodes;
  if (!Array.isArray(nodes) || nodes.length === 0) return [];
  return nodes.map((point, index) => ({
    id: index,
    point: point.clone(),
    projection: point.dot(normal),
    weight: 999,
  }));
}

function createMetadataEdgeMap(edges) {
  if (!Array.isArray(edges)) return null;
  const edgeMap = new Map();
  for (const [start, end] of edges) {
    if (!edgeMap.has(start)) edgeMap.set(start, new Set());
    if (!edgeMap.has(end)) edgeMap.set(end, new Set());
    edgeMap.get(start).add(end);
    edgeMap.get(end).add(start);
  }
  return edgeMap;
}

function collectSelfSupportCandidates(group, normal, mergeDistance) {
  const candidatesByKey = new Map();
  group.updateMatrixWorld(true);
  group.traverse((object) => {
    if (!object.isMesh || !object.geometry?.attributes?.position) return;
    if (object.parent?.name === "LatticeCore self-support struts") return;
    const position = object.geometry.attributes.position;
    const matrixToGroup = new THREE.Matrix4().copy(group.matrixWorld).invert().multiply(object.matrixWorld);
    const point = new THREE.Vector3();
    const step = Math.max(1, Math.floor(position.count / 9000));
    for (let index = 0; index < position.count; index += step) {
      point.fromBufferAttribute(position, index).applyMatrix4(matrixToGroup);
      const key = point.clone().divideScalar(mergeDistance).floor().toArray().join(":");
      if (!candidatesByKey.has(key)) {
        candidatesByKey.set(key, {
          point: new THREE.Vector3(),
          count: 0,
        });
      }
      const candidate = candidatesByKey.get(key);
      candidate.point.add(point);
      candidate.count += 1;
    }
  });
  return [...candidatesByKey.values()]
    .filter((candidate) => candidate.count >= 2)
    .map((candidate) => {
      candidate.point.multiplyScalar(1 / candidate.count);
      candidate.projection = candidate.point.dot(normal);
      candidate.weight = candidate.count;
      return candidate;
    });
}

function hasExistingLowerSupport(node, candidates, normal, minDrop, maxLateral, minPrintableRise, edgeMap = null) {
  const linkedIds = edgeMap && node.id != null ? edgeMap.get(node.id) : null;
  const candidatesToCheck = linkedIds
    ? candidates.filter((candidate) => linkedIds.has(candidate.id))
    : candidates;

  for (const candidate of candidatesToCheck) {
    const drop = node.projection - candidate.projection;
    if (drop < minDrop * 0.65) continue;

    const direction = new THREE.Vector3().subVectors(node.point, candidate.point);
    const length = direction.length();
    if (length < minDrop) continue;

    const riseRatio = Math.abs(direction.dot(normal)) / length;
    if (riseRatio < minPrintableRise) continue;

    const lateral = Math.sqrt(Math.max(length * length - drop * drop, 0));
    if (lateral <= maxLateral) return true;
  }

  return false;
}

function findSelfSupportAnchor(center, centerProjection, candidates, normal, minDrop, maxLength, minPrintableRise) {
  let best = null;
  let bestScore = Infinity;

  for (const candidate of candidates) {
    const drop = centerProjection - candidate.projection;
    if (drop < minDrop) continue;

    const direction = new THREE.Vector3().subVectors(center, candidate.point);
    const length = direction.length();
    if (length < minDrop || length > maxLength) continue;

    const riseRatio = Math.abs(direction.dot(normal)) / length;
    if (riseRatio < minPrintableRise) continue;

    const lateral = Math.sqrt(Math.max(length * length - drop * drop, 0));
    const score = lateral + length * 0.28;
    if (score >= bestScore) continue;
    bestScore = score;
    best = candidate.point;
  }

  return best ? best.clone() : null;
}

function getSeedSalt() {
  const params = getLatticeParams();
  return Math.round(
    params.cellCount * 19 +
      params.edgeReach * 230 +
      params.strutDiameter * 100 +
      params.randomness * 1000
  );
}

function mulberry32(seed) {
  return function random() {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function updateLabels() {
  const params = getLatticeParams();
  const print = getPrintSettings();
  labels.boxX.textContent = `${params.boxX.toFixed(0)} mm`;
  labels.boxY.textContent = `${params.boxY.toFixed(0)} mm`;
  labels.boxZ.textContent = `${params.boxZ.toFixed(0)} mm`;
  labels.cellSize.textContent = params.cellCount.toFixed(0);
  labels.depth.textContent = `${params.surfaceOffset.toFixed(1)} mm`;
  labels.wall.textContent = `${params.strutDiameter.toFixed(2)} mm`;
  labels.minStrut.textContent = `${params.minStrutLength.toFixed(1)} mm`;
  labels.seed.textContent = params.randomSeed.toFixed(0);
  labels.density.textContent = params.edgeReach.toFixed(1);
  labels.smooth.textContent = params.randomness.toFixed(2);
  labels.printSupport.textContent = print.support ? "zap" : "vyp";
  labels.rotateX.textContent = `${print.rotateX.toFixed(0)}°`;
  labels.rotateY.textContent = `${print.rotateY.toFixed(0)}°`;
  labels.rotateZ.textContent = `${print.rotateZ.toFixed(0)}°`;
  labels.overhang.textContent = `${print.overhang.toFixed(0)}°`;
  labels.mode.textContent = state.mode === "surface" ? "Plošný režim" : "Objemový lattice";
  labels.pattern.textContent = patternSelect.options[patternSelect.selectedIndex].text;
  updateMeshingControls(params);
}

function updateMeshingControls(params = getLatticeParams()) {
  const quality = controlsConfig.qualityPreset.value;
  const voxelsAcross = { preview: 4, standard: 6, high: 10 }[quality];
  if (voxelsAcross) {
    controlsConfig.voxelSize.value = (params.strutDiameter / voxelsAcross).toFixed(4);
  }
  controlsConfig.voxelSize.disabled = quality !== "custom";
  const voxelSize = Number(controlsConfig.voxelSize.value);
  labels.voxelSize.textContent = `${voxelSize.toFixed(3)} mm`;
  const implicit = controlsConfig.meshEngine.value === "implicit-union";
  const estimate = estimateImplicitGrid({ ...params, voxelSizeMm: voxelSize });
  const unsafe = estimate.totalVoxels > 32_000_000 || estimate.estimatedBytes > 768 * 1024 * 1024;
  const tooCoarse = voxelSize > params.strutDiameter / 3;
  meshEngineNote.textContent = !implicit
    ? "Rychlý náhled používá překrývající se válce a uzly. Výsledek nemusí být manifold."
    : unsafe
      ? "Nastavení překračuje bezpečný limit 32 milionů voxelů nebo 768 MiB."
      : tooCoarse
        ? "Rozlišení je příliš hrubé vzhledem k průměru prutu."
        : "Pruty a uzly jsou spojeny do jednoho implicitního objemu.";
  meshEngineNote.classList.toggle("error-text", implicit && unsafe);
  if (!state.volumeGroup?.userData?.metadata) updateMetadataPanels(null);
}

function estimateImplicitGrid(params = getLatticeParams()) {
  const voxel = Math.max(params.voxelSizeMm, 0.0001);
  const dimensions = new THREE.Vector3(params.boxX, params.boxY, params.boxZ);
  if (state.geometry?.userData?.latticeShape === "mesh") {
    const bounds = state.geometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(state.geometry.attributes.position);
    bounds.getSize(dimensions);
  }
  const gridSizeX = Math.ceil((dimensions.x + 4 * voxel) / voxel) + 1;
  const gridSizeY = Math.ceil((dimensions.y + 4 * voxel) / voxel) + 1;
  const gridSizeZ = Math.ceil((dimensions.z + 4 * voxel) / voxel) + 1;
  const totalVoxels = gridSizeX * gridSizeY * gridSizeZ;
  return {
    gridSizeX,
    gridSizeY,
    gridSizeZ,
    totalVoxels,
    estimatedBytes: totalVoxels * 4 * 6,
  };
}

function updateStats() {
  const object = state.volumeGroup ?? state.mesh;
  if (!object) return;

  const box = new THREE.Box3().setFromObject(object);
  const size = new THREE.Vector3();
  box.getSize(size);

  labels.triangles.textContent = countTriangles(object).toLocaleString("cs-CZ");
  labels.dimensions.textContent = `${size.x.toFixed(1)} x ${size.y.toFixed(1)} x ${size.z.toFixed(1)} mm`;
  labels.exportState.textContent = state.mode === "surface" ? "Povrchová síť STL" : "Lattice STL";
  if (labels.printState && !state.supportGroup && !state.printDiagnosticGroup) {
    labels.printState.textContent = printControlsConfig.support.checked ? "Bez zásahu" : "Vypnuto";
  }
  updateMetadataPanels(state.volumeGroup?.userData?.metadata ?? null);
}

function updateMetadataPanels(metadata) {
  const statistics = metadata?.statistics;
  const validation = metadata?.outputMeshValidation ?? metadata?.meshValidation;
  const setText = (element, value, fallback = "-") => {
    if (element) element.textContent = value ?? fallback;
  };

  setText(labels.statVoronoiVertices, statistics?.voronoiVertexCount?.toLocaleString("cs-CZ"));
  setText(labels.statStruts, statistics?.strutCountAfterFiltering?.toLocaleString("cs-CZ"));
  setText(labels.statRemovedShort, statistics?.removedShortStrutCount?.toLocaleString("cs-CZ"));
  setText(labels.statComponents, statistics?.connectedComponentCount?.toLocaleString("cs-CZ"));
  setText(labels.statIsolated, statistics?.isolatedNodeCount?.toLocaleString("cs-CZ"));
  setText(labels.statAverageDegree, statistics ? statistics.averageNodeDegree.toFixed(2) : null);
  setText(labels.statMaximumDegree, statistics?.maximumNodeDegree?.toLocaleString("cs-CZ"));
  setText(labels.statTotalLength, statistics ? `${statistics.totalStrutLengthMm.toFixed(1)} mm` : null);
  setText(labels.statOvershoot, statistics ? `${statistics.maximumBoundaryOvershootMm.toFixed(3)} mm` : null);
  setText(labels.statSurfaceSegments, metadata?.surfaceGraph?.cleanSegmentCount?.toLocaleString("cs-CZ"));
  setText(labels.statSurfaceConnectors, metadata?.surfaceConnections?.acceptedConnectorCount?.toLocaleString("cs-CZ"));
  setText(
    labels.statUnconnectedSurface,
    metadata?.surfaceConnections?.unconnectedSurfaceComponentCount?.toLocaleString("cs-CZ"),
  );

  setText(labels.validationWatertight, validation ? (validation.isWatertight ? "Ano" : "Ne") : null);
  setText(labels.validationManifold, validation ? (validation.isEdgeManifold ? "Ano" : "Ne") : null);
  setText(labels.validationBoundary, validation?.boundaryEdgeCount?.toLocaleString("cs-CZ"));
  setText(labels.validationNonManifold, validation?.nonManifoldEdgeCount?.toLocaleString("cs-CZ"));
  setText(labels.validationComponents, validation?.connectedComponentCount?.toLocaleString("cs-CZ"));
  setText(labels.validationVolume, validation ? `${validation.absoluteVolumeMm3.toFixed(1)} mm³` : null);

  const implicit = metadata?.implicitMeshing;
  updateDensityResults(metadata);
  if (!metadata) {
    const params = getLatticeParams();
    const estimate = estimateImplicitGrid(params);
    setText(labels.implicitEngine, params.meshEngine);
    setText(labels.implicitVoxel, params.meshEngine === "implicit-union" ? `${params.voxelSizeMm.toFixed(3)} mm` : "Legacy");
    setText(labels.implicitGrid, `${estimate.gridSizeX} × ${estimate.gridSizeY} × ${estimate.gridSizeZ}`);
    setText(labels.implicitVoxels, estimate.totalVoxels.toLocaleString("cs-CZ"));
    setText(labels.implicitMemory, `${(estimate.estimatedBytes / 1024 / 1024).toFixed(1)} MiB`);
    setText(labels.implicitTime, null);
    setText(labels.implicitClipping, params.boundaryMode === "exact" ? "implicit-sdf-intersection" : "centerline-domain-filter");
  } else {
    setText(labels.implicitEngine, metadata.meshEngine);
    setText(labels.implicitVoxel, implicit?.enabled ? `${implicit.voxelSizeMm.toFixed(3)} mm` : "Legacy");
    setText(
      labels.implicitGrid,
      implicit?.enabled ? `${implicit.gridSizeX} × ${implicit.gridSizeY} × ${implicit.gridSizeZ}` : null,
    );
    setText(labels.implicitVoxels, implicit?.enabled ? implicit.totalVoxelCount.toLocaleString("cs-CZ") : null);
    setText(
      labels.implicitMemory,
      implicit?.enabled ? `${(implicit.estimatedMemoryBytes / 1024 / 1024).toFixed(1)} MiB` : null,
    );
    setText(labels.implicitTime, implicit?.enabled ? `${implicit.generationTimeSeconds.toFixed(2)} s` : null);
    setText(labels.implicitClipping, metadata.clippingImplementation);
  }

  const invalid = Boolean(validation && !validation.isWatertight);
  meshValidationPanel?.classList.toggle("invalid", invalid);
  if (labels.validationWarning) labels.validationWarning.hidden = !invalid;
}

function updateDensityResults(metadata) {
  const volume = metadata?.volumeStatistics;
  const control = metadata?.densityControl;
  const mass = metadata?.massEstimate;
  const text = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value ?? "-";
  };
  text("#density-target-result", control?.targetRelativeDensityPercent != null ? `${control.targetRelativeDensityPercent.toFixed(2)} %` : "-");
  text("#density-achieved-result", volume ? `${volume.relativeDensityPercent.toFixed(2)} %` : "-");
  text("#density-verified-result", control?.finalVerifiedDensity != null ? `${(control.finalVerifiedDensity * 100).toFixed(2)} %` : "-");
  text("#density-initial-verified-result", control?.finalVerification?.initialVerifiedDensity != null
    ? `${(control.finalVerification.initialVerifiedDensity * 100).toFixed(2)} %`
    : "-");
  text("#density-corrections-result", control?.finalVerification
    ? `${control.finalVerification.correctionWasRequired ? "ano" : "ne"} · ${control.finalVerification.correctionIterations?.length ?? 0}`
    : "-");
  text("#density-termination-result", control?.finalVerification?.terminationReason ?? control?.terminationReason ?? "-");
  text("#porosity-result", volume ? `${volume.porosityPercent.toFixed(2)} %` : "-");
  text("#density-scale-result", control?.selectedGlobalRadiusScale?.toFixed(5) ?? "1.00000");
  text("#lattice-volume-result", volume ? `${volume.latticeVolumeMm3.toFixed(2)} mm³` : "-");
  text("#domain-volume-result", volume ? `${volume.domainVolumeMm3.toFixed(2)} mm³` : "-");
  text("#mass-result", mass?.estimatedMassG != null ? `${mass.estimatedMassG.toFixed(3)} g` : "Není zadána hustota materiálu");
  text("#mass-reduction-result", mass?.massReductionPercent != null ? `${mass.massReductionPercent.toFixed(2)} %` : "-");
  text("#density-iterations-result", control?.iterationCount ? `${control.iterationCount} / ${control.solverTimeSeconds.toFixed(2)} s` : "-");
  renderDensityIterations(control?.iterations ?? [], control?.targetRelativeDensityPercent, control?.selectedGlobalRadiusScale);
}

function renderDensityIterations(iterations, targetPercent, selectedScale) {
  const body = document.querySelector("#density-iteration-table tbody");
  body.replaceChildren();
  for (const item of iterations) {
    const row = document.createElement("tr");
    const values = [
      item.phase === "primary" ? `P${item.iteration}` : `F${item.iteration ?? ""}`,
      item.globalRadiusScale.toFixed(4),
      item.interiorStrutDiameterMm?.toFixed(3) ?? "-",
      `${item.relativeDensityPercent.toFixed(2)} %`,
      `${item.errorPercentPoints.toFixed(2)} pp`,
      `${item.generationTimeSeconds.toFixed(2)} s`,
      item.cacheHit ? "hit" : "miss",
    ];
    values.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    body.appendChild(row);
  }
  const chart = document.querySelector("#density-chart");
  if (!iterations.length) {
    chart.replaceChildren();
    return;
  }
  const scales = iterations.map((item) => item.globalRadiusScale);
  const densities = iterations.map((item) => item.relativeDensityPercent);
  const minX = Math.min(...scales);
  const maxX = Math.max(...scales);
  const maxY = Math.max(...densities, targetPercent ?? 0, 1);
  const point = (item) => {
    const x = 16 + ((item.globalRadiusScale - minX) / Math.max(maxX - minX, 1e-9)) * 208;
    const y = 106 - (item.relativeDensityPercent / maxY) * 92;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  };
  const targetY = 106 - ((targetPercent ?? 0) / maxY) * 92;
  chart.innerHTML = `<line x1="16" y1="${targetY}" x2="224" y2="${targetY}" stroke="#f0bb63" stroke-dasharray="4 3"/><polyline points="${iterations.map(point).join(" ")}" fill="none" stroke="#4fc3b5" stroke-width="2"/>${iterations.map((item) => { const [x,y] = point(item).split(","); const selected = Math.abs(item.globalRadiusScale - selectedScale) < 1e-8; const color = selected ? "#f0bb63" : item.phase === "primary" ? "#eef3f6" : "#4fc3b5"; return `<circle cx="${x}" cy="${y}" r="${selected ? 4.5 : 3}" fill="${color}"/>`; }).join("")}`;
}

function renderBatchResults(summary) {
  const panel = document.querySelector("#density-batch-results-panel");
  const body = document.querySelector("#density-batch-table tbody");
  const buttons = [exportBatchZipButton, exportBatchSummaryCsvButton, exportBatchSummaryJsonButton];
  panel.hidden = !summary;
  buttons.forEach((button) => { button.hidden = !summary; });
  body.replaceChildren();
  if (!summary) return;
  const statistics = summary.batchEvaluationStatistics;
  const text = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value;
  };
  text("#batch-completion-result", `${statistics.completedTargetCount} / ${statistics.failedTargetCount}`);
  text("#batch-evaluations-result", String(statistics.uniqueScaleEvaluationCount));
  text("#batch-reused-result", String(statistics.reusedEvaluationCount));
  text("#batch-cache-result", `${statistics.totalCacheHits} / ${statistics.totalCacheMisses}`);
  text("#batch-time-result", `${summary.totalJobTimeSeconds.toFixed(2)} s`);
  text("#batch-zip-size-result", formatBytes(state.batchZipBytes));
  for (const item of summary.results) {
    const row = document.createElement("tr");
    const values = [
      `${item.targetDensityPercent.toFixed(2)} %`,
      item.finalDensityPercent != null ? `${item.finalDensityPercent.toFixed(2)} %` : "-",
      item.errorPercentPoints != null ? `${item.errorPercentPoints.toFixed(2)} pp` : "-",
      item.globalRadiusScale?.toFixed(4) ?? "-",
      item.interiorStrutDiameterMm?.toFixed(3) ?? "-",
      item.estimatedMassG != null ? `${item.estimatedMassG.toFixed(3)} g` : "-",
      item.totalIterations ?? "-",
      item.converged ? "OK" : item.terminationReason,
    ];
    values.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    const exportCell = document.createElement("td");
    if (item.stlFileName) {
      const link = document.createElement("a");
      link.href = state.batchAssets?.[item.stlFileName] ?? "#";
      link.textContent = "STL";
      link.download = item.stlFileName;
      exportCell.appendChild(link);
    }
    row.appendChild(exportCell);
    body.appendChild(row);
  }
}

function countTriangles(object) {
  let triangles = 0;
  object.traverse((item) => {
    if (item.geometry?.attributes?.position) {
      triangles += Math.round(item.geometry.attributes.position.count / 3);
    }
  });
  return triangles;
}

function fitCameraToGeometry(geometry) {
  const box = geometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(geometry.attributes.position);
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);
  const maxSize = Math.max(size.x, size.y, size.z) || 40;
  const distance = maxSize * 2.4;

  camera.position.set(center.x + distance, center.y - distance * 1.1, center.z + distance * 0.75);
  camera.near = Math.max(distance / 100, 0.1);
  camera.far = distance * 100;
  camera.updateProjectionMatrix();
  orbit.target.copy(center);
  orbit.update();
  grid.position.z = box.min.z - 4;
}

function exportStl() {
  const exportObject = state.volumeGroup ?? state.mesh;
  if (!exportObject) return;

  const exporter = new STLExporter();
  const result = state.generatedStlBuffer ?? exporter.parse(exportObject, { binary: true });
  const blob = new Blob([result], { type: "application/octet-stream" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const metadata = state.volumeGroup?.userData?.metadata;
  const engineSuffix = metadata?.meshEngine === "implicit-union" ? "implicit" : "legacy";
  const seedCount = metadata?.seedCount ?? Math.round(getLatticeParams().cellCount);
  const sourceBase = metadata?.sourceFile?.originalName?.replace(/\.[^.]+$/, "");
  link.download = sourceBase ? `${sourceBase}_voronoi_implicit.stl` : `lattice_${seedCount}_${engineSuffix}.stl`;
  link.click();
  URL.revokeObjectURL(link.href);
  labels.status.textContent = "STL export hotový.";
}

function exportMetadata() {
  const metadata = state.volumeGroup?.userData?.metadata;
  if (!metadata) {
    labels.status.textContent = "Nejdřív vygeneruj Python lattice, aby vznikla metadata.";
    return;
  }

  const blob = new Blob([JSON.stringify(metadata, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const sourceBase = metadata.sourceFile?.originalName?.replace(/\.[^.]+$/, "");
  link.download = sourceBase
    ? `${sourceBase}_voronoi_metadata.json`
    : `lattice_${metadata.seedCount}_${metadata.meshEngine === "implicit-union" ? "implicit" : "legacy"}_metadata.json`;
  link.click();
  URL.revokeObjectURL(link.href);
  labels.status.textContent = "JSON metadata exportována.";
}

function exportDensityCsv() {
  if (!state.densityCsv) return;
  const blob = new Blob([state.densityCsv], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const sourceBase = state.volumeGroup?.userData?.metadata?.sourceFile?.originalName?.replace(/\.[^.]+$/, "") ?? "lattice";
  link.download = `${sourceBase}_density_solver.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function exportBatchAsset(assetName) {
  if (!state.batchAssets?.[assetName]) return;
  const link = document.createElement("a");
  link.href = state.batchAssets[assetName];
  link.download = "";
  link.click();
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return "-";
  const units = ["B", "KiB", "MiB", "GiB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function resize() {
  const { width, height } = viewport.getBoundingClientRect();
  if (!width || !height) return;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
}

function animate() {
  requestAnimationFrame(animate);
  orbit.update();
  renderer.render(scene, camera);
}
