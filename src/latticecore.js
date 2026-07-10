import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { STLExporter } from "three/addons/exporters/STLExporter.js";

const viewport = document.querySelector("#viewport");
const fileInput = document.querySelector("#stl-input");
const fileDrop = document.querySelector(".file-drop");
const sampleCubeButton = document.querySelector("#sample-cube");
const sampleCylinderButton = document.querySelector("#sample-cylinder");
const previewButton = document.querySelector("#preview");
const resetButton = document.querySelector("#reset");
const exportButton = document.querySelector("#export");
const patternSelect = document.querySelector("#pattern");
const modeButtons = [...document.querySelectorAll("[data-mode]")];

const controlsConfig = {
  cellSize: document.querySelector("#cell-size"),
  depth: document.querySelector("#depth"),
  wall: document.querySelector("#wall"),
  density: document.querySelector("#density"),
  smooth: document.querySelector("#smooth"),
};

const labels = {
  cellSize: document.querySelector("#cell-size-value"),
  depth: document.querySelector("#depth-value"),
  wall: document.querySelector("#wall-value"),
  density: document.querySelector("#density-value"),
  smooth: document.querySelector("#smooth-value"),
  triangles: document.querySelector("#triangles"),
  dimensions: document.querySelector("#dimensions"),
  exportState: document.querySelector("#export-state"),
  status: document.querySelector("#status"),
  mode: document.querySelector("#mode-label"),
  pattern: document.querySelector("#pattern-label"),
  warning: document.querySelector("#warning-text"),
};

const state = {
  mode: "volume",
  geometry: null,
  originalGeometry: null,
  mesh: null,
  volumeGroup: null,
  previewTimer: null,
  generatorEnabled: true,
};

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
camera.position.set(85, 72, 92);

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
grid.position.y = -24;
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

init();

function init() {
  bindEvents();
  const initialOptions = getInitialOptions();
  state.mode = initialOptions.mode;
  syncModeButtons();
  updateLabels();
  if (initialOptions.sample === "cylinder") {
    loadSampleCylinder();
  } else {
    loadSampleCube();
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
    if (file && file.name.toLowerCase().endsWith(".stl")) loadStlFile(file);
  });

  sampleCubeButton.addEventListener("click", loadSampleCube);
  sampleCylinderButton.addEventListener("click", loadSampleCylinder);
  previewButton.addEventListener("click", applyStructure);
  resetButton.addEventListener("click", resetGeometry);
  exportButton.addEventListener("click", exportStl);

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

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.mode;
      syncModeButtons();
      updateLabels();
      applyStructure();
    });
  });
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

function loadSampleCube() {
  const geometry = new THREE.BoxGeometry(40, 40, 40, 72, 72, 72);
  geometry.userData.latticeShape = "box";
  setGeometry(geometry, "Ukázková kostka je připravená.");
}

function loadSampleCylinder() {
  const geometry = new THREE.CylinderGeometry(16, 16, 46, 72, 18, false);
  geometry.userData.latticeShape = "cylinder";
  setGeometry(geometry, "Ukázkový válec je připravený.");
}

function loadStlFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const loader = new STLLoader();
      const geometry = loader.parse(reader.result);
      geometry.userData.latticeShape = "mesh";
      geometry.computeVertexNormals();
      setGeometry(geometry, `Načteno: ${file.name}`);
    } catch (error) {
      console.error(error);
      labels.status.textContent = "STL se nepodařilo načíst. Zkus jiný soubor.";
    }
  };
  reader.readAsArrayBuffer(file);
}

function setGeometry(geometry, message) {
  geometry = geometry.toNonIndexed();
  geometry.center();
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();

  state.originalGeometry = geometry.clone();
  state.geometry = geometry.clone();

  if (state.mesh) scene.remove(state.mesh);
  disposeVolumeGroup();

  state.mesh = new THREE.Mesh(state.geometry, surfaceMaterial);
  scene.add(state.mesh);
  fitCameraToGeometry(state.geometry);
  applyStructure();
  labels.status.textContent = message;
}

function resetGeometry() {
  if (!state.originalGeometry || !state.mesh) return;
  state.geometry.dispose();
  state.geometry = state.originalGeometry.clone();
  state.mesh.geometry = state.geometry;
  state.mesh.visible = true;
  disposeVolumeGroup();
  updateStats();
  labels.status.textContent = "Model vrácen do původního stavu.";
}

function scheduleStructurePreview() {
  if (!state.originalGeometry) return;
  window.clearTimeout(state.previewTimer);
  labels.status.textContent = "Čekám na dokončení úprav parametrů...";
  state.previewTimer = window.setTimeout(() => {
    state.previewTimer = null;
    applyStructure();
  }, 180);
}

function applySafeStructure() {
  if (!state.originalGeometry || !state.mesh) return;
  window.clearTimeout(state.previewTimer);
  state.previewTimer = null;

  state.geometry.dispose();
  state.geometry = state.originalGeometry.clone();
  state.geometry.computeVertexNormals();
  state.geometry.computeBoundingBox();
  state.mesh.geometry = state.geometry;
  state.mesh.visible = true;
  disposeVolumeGroup();

  labels.warning.textContent =
    state.mode === "surface"
      ? "Plošný generátor je pozastavený. Další krok musí být skutečná povrchová Voronoi síť, ne deformace STL vrcholů."
      : "Objemový generátor je pozastavený. Správný postup je povrchová Voronoi síť a potom vnitřní Voronoi výplň oříznutá tvarem STL.";
  labels.status.textContent = "Model zobrazen bez nevalidní lattice úpravy.";
  updateStats();
}

async function applyStructure() {
  if (!state.originalGeometry || !state.mesh) return;
  window.clearTimeout(state.previewTimer);
  state.previewTimer = null;
  labels.status.textContent = "Přepočítávám náhled...";

  state.geometry.dispose();
  state.geometry = state.originalGeometry.clone();
  labels.warning.textContent =
    state.mode === "surface"
      ? "Povrchový režim vytváří samostatnou Voronoi/lattice síť nad skutečným povrchem modelu."
      : "Objemový režim kombinuje povrchovou Voronoi síť a rychlý tvarový odhad vnitřní lattice výplně.";

  state.geometry.computeVertexNormals();
  state.geometry.computeBoundingBox();
  if (state.mode === "surface") {
    state.mesh.visible = true;
    disposeVolumeGroup();
    state.volumeGroup = createSurfaceLattice(state.originalGeometry);
    scene.add(state.volumeGroup);
    labels.warning.textContent =
      "Plošný režim je teď Voronoi-only: ze seed bodů na povrchu vzniká samostatná síť, původní STL zůstává jen reference.";
  } else {
    state.mesh.visible = true;
    disposeVolumeGroup();
    state.volumeGroup = await createVolumeLattice(state.originalGeometry);
    scene.add(state.volumeGroup);
    labels.warning.textContent =
      "Objemový režim kombinuje povrchovou Voronoi síť a vnitřní seed síť ořezanou tvarem modelu.";
  }

  state.geometry.computeVertexNormals();
  state.geometry.computeBoundingBox();
  state.mesh.geometry = state.geometry;
  updateStats();
  labels.warning.textContent = formatOptimizationSummary(state.volumeGroup?.userData.optimization);
  labels.status.textContent = "Náhled přepočítán.";
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
  const rawSamples = sampleSurfacePoints(sourceGeometry, getSurfaceLatticeCount(), params.surfaceOffset + radius * 0.35);
  const samples = mergeCloseSamples(rawSamples, getNodeMergeDistance(bbox, radius));
  const rawEdges = createSurfaceEdges(samples, bbox);
  const edges = filterIndexedEdgesByLength(rawEdges, samples.map((sample) => sample.position), getMinimumStrutLength(bbox, radius));
  group.userData.optimization = {
    rawNodes: rawSamples.length,
    nodes: samples.length,
    removedNodes: rawSamples.length - samples.length,
    rawEdges: rawEdges.length,
    edges: edges.length,
    removedEdges: rawEdges.length - edges.length,
  };

  for (const [aIndex, bIndex] of edges) {
    addTube(group, samples[aIndex].position, samples[bIndex].position, radius);
  }

  const nodeGeometry = new THREE.SphereGeometry(radius * 1.1, 10, 8);
  for (const sample of samples) {
    const node = new THREE.Mesh(nodeGeometry, latticeMaterial);
    node.position.copy(sample.position);
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
    cellCount: Number(controlsConfig.cellSize.value),
    surfaceOffset: Number(controlsConfig.depth.value),
    strutDiameter: Number(controlsConfig.wall.value),
    edgeReach: Number(controlsConfig.density.value),
    randomness: Number(controlsConfig.smooth.value),
  };
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
  if (sourceGeometry.userData?.latticeShape === "box") {
    try {
      return await createPythonVolumeLattice(sourceGeometry);
    } catch (error) {
      console.error(error);
      labels.warning.textContent = "Python generator selhal, zobrazuji starsi JS nahled.";
    }
  }

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

  for (const [aIndex, bIndex] of edges) {
    addTube(group, points[aIndex], points[bIndex], radius);
  }

  const nodeGeometry = new THREE.SphereGeometry(radius * 1.16, 10, 8);
  for (const point of points) {
    const node = new THREE.Mesh(nodeGeometry, latticeMaterial);
    node.position.copy(point);
    group.add(node);
  }

  return group;
}

async function createPythonVolumeLattice(sourceGeometry) {
  const bbox = sourceGeometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(sourceGeometry.attributes.position);
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  const params = getLatticeParams();
  const radius = maxAxis * 0.5;
  const query = new URLSearchParams({
    points: String(Math.round(params.cellCount)),
    radius: String(radius),
    tubeRadius: String(Math.max(params.strutDiameter * 0.5, maxAxis * 0.0045)),
    seed: String(Math.round(42 + params.randomness * 1000 + params.edgeReach * 31)),
  });

  labels.status.textContent = "Python generuje Voronoi STL...";
  const response = await fetch(`/api/python-lattice?${query.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message);
  }

  const buffer = await response.arrayBuffer();
  const geometry = new STLLoader().parse(buffer);
  geometry.center();
  geometry.computeVertexNormals();

  const mesh = new THREE.Mesh(geometry, latticeMaterial);
  const group = new THREE.Group();
  group.name = "LatticeCore Python volume lattice";
  group.add(mesh);
  group.userData.optimization = {
    pythonGenerator: true,
    removedNodes: 0,
    removedEdges: 0,
  };
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
  const insideTester = createInsideTester(sourceGeometry);

  let attempts = 0;
  const maxAttempts = targetCount * 18;
  while (points.length < targetCount && attempts < maxAttempts) {
    attempts += 1;
    const point = new THREE.Vector3(
      THREE.MathUtils.lerp(bbox.min.x, bbox.max.x, random()),
      THREE.MathUtils.lerp(bbox.min.y, bbox.max.y, random()),
      THREE.MathUtils.lerp(bbox.min.z, bbox.max.z, random())
    );
    if (insideTester(point)) points.push(point);
  }

  if (points.length < 6) {
    points.push(center.clone());
  }

  return points;
}

function createInsideTester(sourceGeometry) {
  const bbox = sourceGeometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(sourceGeometry.attributes.position);
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  bbox.getSize(size);
  bbox.getCenter(center);

  const axes = [
    { name: "x", size: size.x },
    { name: "y", size: size.y },
    { name: "z", size: size.z },
  ].sort((left, right) => right.size - left.size);

  const longest = axes[0];
  const mid = axes[1];
  const shortest = axes[2];
  const shape = sourceGeometry.userData?.latticeShape;
  const looksCylindrical =
    shape === "cylinder" || (longest.size > mid.size * 1.22 && mid.size / Math.max(shortest.size, 0.0001) < 1.28);

  if (!looksCylindrical) {
    return (point) => bbox.containsPoint(point);
  }

  return (point) => {
    const local = point.clone().sub(center);
    const axial = Math.abs(local[longest.name]) / (longest.size * 0.5);
    const radialA = local[mid.name] / (mid.size * 0.5);
    const radialB = local[shortest.name] / (shortest.size * 0.5);
    return axial <= 1 && radialA * radialA + radialB * radialB <= 1;
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
      midpoint.addVectors(points[a], points[item.index]).multiplyScalar(0.5);
      if (insideTester && !insideTester(midpoint)) continue;

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

function addTube(group, start, end, radius) {
  const direction = new THREE.Vector3().subVectors(end, start);
  const length = direction.length();
  if (length < 0.001) return;

  const geometry = new THREE.CylinderGeometry(radius, radius, length, 10, 1, false);
  const tube = new THREE.Mesh(geometry, latticeMaterial);
  const midpoint = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
  const quaternion = new THREE.Quaternion().setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    direction.clone().normalize()
  );

  tube.position.copy(midpoint);
  tube.quaternion.copy(quaternion);
  group.add(tube);
}

function disposeVolumeGroup() {
  if (!state.volumeGroup) return;
  scene.remove(state.volumeGroup);
  state.volumeGroup.traverse((object) => {
    if (object.geometry) object.geometry.dispose();
  });
  state.volumeGroup = null;
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
  labels.cellSize.textContent = params.cellCount.toFixed(0);
  labels.depth.textContent = `${params.surfaceOffset.toFixed(1)} mm`;
  labels.wall.textContent = `${params.strutDiameter.toFixed(2)} mm`;
  labels.density.textContent = params.edgeReach.toFixed(1);
  labels.smooth.textContent = params.randomness.toFixed(2);
  labels.mode.textContent = state.mode === "surface" ? "Plošný režim" : "Objemový lattice";
  labels.pattern.textContent = patternSelect.options[patternSelect.selectedIndex].text;
}

function updateStats() {
  const object = state.volumeGroup ?? state.mesh;
  if (!object) return;

  const box = new THREE.Box3().setFromObject(object);
  const size = new THREE.Vector3();
  box.getSize(size);

  labels.triangles.textContent = countTriangles(object).toLocaleString("cs-CZ");
  labels.dimensions.textContent = `${size.x.toFixed(1)} x ${size.y.toFixed(1)} x ${size.z.toFixed(1)} mm`;
  labels.exportState.textContent = state.generatorEnabled
    ? state.mode === "surface"
      ? "Povrchová síť STL"
      : "Lattice STL"
    : "Pozastaveno";
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

  camera.position.set(center.x + distance, center.y + distance * 0.8, center.z + distance);
  camera.near = Math.max(distance / 100, 0.1);
  camera.far = distance * 100;
  camera.updateProjectionMatrix();
  orbit.target.copy(center);
  orbit.update();
  grid.position.y = box.min.y - 4;
}

function exportStl() {
  if (!state.generatorEnabled) {
    labels.status.textContent = "Export lattice je pozastavený, aby nevznikaly chybné STL soubory.";
    return;
  }

  const exportObject = state.volumeGroup ?? state.mesh;
  if (!exportObject) return;

  const exporter = new STLExporter();
  const result = exporter.parse(exportObject, { binary: false });
  const blob = new Blob([result], { type: "model/stl" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `latticecore-${patternSelect.value}-${state.mode}.stl`;
  link.click();
  URL.revokeObjectURL(link.href);
  labels.status.textContent = "STL export hotový.";
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
