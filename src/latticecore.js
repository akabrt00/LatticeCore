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
  volumeGroup: null,
  seedPoints: [],
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
});

const latticeMaterial = new THREE.MeshStandardMaterial({
  color: 0x2b2722,
  metalness: 0.15,
  roughness: 0.46,
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
  const geometry = new THREE.BoxGeometry(40, 40, 40, 72, 72, 72);
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

function applyStructure() {
  if (!state.originalGeometry || !state.mesh) return;

  state.geometry.dispose();
  state.geometry = state.originalGeometry.clone();
  state.geometry.computeVertexNormals();
  state.geometry.computeBoundingBox();
  state.seedPoints = createSeedPoints(getSurfaceSeedCount(), getSeedSalt());

  if (state.mode === "surface") {
    state.mesh.visible = true;
    disposeVolumeGroup();
    deformSurface(state.geometry);
    labels.warning.textContent =
      "Povrchový režim vytváří reliéf na plášti modelu. Hustota a velikost buněk teď mění samotnou síť vzoru.";
  } else {
    state.mesh.visible = false;
    disposeVolumeGroup();
    state.volumeGroup = createVolumeLattice(state.originalGeometry);
    scene.add(state.volumeGroup);
    labels.warning.textContent =
      "Objemový režim generuje trubičkovou lattice kostru podle referenční kostky. Pro obecné STL je to zatím bounding-box prototyp.";
  }

  state.geometry.computeVertexNormals();
  state.geometry.computeBoundingBox();
  state.mesh.geometry = state.geometry;
  updateStats();
  labels.status.textContent = "Náhled přepočítán.";
}

function deformSurface(geometry) {
  const positions = geometry.attributes.position;
  const normals = geometry.attributes.normal;
  const pattern = patternSelect.value;
  const bbox = geometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(positions);
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxAxis = Math.max(size.x, size.y, size.z) || 1;

  const depth = Number(controlsConfig.depth.value);
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

  const ridgeWidth = 16 + wall * 15 + (42 - cellSize) * 0.22;
  const ridge = Math.exp(-Math.abs(Math.sqrt(second) - Math.sqrt(nearest)) * ridgeWidth);
  const crisp = THREE.MathUtils.smoothstep(ridge, 0.18 + smooth * 0.12, 0.82);
  return crisp * 1.45 - 0.42;
}

function hexPattern(point, cellSize, wall) {
  const scale = 34 / Math.max(cellSize, 1);
  const q = (Math.sqrt(3) / 3 * point.x - 1 / 3 * point.z) * scale;
  const r = (2 / 3 * point.z) * scale;
  const gridX = Math.round(q);
  const gridY = Math.round(r);
  const distance = Math.hypot(q - gridX, r - gridY);
  return Math.exp(-distance * (5.6 + wall * 2.2)) * 1.35 - 0.36;
}

function gyroidPattern(point, cellSize, wall) {
  const scale = Math.PI * 2 / Math.max(cellSize, 1);
  const value =
    Math.sin(point.x * scale) * Math.cos(point.y * scale) +
    Math.sin(point.y * scale) * Math.cos(point.z * scale) +
    Math.sin(point.z * scale) * Math.cos(point.x * scale);
  return Math.exp(-Math.abs(value) * (2.3 + wall)) * 1.2 - 0.34;
}

function organicNoise(point, cellSize, smooth) {
  const scale = 0.12 + 0.62 / Math.max(cellSize, 1);
  const value =
    Math.sin(point.x * scale * 2.1 + point.y * scale) *
      Math.cos(point.z * scale * 1.7 - point.x * scale * 0.8) +
    Math.sin((point.x + point.y + point.z) * scale * 0.9);
  return THREE.MathUtils.smoothstep(value * 0.5 + 0.5, 0.18 + smooth * 0.2, 0.86) * 1.25 - 0.42;
}

function createVolumeLattice(sourceGeometry) {
  const group = new THREE.Group();
  group.name = "LatticeCore volume lattice";

  const bbox = sourceGeometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(sourceGeometry.attributes.position);
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  bbox.getSize(size);
  bbox.getCenter(center);

  const maxAxis = Math.max(size.x, size.y, size.z) || 1;
  const cellSize = Number(controlsConfig.cellSize.value);
  const wall = Number(controlsConfig.wall.value);
  const depth = Number(controlsConfig.depth.value);
  const density = Number(controlsConfig.density.value);
  const smooth = Number(controlsConfig.smooth.value);

  const radius = Math.max(maxAxis * 0.008, 0.22 + wall * 0.68 + depth * 0.08);
  const points = createVolumePoints(bbox, density, cellSize, smooth);
  const edges = createNearestEdges(points, maxAxis, cellSize, wall);

  addBoundingFrame(group, bbox, radius * 1.25);

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

function createNearestEdges(points, maxAxis, cellSize, wall) {
  const edges = [];
  const edgeKeys = new Set();
  const neighborCount = Math.round(3 + wall * 3.2);
  const maxDistance = maxAxis * THREE.MathUtils.clamp(0.32 + cellSize / 100, 0.36, 0.78);

  for (let a = 0; a < points.length; a += 1) {
    const nearest = points
      .map((point, index) => ({ index, distance: point.distanceTo(points[a]) }))
      .filter((item) => item.index !== a && item.distance <= maxDistance)
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

function createSeedPoints(count, salt = 0) {
  const points = [];
  const random = mulberry32(1337 + count * 17 + salt);
  for (let index = 0; index < count; index += 1) {
    points.push(new THREE.Vector3(random(), random(), random()));
  }
  return points;
}

function getSurfaceSeedCount() {
  const density = Number(controlsConfig.density.value);
  const cellSize = Number(controlsConfig.cellSize.value);
  const count = Math.round(density * THREE.MathUtils.clamp(32 / cellSize, 0.8, 4.5));
  return THREE.MathUtils.clamp(count, 12, 180);
}

function getSeedSalt() {
  return Math.round(
    Number(controlsConfig.cellSize.value) * 19 +
      Number(controlsConfig.density.value) * 23 +
      Number(controlsConfig.wall.value) * 100
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
  labels.cellSize.textContent = controlsConfig.cellSize.value;
  labels.depth.textContent = `${Number(controlsConfig.depth.value).toFixed(1)} mm`;
  labels.wall.textContent = Number(controlsConfig.wall.value).toFixed(2);
  labels.density.textContent = controlsConfig.density.value;
  labels.smooth.textContent = Number(controlsConfig.smooth.value).toFixed(2);
  labels.mode.textContent = state.mode === "surface" ? "Plošný režim" : "Objemový lattice";
  labels.pattern.textContent = patternSelect.options[patternSelect.selectedIndex].text;
}

function updateStats() {
  const object = state.mode === "volume" && state.volumeGroup ? state.volumeGroup : state.mesh;
  if (!object) return;

  const box = new THREE.Box3().setFromObject(object);
  const size = new THREE.Vector3();
  box.getSize(size);

  labels.triangles.textContent = countTriangles(object).toLocaleString("cs-CZ");
  labels.dimensions.textContent = `${size.x.toFixed(1)} x ${size.y.toFixed(1)} x ${size.z.toFixed(1)} mm`;
  labels.exportState.textContent = state.mode === "surface" ? "Povrch STL" : "Lattice STL";
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
  const exportObject = state.mode === "volume" && state.volumeGroup ? state.volumeGroup : state.mesh;
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
