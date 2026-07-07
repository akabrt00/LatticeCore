import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { STLExporter } from "three/addons/exporters/STLExporter.js";

const viewport = document.querySelector("#viewport");
const fileInput = document.querySelector("#stl-input");
const fileDrop = document.querySelector(".file-drop");
const sampleCubeButton = document.querySelector("#sample-cube");
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
  mode: "surface",
  geometry: null,
  originalGeometry: null,
  mesh: null,
  helper: null,
  seedPoints: [],
};

const scene = new THREE.Scene();
scene.background = null;

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
camera.position.set(85, 72, 92);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
viewport.appendChild(renderer.domElement);

const orbit = new OrbitControls(camera, renderer.domElement);
orbit.enableDamping = true;
orbit.dampingFactor = 0.06;

const hemi = new THREE.HemisphereLight(0xffffff, 0x26313a, 2.3);
scene.add(hemi);

const key = new THREE.DirectionalLight(0xffffff, 2.2);
key.position.set(90, 120, 80);
scene.add(key);

const fill = new THREE.DirectionalLight(0x72fff0, 0.9);
fill.position.set(-90, 40, -80);
scene.add(fill);

const grid = new THREE.GridHelper(140, 28, 0x3a4550, 0x232b33);
grid.position.y = -24;
scene.add(grid);

const material = new THREE.MeshStandardMaterial({
  color: 0xd9e3e8,
  metalness: 0.05,
  roughness: 0.54,
  flatShading: false,
});

const edgeMaterial = new THREE.LineBasicMaterial({
  color: 0x50d6c6,
  transparent: true,
  opacity: 0.38,
});

init();

function init() {
  bindEvents();
  loadSampleCube();
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
  previewButton.addEventListener("click", applyStructure);
  resetButton.addEventListener("click", resetGeometry);
  exportButton.addEventListener("click", exportStl);

  patternSelect.addEventListener("change", () => {
    updateLabels();
    applyStructure();
  });

  Object.values(controlsConfig).forEach((input) => {
    input.addEventListener("input", () => {
      updateLabels();
      applyStructure();
    });
  });

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.mode;
      modeButtons.forEach((item) => item.classList.toggle("active", item === button));
      updateLabels();
      applyStructure();
    });
  });
}

function loadSampleCube() {
  const geometry = new THREE.BoxGeometry(40, 40, 40, 60, 60, 60);
  setGeometry(geometry, "Ukázková kostka je připravená.");
}

function loadStlFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const loader = new STLLoader();
      const geometry = loader.parse(reader.result);
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
  state.seedPoints = createSeedPoints(Number(controlsConfig.density.value));

  if (state.mesh) scene.remove(state.mesh);
  if (state.helper) scene.remove(state.helper);

  state.mesh = new THREE.Mesh(state.geometry, material);
  scene.add(state.mesh);
  fitCameraToGeometry(state.geometry);
  applyStructure();
  labels.status.textContent = message;
}

function resetGeometry() {
  if (!state.originalGeometry) return;
  state.geometry.dispose();
  state.geometry = state.originalGeometry.clone();
  state.mesh.geometry = state.geometry;
  removeHelper();
  updateStats();
  labels.status.textContent = "Model vrácen do původního stavu.";
}

function applyStructure() {
  if (!state.originalGeometry || !state.mesh) return;

  state.geometry.dispose();
  state.geometry = state.originalGeometry.clone();
  state.geometry.computeVertexNormals();

  if (state.mode === "surface") {
    deformSurface(state.geometry);
    removeHelper();
    labels.warning.textContent =
      "Povrchový režim upravuje vrcholy podél normál. Export STL je dostupný pro aktuální náhled.";
  } else {
    deformSurface(state.geometry, 0.35);
    showVolumePreview();
    labels.warning.textContent =
      "Objemový režim je zatím vizualizace vnitřní struktury. Skutečný export objemového lattice bude další fáze.";
  }

  state.geometry.computeVertexNormals();
  state.geometry.computeBoundingBox();
  state.mesh.geometry = state.geometry;
  updateStats();
  labels.status.textContent = "Náhled přepočítán.";
}

function deformSurface(geometry, multiplier = 1) {
  const positions = geometry.attributes.position;
  const normals = geometry.attributes.normal;
  const pattern = patternSelect.value;
  const bbox = geometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(positions);
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;

  const depth = Number(controlsConfig.depth.value) * multiplier;
  const cellSize = Number(controlsConfig.cellSize.value);
  const wall = Number(controlsConfig.wall.value);
  const smooth = Number(controlsConfig.smooth.value);

  const point = new THREE.Vector3();
  const normal = new THREE.Vector3();

  for (let index = 0; index < positions.count; index += 1) {
    point.fromBufferAttribute(positions, index);
    normal.fromBufferAttribute(normals, index).normalize();

    const value = patternValue(pattern, point, bbox, maxAxis, cellSize, wall, smooth);
    const displacement = depth * value;

    positions.setXYZ(
      index,
      point.x + normal.x * displacement,
      point.y + normal.y * displacement,
      point.z + normal.z * displacement
    );
  }

  positions.needsUpdate = true;
}

function patternValue(pattern, point, bbox, maxAxis, cellSize, wall, smooth) {
  if (pattern === "voronoi") return voronoiRidge(point, bbox, maxAxis, cellSize, wall, smooth);
  if (pattern === "hex") return hexPattern(point, cellSize, wall);
  if (pattern === "gyroid") return gyroidPattern(point, cellSize, wall);
  return organicNoise(point, cellSize, smooth);
}

function voronoiRidge(point, bbox, maxAxis, cellSize, wall, smooth) {
  const normalized = new THREE.Vector3(
    (point.x - bbox.min.x) / maxAxis,
    (point.y - bbox.min.y) / maxAxis,
    (point.z - bbox.min.z) / maxAxis
  );

  let nearest = Infinity;
  let second = Infinity;

  for (const seed of state.seedPoints) {
    const distance = normalized.distanceToSquared(seed);
    if (distance < nearest) {
      second = nearest;
      nearest = distance;
    } else if (distance < second) {
      second = distance;
    }
  }

  const ridge = Math.exp(-Math.abs(Math.sqrt(second) - Math.sqrt(nearest)) * cellSize * 5.5);
  const lifted = Math.pow(THREE.MathUtils.clamp(ridge * (1 + wall), 0, 1), 1 + smooth * 2);
  return lifted - 0.35;
}

function hexPattern(point, cellSize, wall) {
  const scale = 1 / Math.max(cellSize, 1);
  const q = (Math.sqrt(3) / 3 * point.x - 1 / 3 * point.z) * scale * 30;
  const r = (2 / 3 * point.z) * scale * 30;
  const gridX = Math.round(q);
  const gridY = Math.round(r);
  const distance = Math.hypot(q - gridX, r - gridY);
  return Math.exp(-distance * (7 - wall * 2)) - 0.28;
}

function gyroidPattern(point, cellSize, wall) {
  const scale = Math.PI * 2 / Math.max(cellSize, 1);
  const value =
    Math.sin(point.x * scale) * Math.cos(point.y * scale) +
    Math.sin(point.y * scale) * Math.cos(point.z * scale) +
    Math.sin(point.z * scale) * Math.cos(point.x * scale);
  return Math.exp(-Math.abs(value) * (2.8 - wall)) - 0.36;
}

function organicNoise(point, cellSize, smooth) {
  const scale = 0.08 + 0.45 / Math.max(cellSize, 1);
  const value =
    Math.sin(point.x * scale * 2.1 + point.y * scale) *
      Math.cos(point.z * scale * 1.7 - point.x * scale * 0.8) +
    Math.sin((point.x + point.y + point.z) * scale * 0.9);
  return THREE.MathUtils.smoothstep(value * 0.5 + 0.5, 0.2 + smooth * 0.2, 0.9) - 0.42;
}

function showVolumePreview() {
  removeHelper();
  const box = new THREE.Box3().setFromObject(state.mesh);
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);

  const density = Number(controlsConfig.density.value);
  const points = createSeedPoints(Math.floor(density * 0.65)).map((point) =>
    new THREE.Vector3(
      center.x + (point.x - 0.5) * size.x * 0.82,
      center.y + (point.y - 0.5) * size.y * 0.82,
      center.z + (point.z - 0.5) * size.z * 0.82
    )
  );

  const linePositions = [];
  for (let a = 0; a < points.length; a += 1) {
    const distances = points
      .map((point, index) => ({ index, distance: point.distanceToSquared(points[a]) }))
      .filter((item) => item.index !== a)
      .sort((left, right) => left.distance - right.distance)
      .slice(0, 3);

    for (const neighbor of distances) {
      const b = points[neighbor.index];
      linePositions.push(points[a].x, points[a].y, points[a].z, b.x, b.y, b.z);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(linePositions, 3));
  state.helper = new THREE.LineSegments(geometry, edgeMaterial);
  scene.add(state.helper);
}

function removeHelper() {
  if (!state.helper) return;
  scene.remove(state.helper);
  state.helper.geometry.dispose();
  state.helper = null;
}

function createSeedPoints(count) {
  const points = [];
  const random = mulberry32(1337 + count * 17);
  for (let index = 0; index < count; index += 1) {
    points.push(new THREE.Vector3(random(), random(), random()));
  }
  return points;
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
  labels.cellSize.textContent = controlsConfig.cellSize.value;
  labels.depth.textContent = `${Number(controlsConfig.depth.value).toFixed(1)} mm`;
  labels.wall.textContent = Number(controlsConfig.wall.value).toFixed(2);
  labels.density.textContent = controlsConfig.density.value;
  labels.smooth.textContent = Number(controlsConfig.smooth.value).toFixed(2);
  labels.mode.textContent = state.mode === "surface" ? "Plošný režim" : "Objemový náhled";
  labels.pattern.textContent = patternSelect.options[patternSelect.selectedIndex].text;
}

function updateStats() {
  if (!state.geometry) return;
  const box = state.geometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(state.geometry.attributes.position);
  const size = new THREE.Vector3();
  box.getSize(size);
  labels.triangles.textContent = Math.round(state.geometry.attributes.position.count / 3).toLocaleString("cs-CZ");
  labels.dimensions.textContent = `${size.x.toFixed(1)} x ${size.y.toFixed(1)} x ${size.z.toFixed(1)} mm`;
  labels.exportState.textContent = state.mode === "surface" ? "STL export" : "Export jen povrch";
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
  if (!state.mesh) return;
  const exporter = new STLExporter();
  const result = exporter.parse(state.mesh, { binary: false });
  const blob = new Blob([result], { type: "model/stl" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `stl-structure-${patternSelect.value}-${state.mode}.stl`;
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
