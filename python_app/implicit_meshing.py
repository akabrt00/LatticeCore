from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from time import monotonic, perf_counter

import numpy as np
import pyvista as pv

from memory_metrics import voxel_memory_preflight


GENERATOR_MEMORY_LIMIT_BYTES = 768 * 1024 * 1024
GENERATOR_MAX_VOXELS = 32_000_000
MIN_VOXEL_SIZE_MM = 0.04


class GeometryDomain(ABC):
    """Signed-distance domain used by the implicit lattice pipeline."""

    @abstractmethod
    def signed_distance(self, points: np.ndarray) -> np.ndarray:
        """Return negative values inside, zero on, and positive outside."""

    @abstractmethod
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Return minimum and maximum XYZ bounds in millimeters."""

    def contains(self, points: np.ndarray, tolerance: float = 0.0) -> np.ndarray:
        return self.signed_distance(points) <= tolerance


@dataclass(frozen=True)
class BoxDomain(GeometryDomain):
    half_sizes: np.ndarray
    center: np.ndarray

    def __init__(self, half_sizes: np.ndarray, center: np.ndarray | None = None):
        half = np.asarray(half_sizes, dtype=float)
        if half.shape != (3,) or np.any(half <= 0):
            raise ValueError("Box half sizes must be a positive XYZ vector.")
        object.__setattr__(self, "half_sizes", half)
        object.__setattr__(self, "center", np.zeros(3) if center is None else np.asarray(center, dtype=float))

    def signed_distance(self, points: np.ndarray) -> np.ndarray:
        samples = np.asarray(points, dtype=float)
        q = np.abs(samples - self.center) - self.half_sizes
        outside = np.linalg.norm(np.maximum(q, 0.0), axis=-1)
        inside = np.minimum(np.max(q, axis=-1), 0.0)
        return outside + inside

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.center - self.half_sizes, self.center + self.half_sizes


@dataclass(frozen=True)
class CapsulePrimitive:
    start: np.ndarray
    end: np.ndarray
    radius: float


@dataclass(frozen=True)
class SpherePrimitive:
    center: np.ndarray
    radius: float


@dataclass(frozen=True)
class VoxelGridPlan:
    origin: np.ndarray
    maximum: np.ndarray
    spacing: np.ndarray
    dimensions: tuple[int, int, int]
    requested_voxel_size_mm: float
    total_voxel_count: int
    estimated_field_memory_bytes: int
    estimated_temporary_memory_bytes: int
    estimated_total_memory_bytes: int
    memory_preflight: dict

    def metadata(self) -> dict:
        data = asdict(self)
        data["origin"] = self.origin.tolist()
        data["maximum"] = self.maximum.tolist()
        data["spacing"] = self.spacing.tolist()
        data["gridSizeX"], data["gridSizeY"], data["gridSizeZ"] = self.dimensions
        data["totalVoxelCount"] = self.total_voxel_count
        data["estimatedFieldMemoryBytes"] = self.estimated_field_memory_bytes
        data["estimatedTemporaryMemoryBytes"] = self.estimated_temporary_memory_bytes
        data["estimatedTotalMemoryBytes"] = self.estimated_total_memory_bytes
        data["memoryPreflight"] = self.memory_preflight
        return data


def sphere_sdf(points: np.ndarray, center: np.ndarray, radius: float) -> np.ndarray:
    samples = np.asarray(points, dtype=float)
    return np.linalg.norm(samples - np.asarray(center, dtype=float), axis=-1) - float(radius)


def capsule_sdf(
    points: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    radius: float,
    degeneracy_tolerance: float = 1e-12,
) -> np.ndarray:
    samples = np.asarray(points, dtype=float)
    first = np.asarray(start, dtype=float)
    second = np.asarray(end, dtype=float)
    segment = second - first
    squared_length = float(np.dot(segment, segment))
    if squared_length <= degeneracy_tolerance:
        return sphere_sdf(samples, first, radius)
    projection = np.sum((samples - first) * segment, axis=-1) / squared_length
    projection = np.clip(projection, 0.0, 1.0)
    closest = first + projection[..., None] * segment
    return np.linalg.norm(samples - closest, axis=-1) - float(radius)


def union_sdf(*fields: np.ndarray) -> np.ndarray:
    if not fields:
        raise ValueError("At least one field is required for an SDF union.")
    return np.minimum.reduce(fields)


def intersection_sdf(*fields: np.ndarray) -> np.ndarray:
    if not fields:
        raise ValueError("At least one field is required for an SDF intersection.")
    return np.maximum.reduce(fields)


def resolve_voxel_size(strut_diameter_mm: float, quality_preset: str, custom_voxel_size_mm: float) -> float:
    if quality_preset == "custom":
        voxel_size = float(custom_voxel_size_mm)
    else:
        voxels_across = {"preview": 4.0, "standard": 6.0, "high": 10.0}.get(quality_preset)
        if voxels_across is None:
            raise ValueError(f"Unknown quality preset: {quality_preset}")
        voxel_size = float(strut_diameter_mm) / voxels_across
    if voxel_size < MIN_VOXEL_SIZE_MM:
        raise ValueError(f"Voxel size {voxel_size:.4f} mm is below the safe limit {MIN_VOXEL_SIZE_MM:.2f} mm.")
    return voxel_size


def create_voxel_grid_plan(domain: GeometryDomain, voxel_size_mm: float, padding_voxels: int = 2) -> VoxelGridPlan:
    minimum, maximum = domain.bounds()
    padding = float(voxel_size_mm) * int(padding_voxels)
    origin = minimum - padding
    padded_maximum = maximum + padding
    extent = padded_maximum - origin
    dimensions_array = np.ceil(extent / float(voxel_size_mm)).astype(int) + 1
    spacing = extent / np.maximum(dimensions_array - 1, 1)
    dimensions = tuple(int(value) for value in dimensions_array)
    total = int(np.prod(dimensions_array, dtype=np.int64))
    field_bytes = total * np.dtype(np.float32).itemsize
    temporary_bytes = field_bytes * 5
    estimated_total = field_bytes + temporary_bytes
    if total > GENERATOR_MAX_VOXELS:
        raise ValueError(f"Voxel grid requires {total:,} samples; safe limit is {GENERATOR_MAX_VOXELS:,}.")
    if estimated_total > GENERATOR_MEMORY_LIMIT_BYTES:
        raise ValueError(
            f"Estimated implicit meshing memory is {estimated_total / 1024**2:.0f} MiB; "
            f"safe limit is {GENERATOR_MEMORY_LIMIT_BYTES / 1024**2:.0f} MiB."
        )
    memory_preflight = voxel_memory_preflight(estimated_total)
    return VoxelGridPlan(
        origin=origin,
        maximum=padded_maximum,
        spacing=spacing,
        dimensions=dimensions,
        requested_voxel_size_mm=float(voxel_size_mm),
        total_voxel_count=total,
        estimated_field_memory_bytes=field_bytes,
        estimated_temporary_memory_bytes=temporary_bytes,
        estimated_total_memory_bytes=estimated_total,
        memory_preflight=memory_preflight,
    )


def _primitive_bounds(primitive: CapsulePrimitive | SpherePrimitive, margin: float) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(primitive, CapsulePrimitive):
        minimum = np.minimum(primitive.start, primitive.end)
        maximum = np.maximum(primitive.start, primitive.end)
        radius = primitive.radius
    else:
        minimum = primitive.center
        maximum = primitive.center
        radius = primitive.radius
    expansion = float(radius) + float(margin)
    return minimum - expansion, maximum + expansion


def _build_uniform_block_index(
    primitives: list[CapsulePrimitive | SpherePrimitive],
    plan: VoxelGridPlan,
    block_size: int,
    narrow_band_margin: float,
) -> dict[tuple[int, int, int], list[int]]:
    block_counts = np.ceil(np.asarray(plan.dimensions) / block_size).astype(int)
    index: dict[tuple[int, int, int], list[int]] = {}
    for primitive_index, primitive in enumerate(primitives):
        minimum, maximum = _primitive_bounds(primitive, narrow_band_margin)
        first_voxel = np.floor((minimum - plan.origin) / plan.spacing).astype(int)
        last_voxel = np.ceil((maximum - plan.origin) / plan.spacing).astype(int)
        first_block = np.clip(first_voxel // block_size, 0, block_counts - 1)
        last_block = np.clip(last_voxel // block_size, 0, block_counts - 1)
        for block_x in range(int(first_block[0]), int(last_block[0]) + 1):
            for block_y in range(int(first_block[1]), int(last_block[1]) + 1):
                for block_z in range(int(first_block[2]), int(last_block[2]) + 1):
                    index.setdefault((block_x, block_y, block_z), []).append(primitive_index)
    return index


def evaluate_lattice_field(
    plan: VoxelGridPlan,
    capsules: list[CapsulePrimitive],
    spheres: list[SpherePrimitive],
    block_size: int = 16,
    narrow_band_voxels: float = 2.5,
    progress_callback=None,
    cancellation_token=None,
) -> tuple[np.ndarray, dict]:
    primitives: list[CapsulePrimitive | SpherePrimitive] = [*capsules, *spheres]
    if not primitives:
        raise ValueError("Implicit meshing requires at least one capsule or sphere primitive.")
    margin = float(np.max(plan.spacing)) * narrow_band_voxels
    block_index = _build_uniform_block_index(primitives, plan, block_size, margin)
    background = np.float32(np.linalg.norm(plan.maximum - plan.origin))
    field = np.full(plan.dimensions, background, dtype=np.float32)
    dimensions = np.asarray(plan.dimensions)

    block_keys = sorted(block_index)
    last_report = 0.0
    for completed, block_key in enumerate(block_keys, start=1):
        if cancellation_token is not None:
            cancellation_token.check()
        start = np.asarray(block_key) * block_size
        stop = np.minimum(start + block_size, dimensions)
        axes = [
            plan.origin[axis] + np.arange(start[axis], stop[axis], dtype=np.float32) * plan.spacing[axis]
            for axis in range(3)
        ]
        x, y, z = np.meshgrid(*axes, indexing="ij")
        points = np.column_stack((x.ravel(), y.ravel(), z.ravel()))
        values = np.full(len(points), background, dtype=np.float32)
        for primitive_index in block_index[block_key]:
            primitive = primitives[primitive_index]
            if isinstance(primitive, CapsulePrimitive):
                candidate = capsule_sdf(points, primitive.start, primitive.end, primitive.radius)
            else:
                candidate = sphere_sdf(points, primitive.center, primitive.radius)
            np.minimum(values, candidate, out=values)
        block_shape = tuple((stop - start).tolist())
        field[
            start[0] : stop[0],
            start[1] : stop[1],
            start[2] : stop[2],
        ] = values.reshape(block_shape)
        now = monotonic()
        if progress_callback is not None and (now - last_report >= 0.125 or completed == len(block_keys)):
            progress_callback(completed, len(block_keys))
            last_report = now

    return field, {
        "spatialIndexType": "uniform-voxel-block-aabb",
        "blockSizeVoxels": int(block_size),
        "indexedBlockCount": int(len(block_index)),
        "primitiveCount": int(len(primitives)),
        "strutPrimitiveCount": int(len(capsules)),
        "nodePrimitiveCount": int(len(spheres)),
    }


def apply_domain_intersection(
    field: np.ndarray,
    plan: VoxelGridPlan,
    domain: GeometryDomain,
    slab_size: int = 16,
    progress_callback=None,
    cancellation_token=None,
) -> None:
    nx, ny, nz = plan.dimensions
    y_axis = plan.origin[1] + np.arange(ny, dtype=np.float32) * plan.spacing[1]
    z_axis = plan.origin[2] + np.arange(nz, dtype=np.float32) * plan.spacing[2]
    slab_starts = list(range(0, nx, slab_size))
    last_report = 0.0
    for completed, x_start in enumerate(slab_starts, start=1):
        if cancellation_token is not None:
            cancellation_token.check()
        x_stop = min(x_start + slab_size, nx)
        x_axis = plan.origin[0] + np.arange(x_start, x_stop, dtype=np.float32) * plan.spacing[0]
        x, y, z = np.meshgrid(x_axis, y_axis, z_axis, indexing="ij")
        points = np.column_stack((x.ravel(), y.ravel(), z.ravel()))
        domain_values = domain.signed_distance(points).astype(np.float32).reshape((x_stop - x_start, ny, nz))
        np.maximum(field[x_start:x_stop], domain_values, out=field[x_start:x_stop])
        now = monotonic()
        if progress_callback is not None and (now - last_report >= 0.125 or completed == len(slab_starts)):
            progress_callback(completed, len(slab_starts))
            last_report = now


def remove_tiny_marching_components(mesh: pv.PolyData, maximum_artifact_cells: int = 64) -> tuple[pv.PolyData, int]:
    """Remove only tiny disconnected contour artifacts, preserving meaningful bodies."""
    if mesh.n_cells == 0:
        return mesh, 0
    # VTK extraction provenance arrays can retain the pre-cleanup cell count
    # after connectivity filtering. They are not part of the export geometry.
    mesh.clear_data()
    connected = mesh.connectivity()
    region_ids, counts = np.unique(connected.cell_data["RegionId"], return_counts=True)
    if len(region_ids) <= 1:
        mesh.clear_data()
        return mesh, 0
    largest_index = int(np.argmax(counts))
    secondary_counts = np.delete(counts, largest_index)
    if np.any(secondary_counts > maximum_artifact_cells):
        mesh.clear_data()
        return mesh, 0
    largest = connected.connectivity(extraction_mode="largest").extract_surface(algorithm="dataset_surface")
    rebuilt = pv.PolyData(np.asarray(largest.points).copy(), np.asarray(largest.faces).copy()).clean()
    return rebuilt, int(len(region_ids) - 1)


def marching_cubes_mesh(field: np.ndarray, plan: VoxelGridPlan) -> tuple[pv.PolyData, int]:
    # A mathematically exact zero on a grid vertex creates ambiguous duplicate
    # triangles in VTK. A deterministic sub-micron outside tie-break preserves
    # level=0 geometry while avoiding those degeneracies.
    zero_tie_break = np.float32(float(np.max(plan.spacing)) * 1e-6)
    field[np.abs(field) <= zero_tie_break] = zero_tie_break
    image = pv.ImageData(dimensions=plan.dimensions, spacing=plan.spacing, origin=plan.origin)
    image.point_data["sdf"] = np.asarray(field, dtype=np.float32).ravel(order="F")
    mesh = image.contour(isosurfaces=[0.0], scalars="sdf", method="flying_edges")
    mesh = mesh.extract_surface(algorithm="dataset_surface").triangulate().clean()
    mesh, removed_artifacts = remove_tiny_marching_components(mesh)
    rebuilt = pv.PolyData(np.asarray(mesh.points).copy(), np.asarray(mesh.faces).copy()).clean()
    return rebuilt, removed_artifacts


def generate_implicit_union_mesh(
    domain: GeometryDomain,
    capsules: list[CapsulePrimitive],
    spheres: list[SpherePrimitive],
    voxel_size_mm: float,
    exact_domain_intersection: bool = True,
    progress_callback=None,
    cancellation_token=None,
) -> tuple[pv.PolyData, dict]:
    started = perf_counter()
    plan = create_voxel_grid_plan(domain, voxel_size_mm)
    if progress_callback is not None:
        progress_callback(
            phase="memory-preflight",
            message=(
                "Odhad paměti překračuje soft limit; pokračuji pod dohledem."
                if plan.memory_preflight["softLimitExceeded"]
                else "Paměťový preflight voxelové mřížky prošel."
            ),
            fraction=0.0,
            metrics={
                **plan.memory_preflight,
                "estimatedVoxelFieldBytes": plan.estimated_field_memory_bytes,
                "estimatedNumpyBytes": plan.estimated_total_memory_bytes,
            },
        )
    field_started = perf_counter()
    field, index_stats = evaluate_lattice_field(
        plan,
        capsules,
        spheres,
        progress_callback=(
            (lambda completed, total: progress_callback(
                phase="generating-final-mesh",
                message=f"Vyhodnocuji SDF blok {completed}/{total}",
                fraction=completed / max(total, 1),
                metrics={"completedBlocks": completed, "totalBlocks": total},
            ))
            if progress_callback is not None else None
        ),
        cancellation_token=cancellation_token,
    )
    if exact_domain_intersection:
        apply_domain_intersection(
            field,
            plan,
            domain,
            progress_callback=(
                (lambda completed, total: progress_callback(
                    phase="clipping-interior",
                    message=f"Ořezávám SDF blok {completed}/{total}",
                    fraction=completed / max(total, 1),
                    metrics={"completedBlocks": completed, "totalBlocks": total},
                ))
                if progress_callback is not None else None
            ),
            cancellation_token=cancellation_token,
        )
    if cancellation_token is not None:
        cancellation_token.check()
    field_seconds = perf_counter() - field_started
    marching_started = perf_counter()
    mesh, removed_artifacts = marching_cubes_mesh(field, plan)
    marching_seconds = perf_counter() - marching_started
    metadata = {
        "enabled": True,
        "voxelSizeMm": float(voxel_size_mm),
        "gridSizeX": plan.dimensions[0],
        "gridSizeY": plan.dimensions[1],
        "gridSizeZ": plan.dimensions[2],
        "totalVoxelCount": plan.total_voxel_count,
        "estimatedMemoryBytes": plan.estimated_total_memory_bytes,
        "estimatedFieldMemoryBytes": plan.estimated_field_memory_bytes,
        "estimatedTemporaryMemoryBytes": plan.estimated_temporary_memory_bytes,
        "memoryPreflight": plan.memory_preflight,
        "actualFieldMemoryBytes": int(field.nbytes),
        **index_stats,
        "marchingCubesVertexCount": int(mesh.n_points),
        "marchingCubesTriangleCount": int(mesh.n_cells),
        "removedTinyComponentCount": int(removed_artifacts),
        "zeroTieBreakMm": float(np.max(plan.spacing) * 1e-6),
        "generationTimeSeconds": float(perf_counter() - started),
        "fieldEvaluationTimeSeconds": float(field_seconds),
        "marchingCubesTimeSeconds": float(marching_seconds),
    }
    return mesh, metadata
