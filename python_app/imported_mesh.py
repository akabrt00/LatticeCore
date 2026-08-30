from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import numpy as np
import pyvista as pv
from vtkmodules.vtkCommonCore import reference
from vtkmodules.vtkCommonDataModel import vtkGenericCell, vtkStaticCellLocator

from implicit_meshing import GeometryDomain


SUPPORTED_MESH_FORMATS = {".stl": "stl", ".obj": "obj"}
MAX_INPUT_FILE_BYTES = 100 * 1024 * 1024


def _triangles(mesh: pv.PolyData) -> np.ndarray:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if not len(faces):
        return np.empty((0, 3), dtype=np.int64)
    shaped = faces.reshape(-1, 4)
    if np.any(shaped[:, 0] != 3):
        raise ValueError("Mesh cleanup did not produce a triangular surface.")
    return shaped[:, 1:]


def _edge_statistics(faces: np.ndarray) -> tuple[int, int]:
    if not len(faces):
        return 0, 0
    edges = np.sort(
        np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])),
        axis=1,
    )
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int(np.count_nonzero(counts == 1)), int(np.count_nonzero(counts > 2))


def validate_surface_mesh(mesh: pv.PolyData, cleanup_applied: bool = False, orientation_repaired: bool = False) -> dict:
    faces = _triangles(mesh)
    points = np.asarray(mesh.points, dtype=float)
    if len(faces):
        first, second, third = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
        doubled_area = np.linalg.norm(np.cross(second - first, third - first), axis=1)
        degenerates = int(np.count_nonzero(doubled_area <= 1e-12))
        canonical = np.sort(faces, axis=1)
        duplicate_count = int(len(canonical) - len(np.unique(canonical, axis=0)))
    else:
        degenerates = duplicate_count = 0
    boundary_edges, non_manifold_edges = _edge_statistics(faces)
    connected = mesh.connectivity() if mesh.n_cells else mesh
    component_count = (
        int(len(np.unique(connected.cell_data["RegionId"])))
        if mesh.n_cells and "RegionId" in connected.cell_data
        else int(mesh.n_cells > 0)
    )
    bounds = np.asarray(mesh.bounds, dtype=float) if mesh.n_points else np.zeros(6)
    size = np.asarray([bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]])
    signed_volume = float(mesh.volume) if mesh.n_cells else 0.0
    return {
        "vertexCount": int(mesh.n_points),
        "triangleCount": int(mesh.n_cells),
        "bounds": {
            "min": [float(bounds[0]), float(bounds[2]), float(bounds[4])],
            "max": [float(bounds[1]), float(bounds[3]), float(bounds[5])],
        },
        "sizeMm": {"x": float(size[0]), "y": float(size[1]), "z": float(size[2])},
        "surfaceAreaMm2": float(mesh.area),
        "signedVolumeMm3": signed_volume,
        "absoluteVolumeMm3": abs(signed_volume),
        "boundaryEdgeCount": boundary_edges,
        "nonManifoldEdgeCount": non_manifold_edges,
        "degenerateTriangleCount": degenerates,
        "duplicateTriangleCount": duplicate_count,
        "connectedComponentCount": component_count,
        "isWatertight": boundary_edges == 0,
        "isEdgeManifold": non_manifold_edges == 0,
        "normalsConsistent": True,
        "orientationWasRepaired": bool(orientation_repaired),
        "cleanupWasApplied": bool(cleanup_applied),
    }


def clean_triangle_mesh(mesh: pv.DataSet, import_scale: float = 1.0) -> tuple[pv.PolyData, dict]:
    if not np.isfinite(import_scale) or import_scale <= 0:
        raise ValueError("Import scale must be a finite positive number.")
    surface = mesh.extract_surface(algorithm="dataset_surface").triangulate()
    if surface.n_points == 0 or surface.n_cells == 0:
        raise ValueError("The imported mesh is empty.")
    points = np.asarray(surface.points, dtype=float) * float(import_scale)
    faces = _triangles(surface)
    finite_vertices = np.all(np.isfinite(points), axis=1)
    valid_faces = np.all(finite_vertices[faces], axis=1)
    faces = faces[valid_faces]
    if not len(faces):
        raise ValueError("The imported mesh has no finite triangles.")
    first, second, third = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    faces = faces[np.linalg.norm(np.cross(second - first, third - first), axis=1) > 1e-12]
    canonical = np.sort(faces, axis=1)
    _, unique_indices = np.unique(canonical, axis=0, return_index=True)
    faces = faces[np.sort(unique_indices)]
    face_data = np.column_stack((np.full(len(faces), 3, dtype=np.int64), faces)).ravel()
    cleaned = pv.PolyData(points, face_data).clean(point_merging=True, tolerance=1e-7, absolute=True)
    cleaned = cleaned.extract_surface(algorithm="dataset_surface").triangulate().clean()
    before_volume = float(cleaned.volume)
    cleaned = cleaned.compute_normals(
        cell_normals=True,
        point_normals=True,
        consistent_normals=True,
        auto_orient_normals=True,
        non_manifold_traversal=False,
        inplace=False,
    )
    orientation_repaired = before_volume < 0
    validation = validate_surface_mesh(cleaned, cleanup_applied=True, orientation_repaired=orientation_repaired)
    return cleaned, validation


def load_triangle_mesh(path: str | Path, import_scale: float = 1.0) -> tuple[pv.PolyData, dict]:
    source = Path(path)
    detected_format = SUPPORTED_MESH_FORMATS.get(source.suffix.lower())
    if detected_format is None:
        raise ValueError("Unsupported input format. Use STL or OBJ.")
    file_size = source.stat().st_size
    if file_size > MAX_INPUT_FILE_BYTES:
        raise ValueError("Input file exceeds the 100 MiB safety limit.")
    started = perf_counter()
    try:
        loaded = pv.read(source)
    except Exception as exc:
        raise ValueError(f"The {detected_format.upper()} file cannot be read: {exc}") from exc
    mesh, validation = clean_triangle_mesh(loaded, import_scale)
    validation["loadAndCleanupTimeSeconds"] = float(perf_counter() - started)
    validation["detectedFormat"] = detected_format
    validation["fileSizeBytes"] = int(file_size)
    return mesh, validation


def _component_meshes(mesh: pv.PolyData) -> list[pv.PolyData]:
    connected = mesh.connectivity()
    ids = np.unique(connected.cell_data["RegionId"])
    return [
        connected.threshold([int(region), int(region)], scalars="RegionId").extract_surface(
            algorithm="dataset_surface"
        ).triangulate().clean()
        for region in ids
    ]


def apply_component_mode(mesh: pv.PolyData, mode: str) -> tuple[pv.PolyData, int]:
    components = _component_meshes(mesh)
    if len(components) <= 1:
        return mesh, 0
    if mode == "require-single":
        raise ValueError(f"The imported model has {len(components)} components; require-single accepts exactly one.")
    if mode == "keep-largest":
        largest = max(components, key=lambda item: abs(float(item.volume)))
        return largest, len(components) - 1
    if mode == "use-all-closed":
        for component in components:
            validation = validate_surface_mesh(component)
            if not validation["isWatertight"] or not validation["isEdgeManifold"]:
                raise ValueError("Every component must be closed and edge-manifold for use-all-closed.")
        return mesh, 0
    raise ValueError(f"Unknown component mode: {mode}")


class TriangleMeshDomain(GeometryDomain):
    """Closed triangular surface domain backed by VTK spatial queries."""

    def __init__(self, mesh: pv.PolyData, component_mode: str = "use-all-closed", validation: dict | None = None):
        selected, removed = apply_component_mode(mesh, component_mode)
        self.mesh = selected.compute_normals(
            cell_normals=True,
            point_normals=True,
            consistent_normals=True,
            auto_orient_normals=True,
            non_manifold_traversal=False,
            inplace=False,
        )
        self.component_mode = component_mode
        self.removed_component_count = removed
        self._validation = validate_surface_mesh(self.mesh, cleanup_applied=validation is not None)
        if not self._validation["isWatertight"]:
            raise ValueError(
                f"The imported model is open ({self._validation['boundaryEdgeCount']} boundary edges); "
                "its interior volume is ambiguous."
            )
        if not self._validation["isEdgeManifold"]:
            raise ValueError(
                f"The imported model is non-manifold ({self._validation['nonManifoldEdgeCount']} non-manifold edges)."
            )
        if self._validation["absoluteVolumeMm3"] <= 1e-9:
            raise ValueError("The imported model has zero enclosed volume.")
        self._cell_locator = vtkStaticCellLocator()
        self._cell_locator.SetDataSet(self.mesh)
        self._cell_locator.BuildLocator()
        self._sign_multiplier, self._sign_agreement = self._calibrate_sign()
        if self._sign_agreement < 0.9:
            raise ValueError("The mesh signed-distance sign is inconsistent with its enclosed volume.")

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        bounds = np.asarray(self.mesh.bounds, dtype=float)
        return np.asarray([bounds[0], bounds[2], bounds[4]]), np.asarray([bounds[1], bounds[3], bounds[5]])

    def _raw_signed_distance(self, points: np.ndarray, chunk_size: int = 250_000) -> np.ndarray:
        samples = np.atleast_2d(np.asarray(points, dtype=float))
        result = np.empty(len(samples), dtype=float)
        for start in range(0, len(samples), chunk_size):
            stop = min(start + chunk_size, len(samples))
            cloud = pv.PolyData(samples[start:stop])
            distances = cloud.compute_implicit_distance(self.mesh, inplace=False)["implicit_distance"]
            result[start:stop] = np.asarray(distances, dtype=float)
        return result

    def _enclosed_mask(self, points: np.ndarray) -> np.ndarray:
        samples = np.atleast_2d(np.asarray(points, dtype=float))
        selected = pv.PolyData(samples).select_interior_points(
            self.mesh,
            method="cell_locator",
            locator_tolerance=1e-7,
            check_surface=False,
        )
        return np.asarray(selected.point_data["selected_points"], dtype=bool)

    def _calibrate_sign(self) -> tuple[float, float]:
        minimum, maximum = self.bounds()
        extent = maximum - minimum
        rng = np.random.default_rng(1729)
        candidates = rng.uniform(minimum, maximum, size=(96, 3))
        outside = np.asarray([minimum - extent, maximum + extent])
        samples = np.vstack((candidates, outside))
        inside = self._enclosed_mask(samples)
        raw = self._raw_signed_distance(samples)
        usable = np.abs(raw) > max(float(np.max(extent)) * 1e-8, 1e-8)
        expected_negative = inside[usable]
        negative_agreement = float(np.mean((raw[usable] < 0) == expected_negative))
        positive_agreement = float(np.mean((-raw[usable] < 0) == expected_negative))
        return (1.0, negative_agreement) if negative_agreement >= positive_agreement else (-1.0, positive_agreement)

    def signed_distance(self, points: np.ndarray) -> np.ndarray:
        original = np.asarray(points, dtype=float)
        result = self._raw_signed_distance(original) * self._sign_multiplier
        return result.reshape(original.shape[:-1])

    def contains(self, points: np.ndarray, tolerance: float = 0.0) -> np.ndarray:
        if tolerance == 0:
            return self._enclosed_mask(points)
        return self.signed_distance(points) <= tolerance

    def closest_points(self, points: np.ndarray) -> np.ndarray:
        samples = np.atleast_2d(np.asarray(points, dtype=float))
        result = np.empty_like(samples)
        generic_cell = vtkGenericCell()
        for index, point in enumerate(samples):
            closest = [0.0, 0.0, 0.0]
            cell_id, sub_id, squared_distance = reference(0), reference(0), reference(0.0)
            self._cell_locator.FindClosestPoint(
                point,
                closest,
                generic_cell,
                cell_id,
                sub_id,
                squared_distance,
            )
            result[index] = closest
        return result

    def validate(self) -> dict:
        return {**self._validation, "sdfSignAgreement": self._sign_agreement}

    def metadata(self) -> dict:
        return {
            "domainType": "triangle-mesh",
            "componentMode": self.component_mode,
            "removedComponentCount": self.removed_component_count,
            "signedDistanceImplementation": "vtkImplicitPolyDataDistance",
            "insideTestImplementation": "vtkSelectEnclosedPoints",
            "spatialLocator": "vtkStaticCellLocator (PyVista find_closest_cell)",
            "sdfSignMultiplier": self._sign_multiplier,
            "sdfSignAgreement": self._sign_agreement,
        }


@dataclass(frozen=True)
class SeedSamplingResult:
    points: np.ndarray
    metadata: dict


def generate_points_in_domain(
    domain: GeometryDomain,
    count: int,
    random_seed: int,
    boundary_offset_mm: float = 0.0,
    maximum_sampling_attempts: int = 1_000_000,
    fallback_ratio: float = 0.02,
    cancellation_token=None,
) -> SeedSamplingResult:
    if count < 5:
        raise ValueError("At least five seed points are required for a 3D Voronoi diagram.")
    if boundary_offset_mm < 0:
        raise ValueError("Boundary offset cannot be negative.")
    started = perf_counter()
    rng = np.random.default_rng(random_seed)
    minimum, maximum = domain.bounds()
    accepted: list[np.ndarray] = []
    candidate_count = 0
    batch_size = max(256, count * 4)
    method = "bounding-box-rejection"
    fallback_threshold = min(maximum_sampling_attempts, max(2_000, count * 20))
    while len(accepted) < count and candidate_count < maximum_sampling_attempts:
        if cancellation_token is not None:
            cancellation_token.check()
        batch = min(batch_size, maximum_sampling_attempts - candidate_count)
        candidates = rng.uniform(minimum, maximum, size=(batch, 3))
        mask = domain.signed_distance(candidates) <= -boundary_offset_mm
        accepted.extend(candidates[mask])
        candidate_count += batch
        ratio = len(accepted) / candidate_count
        if candidate_count >= fallback_threshold and ratio < fallback_ratio and len(accepted) < count:
            method = "interior-voxel-assisted"
            break

    if method == "interior-voxel-assisted" and len(accepted) < count:
        dimensions = np.full(3, 24, dtype=int)
        axes = [minimum[i] + (np.arange(dimensions[i]) + 0.5) * (maximum[i] - minimum[i]) / dimensions[i] for i in range(3)]
        xx, yy, zz = np.meshgrid(*axes, indexing="ij")
        centers = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))
        interior_centers = centers[domain.signed_distance(centers) <= -boundary_offset_mm]
        if not len(interior_centers):
            raise ValueError("No interior sampling cells remain; reduce boundaryOffsetMm.")
        cell_size = (maximum - minimum) / dimensions
        while len(accepted) < count and candidate_count < maximum_sampling_attempts:
            if cancellation_token is not None:
                cancellation_token.check()
            batch = min(batch_size, maximum_sampling_attempts - candidate_count)
            chosen = interior_centers[rng.integers(0, len(interior_centers), size=batch)]
            candidates = chosen + rng.uniform(-0.5, 0.5, size=(batch, 3)) * cell_size
            mask = domain.signed_distance(candidates) <= -boundary_offset_mm
            accepted.extend(candidates[mask])
            candidate_count += batch

    if len(accepted) < count:
        raise ValueError(
            f"Generated only {len(accepted)} of {count} requested seeds after {candidate_count} candidates. "
            "Reduce boundaryOffsetMm or seedCount."
        )
    points = np.asarray(accepted[:count])
    return SeedSamplingResult(points, {
        "requestedSeedCount": int(count),
        "acceptedSeedCount": int(count),
        "candidateCount": int(candidate_count),
        "rejectedCandidateCount": int(candidate_count - count),
        "acceptanceRatio": float(count / candidate_count),
        "boundaryOffsetMm": float(boundary_offset_mm),
        "samplingMethod": method,
        "generationTimeSeconds": float(perf_counter() - started),
    })


def _bisect_surface_crossing(domain: GeometryDomain, start: np.ndarray, end: np.ndarray, t0: float, t1: float, tolerance: float) -> float:
    f0 = float(domain.signed_distance(start + (end - start) * t0))
    for _ in range(48):
        midpoint = (t0 + t1) * 0.5
        fm = float(domain.signed_distance(start + (end - start) * midpoint))
        if abs(fm) <= tolerance or abs(t1 - t0) * np.linalg.norm(end - start) <= tolerance:
            return midpoint
        if (f0 <= 0) == (fm <= 0):
            t0, f0 = midpoint, fm
        else:
            t1 = midpoint
    return (t0 + t1) * 0.5


def clip_segment_to_domain_intervals(
    start: np.ndarray,
    end: np.ndarray,
    domain: GeometryDomain,
    sampling_step: float,
    root_tolerance: float = 1e-5,
    maximum_samples: int = 4096,
) -> list[tuple[np.ndarray, np.ndarray]]:
    first, second = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    length = float(np.linalg.norm(second - first))
    if length <= root_tolerance:
        return []
    count = int(np.clip(np.ceil(length / max(sampling_step, root_tolerance)) + 1, 2, maximum_samples))
    parameters = np.linspace(0.0, 1.0, count)
    points = first + parameters[:, None] * (second - first)
    values = domain.signed_distance(points)
    inside = values <= 0
    intervals: list[tuple[np.ndarray, np.ndarray]] = []
    index = 0
    while index < count:
        if not inside[index]:
            index += 1
            continue
        run_start = index
        while index + 1 < count and inside[index + 1]:
            index += 1
        run_end = index
        start_t = parameters[run_start]
        end_t = parameters[run_end]
        if run_start > 0:
            start_t = _bisect_surface_crossing(domain, first, second, parameters[run_start - 1], parameters[run_start], root_tolerance)
        if run_end + 1 < count:
            end_t = _bisect_surface_crossing(domain, first, second, parameters[run_end], parameters[run_end + 1], root_tolerance)
        clipped_start = first + start_t * (second - first)
        clipped_end = first + end_t * (second - first)
        if np.linalg.norm(clipped_end - clipped_start) > root_tolerance:
            intervals.append((clipped_start, clipped_end))
        index += 1
    return intervals


def clip_edges_to_domain(
    edges: list[tuple[np.ndarray, np.ndarray]],
    domain: GeometryDomain,
    sampling_step: float,
    minimum_length_mm: float,
    cancellation_token=None,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], dict]:
    started = perf_counter()
    output: list[tuple[np.ndarray, np.ndarray]] = []
    rejected = split = removed_short = intersections = 0
    for index, (start, end) in enumerate(edges):
        if cancellation_token is not None and index % 32 == 0:
            cancellation_token.check()
        intervals = clip_segment_to_domain_intervals(start, end, domain, sampling_step)
        if not intervals:
            rejected += 1
            continue
        if len(intervals) > 1:
            split += 1
        for clipped_start, clipped_end in intervals:
            if np.linalg.norm(clipped_end - clipped_start) < minimum_length_mm:
                removed_short += 1
                continue
            intersections += int(np.linalg.norm(clipped_start - start) > 1e-5)
            intersections += int(np.linalg.norm(clipped_end - end) > 1e-5)
            output.append((clipped_start, clipped_end))
    return output, {
        "inputStrutCount": len(edges),
        "rejectedOutsideStrutCount": rejected,
        "splitStrutCount": split,
        "outputIntervalCount": len(output),
        "surfaceIntersectionNodeCount": intersections,
        "removedShortIntervalCount": removed_short,
        "clippingTimeSeconds": float(perf_counter() - started),
    }
