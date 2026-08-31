from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import numpy as np
import pyvista as pv
from scipy.spatial import SphericalVoronoi, Voronoi

from cache_store import CacheStore, build_cache_keys, canonical_hash, file_content_hash
from density_solver import density_statistics, mass_estimate
from debug_payload import ALL_LAYERS, write_debug_payload
from conformal_surface import (
    SurfaceVoronoiParameters,
    SurfaceVoronoiResult,
    generate_conformal_surface,
    place_conformal_surface_graph,
)
from implicit_meshing import (
    BoxDomain,
    CapsulePrimitive,
    SpherePrimitive,
    generate_implicit_union_mesh,
    resolve_voxel_size,
)
from imported_mesh import (
    TriangleMeshDomain,
    clip_edges_to_domain,
    generate_points_in_domain,
    load_triangle_mesh,
)
from worker_runtime import WorkerRuntime, build_topology_session_key


@dataclass(frozen=True)
class OptimizationStats:
    """Basic counts from the automatic strut cleanup stage."""

    raw_edges: int
    inside_edges: int
    removed_short_edges: int
    collapsed_short_edges: int = 0


def as_half_sizes(value: float | np.ndarray | list[float] | tuple[float, float, float]) -> np.ndarray:
    """Normalize a scalar cube half-size or XYZ box half-sizes to a 3-vector."""
    half_sizes = np.asarray(value, dtype=float)
    if half_sizes.ndim == 0:
        return np.repeat(float(half_sizes), 3)
    if half_sizes.shape != (3,):
        raise ValueError(f"Box half-sizes must be scalar or XYZ triplet, got shape {half_sizes.shape}.")
    if np.any(half_sizes <= 0):
        raise ValueError("Box dimensions must be positive.")
    return half_sizes


def box_reference_radius(half_sizes: np.ndarray) -> float:
    """Use the largest half-axis as the existing relative-parameter reference length."""
    return float(np.max(as_half_sizes(half_sizes)))


def generate_points_in_sphere(n: int, radius: float, random_seed: int = 42) -> np.ndarray:
    """Generate n random points inside a sphere centered at [0, 0, 0]."""
    rng = np.random.default_rng(random_seed)
    points: list[np.ndarray] = []

    while len(points) < n:
        candidate = rng.uniform(-radius, radius, size=3)
        if np.linalg.norm(candidate) <= radius:
            points.append(candidate)

    return np.asarray(points)


def generate_points_in_box(n: int, half_size: float | np.ndarray, random_seed: int = 42) -> np.ndarray:
    """Generate n random points inside a box centered at [0, 0, 0]."""
    rng = np.random.default_rng(random_seed)
    half_sizes = as_half_sizes(half_size)
    return rng.uniform(-half_sizes, half_sizes, size=(n, 3))


def load_input_body_mesh(input_path: str, import_scale: float = 1.0) -> pv.PolyData:
    """Load a triangular STL/OBJ without changing its source coordinate system."""
    mesh, _ = load_triangle_mesh(input_path, import_scale)
    return mesh


def mesh_contains_points(mesh: pv.PolyData, points: np.ndarray) -> np.ndarray:
    """Return a boolean mask for points inside a closed PyVista surface."""
    if len(points) == 0:
        return np.asarray([], dtype=bool)

    point_cloud = pv.PolyData(points)
    selected = point_cloud.select_enclosed_points(mesh, tolerance=1e-5, check_surface=False)
    return selected.point_data["SelectedPoints"].astype(bool)


def generate_points_in_mesh(mesh: pv.PolyData, n: int, random_seed: int = 42) -> np.ndarray:
    """Generate n random points inside an arbitrary STL body."""
    rng = np.random.default_rng(random_seed)
    bounds = np.asarray(mesh.bounds, dtype=float)
    mins = np.asarray([bounds[0], bounds[2], bounds[4]])
    maxs = np.asarray([bounds[1], bounds[3], bounds[5]])
    points: list[np.ndarray] = []
    batch_size = max(256, n * 8)

    for _ in range(120):
        candidates = rng.uniform(mins, maxs, size=(batch_size, 3))
        inside = mesh_contains_points(mesh, candidates)
        points.extend(candidates[inside])
        if len(points) >= n:
            return np.asarray(points[:n])

    if len(points) < 5:
        raise ValueError(
            "Could not sample enough points inside the imported STL. "
            "The model may be open/non-watertight or too thin for volume lattice generation."
        )
    return np.asarray(points[:n])


def generate_body_points(shape: str, n: int, radius: float, random_seed: int) -> np.ndarray:
    """Generate points inside the selected implicit body."""
    if shape == "box":
        return generate_points_in_box(n, radius, random_seed)
    return generate_points_in_sphere(n, radius, random_seed)


def compute_voronoi_edges(points: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Compute finite Voronoi ridge polygon edges as pairs of 3D points."""
    voronoi = Voronoi(points)
    edges: list[tuple[np.ndarray, np.ndarray]] = []
    seen_edges: set[tuple[int, int]] = set()

    for ridge_vertices in voronoi.ridge_vertices:
        if -1 in ridge_vertices:
            continue
        if len(ridge_vertices) < 2:
            continue

        for index in range(len(ridge_vertices)):
            start_index = ridge_vertices[index]
            end_index = ridge_vertices[(index + 1) % len(ridge_vertices)]
            edge_key = tuple(sorted((start_index, end_index)))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            start = voronoi.vertices[start_index]
            end = voronoi.vertices[end_index]
            edges.append((start, end))

    return edges


def compute_voronoi_edges_with_ghost_seeds(
    points: np.ndarray,
    minimum: np.ndarray,
    maximum: np.ndarray,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Bound imported-mesh Voronoi cells with deterministic seeds outside its AABB."""
    center = (np.asarray(minimum, dtype=float) + np.asarray(maximum, dtype=float)) * 0.5
    half = np.maximum((np.asarray(maximum, dtype=float) - np.asarray(minimum, dtype=float)) * 0.5, 1e-6)
    ghost = np.asarray(
        [center + np.asarray([x, y, z], dtype=float) * half * 2.5
         for x in (-1.0, 0.0, 1.0)
         for y in (-1.0, 0.0, 1.0)
         for z in (-1.0, 0.0, 1.0)
         if (x, y, z) != (0.0, 0.0, 0.0)]
    )
    return compute_voronoi_edges(np.vstack((points, ghost)))


def compute_voronoi_vertex_count(points: np.ndarray) -> int:
    """Return the number of finite vertices produced by SciPy's 3D Voronoi diagram."""
    if len(points) < 5:
        return 0
    return int(len(Voronoi(points).vertices))


def filter_edges_inside_sphere(
    edges: list[tuple[np.ndarray, np.ndarray]],
    radius: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Keep only edges whose both endpoints are inside the sphere."""
    filtered_edges: list[tuple[np.ndarray, np.ndarray]] = []

    for start, end in edges:
        if np.linalg.norm(start) <= radius and np.linalg.norm(end) <= radius:
            filtered_edges.append((start, end))

    return filtered_edges


def filter_edges_inside_box(
    edges: list[tuple[np.ndarray, np.ndarray]],
    half_size: float | np.ndarray,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Keep only edges whose both endpoints are inside the box."""
    half_sizes = as_half_sizes(half_size)
    filtered_edges: list[tuple[np.ndarray, np.ndarray]] = []

    for start, end in edges:
        if np.all(np.abs(start) <= half_sizes) and np.all(np.abs(end) <= half_sizes):
            filtered_edges.append((start, end))

    return filtered_edges


def filter_edges_inside_mesh(
    edges: list[tuple[np.ndarray, np.ndarray]],
    mesh: pv.PolyData,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Keep only edges whose endpoints and midpoint are inside an imported mesh."""
    if not edges:
        return []

    samples = []
    for start, end in edges:
        samples.extend((start, end, (start + end) * 0.5))

    inside = mesh_contains_points(mesh, np.asarray(samples))
    filtered_edges: list[tuple[np.ndarray, np.ndarray]] = []
    for edge_index, edge in enumerate(edges):
        offset = edge_index * 3
        if bool(inside[offset]) and bool(inside[offset + 1]) and bool(inside[offset + 2]):
            filtered_edges.append(edge)

    return filtered_edges


def edge_stays_inside_mesh(start: np.ndarray, end: np.ndarray, mesh: pv.PolyData) -> bool:
    """Return True when a connector is likely inside the body volume.

    The surface endpoint can lie exactly on the mesh boundary, so only interior
    samples along the segment are tested.
    """
    samples = np.asarray([
        start * 0.85 + end * 0.15,
        start * 0.55 + end * 0.45,
        start * 0.25 + end * 0.75,
        end,
    ])
    return bool(np.all(mesh_contains_points(mesh, samples)))


def filter_edges_inside_body(
    shape: str,
    edges: list[tuple[np.ndarray, np.ndarray]],
    radius: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Keep only edges whose endpoints are inside the selected body."""
    if shape == "box":
        return filter_edges_inside_box(edges, radius)
    return filter_edges_inside_sphere(edges, radius)


def filter_edges_by_length(
    edges: list[tuple[np.ndarray, np.ndarray]],
    min_length: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Remove tiny struts that would create bumps instead of useful structure."""
    if min_length <= 0:
        return edges

    return [(start, end) for start, end in edges if np.linalg.norm(end - start) >= min_length]


def collapse_short_edge_nodes(
    edges: list[tuple[np.ndarray, np.ndarray]],
    min_length: float,
    max_iterations: int = 4,
    decimals: int = 6,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], int]:
    """Replace tiny struts by merging their endpoints into a shared median node."""
    if min_length <= 0 or not edges:
        return edges, 0

    current_edges = edges
    collapsed_total = 0

    for _ in range(max_iterations):
        points_by_key: dict[tuple[float, float, float], np.ndarray] = {}
        parent: dict[tuple[float, float, float], tuple[float, float, float]] = {}

        def key_for(point: np.ndarray) -> tuple[float, float, float]:
            return tuple(np.round(point, decimals))

        def ensure(point: np.ndarray) -> tuple[float, float, float]:
            key = key_for(point)
            points_by_key.setdefault(key, point)
            parent.setdefault(key, key)
            return key

        def find(key: tuple[float, float, float]) -> tuple[float, float, float]:
            root = key
            while parent[root] != root:
                root = parent[root]
            while parent[key] != key:
                next_key = parent[key]
                parent[key] = root
                key = next_key
            return root

        def union(first: tuple[float, float, float], second: tuple[float, float, float]) -> None:
            first_root = find(first)
            second_root = find(second)
            if first_root != second_root:
                parent[second_root] = first_root

        short_edges = 0
        for start, end in current_edges:
            start_key = ensure(start)
            end_key = ensure(end)
            if float(np.linalg.norm(end - start)) < min_length:
                union(start_key, end_key)
                short_edges += 1

        if short_edges == 0:
            break

        components: dict[tuple[float, float, float], list[np.ndarray]] = {}
        for key, point in points_by_key.items():
            components.setdefault(find(key), []).append(point)

        merged_points = {
            root: np.median(np.asarray(component_points), axis=0)
            for root, component_points in components.items()
        }

        rebuilt_edges: list[tuple[np.ndarray, np.ndarray]] = []
        seen_edges: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = set()
        for start, end in current_edges:
            merged_start = merged_points[find(key_for(start))]
            merged_end = merged_points[find(key_for(end))]
            if np.linalg.norm(merged_end - merged_start) < min_length:
                continue
            start_key = key_for(merged_start)
            end_key = key_for(merged_end)
            edge_key = (start_key, end_key) if start_key <= end_key else (end_key, start_key)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            rebuilt_edges.append((merged_start, merged_end))

        current_edges = rebuilt_edges
        collapsed_total += short_edges

    return current_edges, collapsed_total


def collapse_short_edges_across_groups(
    edge_groups: list[list[tuple[np.ndarray, np.ndarray]]],
    min_length: float,
    max_iterations: int = 3,
    decimals: int = 6,
) -> tuple[list[list[tuple[np.ndarray, np.ndarray]]], int]:
    """Merge near-duplicate nodes across inner, connector, and surface edge groups."""
    if min_length <= 0 or not edge_groups:
        return edge_groups, 0

    current_groups = edge_groups
    collapsed_total = 0

    for _ in range(max_iterations):
        points_by_key: dict[tuple[float, float, float], np.ndarray] = {}
        parent: dict[tuple[float, float, float], tuple[float, float, float]] = {}

        def key_for(point: np.ndarray) -> tuple[float, float, float]:
            return tuple(np.round(point, decimals))

        def ensure(point: np.ndarray) -> tuple[float, float, float]:
            key = key_for(point)
            points_by_key.setdefault(key, point)
            parent.setdefault(key, key)
            return key

        def find(key: tuple[float, float, float]) -> tuple[float, float, float]:
            root = key
            while parent[root] != root:
                root = parent[root]
            while parent[key] != key:
                next_key = parent[key]
                parent[key] = root
                key = next_key
            return root

        def union(first: tuple[float, float, float], second: tuple[float, float, float]) -> None:
            first_root = find(first)
            second_root = find(second)
            if first_root != second_root:
                parent[second_root] = first_root

        short_edges = 0
        for group in current_groups:
            for start, end in group:
                start_key = ensure(start)
                end_key = ensure(end)
                if float(np.linalg.norm(end - start)) < min_length:
                    union(start_key, end_key)
                    short_edges += 1

        point_keys = list(points_by_key)
        for first_index, first_key in enumerate(point_keys):
            first_point = points_by_key[first_key]
            for second_key in point_keys[first_index + 1 :]:
                if float(np.linalg.norm(points_by_key[second_key] - first_point)) >= min_length:
                    continue
                first_root = find(first_key)
                second_root = find(second_key)
                if first_root == second_root:
                    continue
                union(first_root, second_root)
                short_edges += 1

        if short_edges == 0:
            break

        components: dict[tuple[float, float, float], list[np.ndarray]] = {}
        for key, point in points_by_key.items():
            components.setdefault(find(key), []).append(point)

        merged_points = {
            root: np.median(np.asarray(component_points), axis=0)
            for root, component_points in components.items()
        }

        rebuilt_groups: list[list[tuple[np.ndarray, np.ndarray]]] = []
        for group in current_groups:
            rebuilt_group: list[tuple[np.ndarray, np.ndarray]] = []
            seen_edges: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = set()
            for start, end in group:
                merged_start = merged_points[find(key_for(start))]
                merged_end = merged_points[find(key_for(end))]
                if np.linalg.norm(merged_end - merged_start) < min_length:
                    continue
                start_key = key_for(merged_start)
                end_key = key_for(merged_end)
                edge_key = (start_key, end_key) if start_key <= end_key else (end_key, start_key)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                rebuilt_group.append((merged_start, merged_end))
            rebuilt_groups.append(rebuilt_group)

        current_groups = rebuilt_groups
        collapsed_total += short_edges

    return current_groups, collapsed_total


def optimize_strut_network(
    shape: str,
    edges: list[tuple[np.ndarray, np.ndarray]],
    radius: float,
    min_length: float,
    enabled: bool,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], OptimizationStats]:
    """Clip Voronoi edges to the body and remove tiny struts."""
    inside_edges = filter_edges_inside_body(shape, edges, radius)
    if enabled:
        collapsed_edges, collapsed_short_edges = collapse_short_edge_nodes(inside_edges, min_length)
        reclipped_edges = filter_edges_inside_body(shape, collapsed_edges, radius)
        optimized_edges = filter_edges_by_length(reclipped_edges, min_length)
    else:
        collapsed_short_edges = 0
        optimized_edges = inside_edges

    stats = OptimizationStats(
        raw_edges=len(edges),
        inside_edges=len(inside_edges),
        removed_short_edges=len(inside_edges) - len(optimized_edges),
        collapsed_short_edges=collapsed_short_edges,
    )
    return optimized_edges, stats


def optimize_mesh_strut_network(
    edges: list[tuple[np.ndarray, np.ndarray]],
    mesh: pv.PolyData,
    min_length: float,
    enabled: bool,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], OptimizationStats]:
    """Clip Voronoi edges to an imported body mesh and remove tiny struts."""
    inside_edges = filter_edges_inside_mesh(edges, mesh)
    if enabled:
        collapsed_edges, collapsed_short_edges = collapse_short_edge_nodes(inside_edges, min_length)
        reclipped_edges = filter_edges_inside_mesh(collapsed_edges, mesh)
        optimized_edges = filter_edges_by_length(reclipped_edges, min_length)
    else:
        collapsed_short_edges = 0
        optimized_edges = inside_edges
    stats = OptimizationStats(
        raw_edges=len(edges),
        inside_edges=len(inside_edges),
        removed_short_edges=len(inside_edges) - len(optimized_edges),
        collapsed_short_edges=collapsed_short_edges,
    )
    return optimized_edges, stats


def create_tube_mesh(
    edges: list[tuple[np.ndarray, np.ndarray]],
    tube_radius: float,
) -> pv.PolyData:
    """Convert Voronoi edges to one merged tube mesh."""
    tube_mesh = pv.PolyData()

    for start, end in edges:
        if np.linalg.norm(end - start) <= tube_radius * 2:
            continue

        line = pv.Line(start, end)
        tube = line.tube(radius=tube_radius, n_sides=16, capping=True)
        tube_mesh = tube if tube_mesh.n_points == 0 else tube_mesh.merge(tube)

    return tube_mesh


def generate_points_on_sphere(n: int, radius: float, random_seed: int = 1337) -> np.ndarray:
    """Generate n repeatable random points on a sphere surface."""
    rng = np.random.default_rng(random_seed)
    points = rng.normal(size=(n, 3))
    lengths = np.linalg.norm(points, axis=1)
    points = points / lengths[:, None]
    return points * radius


def generate_points_on_square(n: int, half_size: float, random_seed: int) -> np.ndarray:
    """Generate repeatable random 2D points on one square face."""
    rng = np.random.default_rng(random_seed)
    return rng.uniform(-half_size, half_size, size=(n, 2))


def spherical_arc_points(start: np.ndarray, end: np.ndarray, radius: float, steps: int = 9) -> np.ndarray:
    """Interpolate a short great-circle arc between two sphere points."""
    start_unit = start / np.linalg.norm(start)
    end_unit = end / np.linalg.norm(end)
    dot = float(np.clip(np.dot(start_unit, end_unit), -1.0, 1.0))
    angle = float(np.arccos(dot))

    if angle < 1e-8:
        return np.asarray([start, end])

    samples = []
    for value in np.linspace(0.0, 1.0, steps):
        a = np.sin((1.0 - value) * angle) / np.sin(angle)
        b = np.sin(value * angle) / np.sin(angle)
        point = (a * start_unit + b * end_unit) * radius
        samples.append(point)

    return np.asarray(samples)


def create_polyline(points: np.ndarray) -> pv.PolyData:
    """Create a PyVista polyline from ordered points."""
    polyline = pv.PolyData()
    polyline.points = points
    polyline.lines = np.hstack(([len(points)], np.arange(len(points)))).astype(np.int64)
    return polyline


def compute_surface_voronoi_edges(
    surface_points: np.ndarray,
    radius: float,
) -> list[np.ndarray]:
    """Compute approximate spherical Voronoi boundary arcs."""
    spherical_voronoi = SphericalVoronoi(surface_points, radius=radius, center=np.zeros(3))
    spherical_voronoi.sort_vertices_of_regions()
    arcs: list[np.ndarray] = []
    seen_edges: set[tuple[int, int]] = set()

    for region in spherical_voronoi.regions:
        if len(region) < 2:
            continue

        for index in range(len(region)):
            start_index = region[index]
            end_index = region[(index + 1) % len(region)]
            edge_key = tuple(sorted((start_index, end_index)))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            start = spherical_voronoi.vertices[start_index]
            end = spherical_voronoi.vertices[end_index]
            arcs.append(spherical_arc_points(start, end, radius))

    return arcs


def create_surface_voronoi_shell(
    radius: float,
    surface_seed_count: int,
    tube_radius: float,
    random_seed: int,
) -> pv.PolyData:
    """Create a Voronoi-like open shell made from tubes on the sphere surface."""
    surface_points = generate_points_on_sphere(surface_seed_count, radius, random_seed)
    surface_arcs = compute_surface_voronoi_edges(surface_points, radius)
    shell_mesh = pv.PolyData()

    for arc in surface_arcs:
        if len(arc) < 2:
            continue
        tube = create_polyline(arc).tube(radius=tube_radius, n_sides=16, capping=True)
        shell_mesh = tube if shell_mesh.n_points == 0 else shell_mesh.merge(tube)

    return shell_mesh.clean()


def point_2d_inside_square(point: np.ndarray, half_size: float) -> bool:
    """Return True when a 2D point is inside the square face bounds."""
    return bool(np.all(np.abs(point) <= half_size))


def polygon_area_2d(points: np.ndarray) -> float:
    """Return signed area of a 2D polygon."""
    if len(points) < 3:
        return 0.0
    x = points[:, 0]
    y = points[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - y * np.roll(x, -1)))


def clip_polygon_half_plane(
    polygon: np.ndarray,
    axis: int,
    limit: float,
    keep_less_equal: bool,
) -> np.ndarray:
    """Clip a 2D polygon against one axis-aligned half-plane."""
    if len(polygon) == 0:
        return polygon

    clipped: list[np.ndarray] = []

    def inside(point: np.ndarray) -> bool:
        return bool(point[axis] <= limit + 1e-9) if keep_less_equal else bool(point[axis] >= limit - 1e-9)

    def intersection(start: np.ndarray, end: np.ndarray) -> np.ndarray:
        direction = end - start
        if abs(direction[axis]) < 1e-12:
            return end
        factor = (limit - start[axis]) / direction[axis]
        return start + factor * direction

    previous = polygon[-1]
    previous_inside = inside(previous)

    for current in polygon:
        current_inside = inside(current)

        if current_inside:
            if not previous_inside:
                clipped.append(intersection(previous, current))
            clipped.append(current)
        elif previous_inside:
            clipped.append(intersection(previous, current))

        previous = current
        previous_inside = current_inside

    return np.asarray(clipped)


def clip_polygon_to_square(polygon: np.ndarray, half_size: float) -> np.ndarray:
    """Clip a 2D polygon to the square face boundary."""
    clipped = polygon
    clipped = clip_polygon_half_plane(clipped, axis=0, limit=-half_size, keep_less_equal=False)
    clipped = clip_polygon_half_plane(clipped, axis=0, limit=half_size, keep_less_equal=True)
    clipped = clip_polygon_half_plane(clipped, axis=1, limit=-half_size, keep_less_equal=False)
    clipped = clip_polygon_half_plane(clipped, axis=1, limit=half_size, keep_less_equal=True)

    if len(clipped) < 3 or abs(polygon_area_2d(clipped)) < 1e-10:
        return np.empty((0, 2))

    return clipped


def finite_voronoi_regions_2d(points: np.ndarray, extension_radius: float) -> list[np.ndarray]:
    """Build finite 2D Voronoi regions, extending infinite regions outward."""
    voronoi = Voronoi(points)
    center = points.mean(axis=0)
    all_ridges: dict[int, list[tuple[int, int, int]]] = {}

    for (first_point, second_point), (first_vertex, second_vertex) in zip(
        voronoi.ridge_points,
        voronoi.ridge_vertices,
    ):
        all_ridges.setdefault(first_point, []).append((second_point, first_vertex, second_vertex))
        all_ridges.setdefault(second_point, []).append((first_point, first_vertex, second_vertex))

    regions: list[np.ndarray] = []

    for point_index, region_index in enumerate(voronoi.point_region):
        region = voronoi.regions[region_index]

        if all(vertex_index >= 0 for vertex_index in region):
            polygon = voronoi.vertices[region]
            regions.append(order_polygon_vertices(polygon))
            continue

        new_region = [vertex_index for vertex_index in region if vertex_index >= 0]

        for neighbor_index, first_vertex, second_vertex in all_ridges[point_index]:
            if first_vertex >= 0 and second_vertex >= 0:
                continue

            finite_vertex = first_vertex if first_vertex >= 0 else second_vertex
            tangent = points[neighbor_index] - points[point_index]
            tangent = tangent / np.linalg.norm(tangent)
            normal = np.asarray([-tangent[1], tangent[0]])
            midpoint = points[[point_index, neighbor_index]].mean(axis=0)
            direction = np.sign(np.dot(midpoint - center, normal)) * normal
            far_point = voronoi.vertices[finite_vertex] + direction * extension_radius
            new_region.append(len(voronoi.vertices))
            voronoi.vertices = np.vstack([voronoi.vertices, far_point])

        regions.append(order_polygon_vertices(voronoi.vertices[new_region]))

    return regions


def order_polygon_vertices(points: np.ndarray) -> np.ndarray:
    """Order 2D polygon vertices around their centroid."""
    centroid = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - centroid[1], points[:, 0] - centroid[0])
    return points[np.argsort(angles)]


def edge_key_2d(start: np.ndarray, end: np.ndarray, decimals: int = 6) -> tuple[tuple[float, float], tuple[float, float]]:
    """Create a stable undirected key for a 2D segment."""
    first = tuple(np.round(start, decimals))
    second = tuple(np.round(end, decimals))
    return (first, second) if first <= second else (second, first)


def edge_is_on_square_boundary(start: np.ndarray, end: np.ndarray, half_size: float) -> bool:
    """Return True if a segment lies directly on the outer square frame."""
    tolerance = 1e-6
    return bool(
        (abs(start[0] - end[0]) <= tolerance and abs(abs(start[0]) - half_size) <= tolerance)
        or (abs(start[1] - end[1]) <= tolerance and abs(abs(start[1]) - half_size) <= tolerance)
    )


def compute_square_voronoi_edges(
    points: np.ndarray,
    half_size: float,
    min_edge_length: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Compute 2D Voronoi cell edges clipped to a square face."""
    edges: list[tuple[np.ndarray, np.ndarray]] = []
    seen_edges: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    regions = finite_voronoi_regions_2d(points, extension_radius=half_size * 8.0)

    for region in regions:
        clipped_region = clip_polygon_to_square(region, half_size)
        if len(clipped_region) < 3:
            continue

        for index in range(len(clipped_region)):
            start = clipped_region[index]
            end = clipped_region[(index + 1) % len(clipped_region)]
            if np.linalg.norm(end - start) < min_edge_length:
                continue
            if edge_is_on_square_boundary(start, end, half_size):
                continue
            key = edge_key_2d(start, end)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append((start, end))

    return edges


def face_point_to_3d(face: str, point: np.ndarray, half_size: float | np.ndarray) -> np.ndarray:
    """Map a normalized 2D face point to its 3D box face."""
    hx, hy, hz = as_half_sizes(half_size)
    u, v = point
    if face == "x+":
        return np.asarray([hx, u * hy, v * hz])
    if face == "x-":
        return np.asarray([-hx, u * hy, v * hz])
    if face == "y+":
        return np.asarray([u * hx, hy, v * hz])
    if face == "y-":
        return np.asarray([u * hx, -hy, v * hz])
    if face == "z+":
        return np.asarray([u * hx, v * hy, hz])
    return np.asarray([u * hx, v * hy, -hz])


def create_box_frame_edges(half_size: float | np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Create the 12 outer box frame edges."""
    hx, hy, hz = as_half_sizes(half_size)
    corners = [
        np.asarray([x, y, z])
        for x in (-hx, hx)
        for y in (-hy, hy)
        for z in (-hz, hz)
    ]
    edges = []

    for first_index, first in enumerate(corners):
        for second in corners[first_index + 1 :]:
            differing_axes = np.count_nonzero(np.abs(first - second) > 1e-9)
            if differing_axes == 1:
                edges.append((first, second))

    return edges


def create_box_surface_voronoi_edges(
    half_size: float | np.ndarray,
    surface_seed_count: int,
    random_seed: int,
    min_edge_length: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Create Voronoi-like tube centerlines on each cube face."""
    faces = ["x+", "x-", "y+", "y-", "z+", "z-"]
    seeds_per_face = max(6, int(np.ceil(surface_seed_count / len(faces))))
    surface_edges: list[tuple[np.ndarray, np.ndarray]] = create_box_frame_edges(half_size)

    for face_index, face in enumerate(faces):
        points_2d = generate_points_on_square(seeds_per_face, 1.0, random_seed + face_index * 101)
        edges_2d = compute_square_voronoi_edges(points_2d, 1.0, 0.0)
        for start, end in edges_2d:
            surface_edges.append(
                (
                    face_point_to_3d(face, start, half_size),
                    face_point_to_3d(face, end, half_size),
                )
            )

    return surface_edges


def create_box_surface_voronoi_shell(
    half_size: float | np.ndarray,
    surface_seed_count: int,
    tube_radius: float,
    random_seed: int,
    min_edge_length: float,
) -> tuple[pv.PolyData, list[tuple[np.ndarray, np.ndarray]]]:
    """Create a cube casing with Voronoi-like tube cells on each face."""
    surface_edges = create_box_surface_voronoi_edges(half_size, surface_seed_count, random_seed, min_edge_length)
    surface_edges, _ = collapse_short_edge_nodes(surface_edges, min_edge_length)
    return create_tube_mesh(surface_edges, tube_radius).clean(), surface_edges


def create_surface_shell(
    shape: str,
    radius: float,
    surface_seed_count: int,
    tube_radius: float,
    random_seed: int,
    min_edge_length: float,
) -> tuple[pv.PolyData, list[tuple[np.ndarray, np.ndarray]]]:
    """Create the selected body surface as a Voronoi-like tube shell."""
    if shape == "box":
        return create_box_surface_voronoi_shell(radius, surface_seed_count, tube_radius, random_seed, min_edge_length)
    return create_surface_voronoi_shell(radius, surface_seed_count, tube_radius, random_seed), []


def sample_points_on_mesh_surface(
    mesh: pv.PolyData,
    count: int,
    random_seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted random points on a triangulated mesh surface with face normals."""
    rng = np.random.default_rng(random_seed)
    faces = mesh.faces.reshape((-1, 4))[:, 1:4]
    vertices = np.asarray(mesh.points)
    triangles = vertices[faces]

    vectors_a = triangles[:, 1] - triangles[:, 0]
    vectors_b = triangles[:, 2] - triangles[:, 0]
    cross = np.cross(vectors_a, vectors_b)
    areas = np.linalg.norm(cross, axis=1) * 0.5
    valid = areas > 1e-12
    if not np.any(valid):
        raise ValueError("Input STL has no usable triangle surface area.")

    faces = faces[valid]
    triangles = triangles[valid]
    cross = cross[valid]
    areas = areas[valid]
    normals = cross / np.linalg.norm(cross, axis=1)[:, None]
    probabilities = areas / areas.sum()
    chosen = rng.choice(len(triangles), size=count, replace=True, p=probabilities)
    chosen_triangles = triangles[chosen]

    u = rng.random(count)
    v = rng.random(count)
    flip = u + v > 1.0
    u[flip] = 1.0 - u[flip]
    v[flip] = 1.0 - v[flip]
    points = chosen_triangles[:, 0] + u[:, None] * (chosen_triangles[:, 1] - chosen_triangles[:, 0]) + v[:, None] * (
        chosen_triangles[:, 2] - chosen_triangles[:, 0]
    )
    return points, normals[chosen]


def create_mesh_surface_lattice_edges(
    mesh: pv.PolyData,
    surface_seed_count: int,
    random_seed: int,
    min_edge_length: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Create a surface network from local STL triangle adjacency, never across open air."""
    del random_seed
    faces = mesh.faces.reshape((-1, 4))[:, 1:4]
    vertices = np.asarray(mesh.points)
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = np.asarray([bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]])
    max_extent = float(np.max(extents)) or 1.0
    base_spacing = max_extent * float(np.clip(1.15 / np.sqrt(max(surface_seed_count, 1)), 0.055, 0.14))

    for spacing_scale in (1.0, 0.75, 0.55):
        spacing = max(base_spacing * spacing_scale, min_edge_length * 1.25, 1e-6)
        cluster_sums: dict[tuple[int, int, int], np.ndarray] = {}
        cluster_counts: dict[tuple[int, int, int], int] = {}
        vertex_keys: list[tuple[int, int, int]] = []
        edge_keys: set[tuple[tuple[int, int, int], tuple[int, int, int]]] = set()

        def add_cluster_point(point: np.ndarray) -> tuple[int, int, int]:
            key = tuple(np.floor(point / spacing).astype(int))
            cluster_sums[key] = cluster_sums.get(key, np.zeros(3)) + point
            cluster_counts[key] = cluster_counts.get(key, 0) + 1
            return key

        def add_edge_key(first_key: tuple[int, int, int], second_key: tuple[int, int, int]) -> None:
            if first_key == second_key:
                return
            edge_key = (first_key, second_key) if first_key <= second_key else (second_key, first_key)
            edge_keys.add(edge_key)

        for vertex in vertices:
            vertex_keys.append(add_cluster_point(vertex))

        for face in faces:
            face_indices = [int(face[0]), int(face[1]), int(face[2])]
            face_points = vertices[face_indices]
            face_keys = [vertex_keys[index] for index in face_indices]
            for first_index, second_index in (
                (0, 1),
                (1, 2),
                (2, 0),
            ):
                add_edge_key(face_keys[first_index], face_keys[second_index])

            edge_lengths = [
                float(np.linalg.norm(face_points[1] - face_points[0])),
                float(np.linalg.norm(face_points[2] - face_points[1])),
                float(np.linalg.norm(face_points[0] - face_points[2])),
            ]
            face_area = float(np.linalg.norm(np.cross(face_points[1] - face_points[0], face_points[2] - face_points[0])) * 0.5)
            needs_inner_node = max(edge_lengths) > spacing * 1.45 or face_area > spacing * spacing * 0.55
            if needs_inner_node:
                centroid_key = add_cluster_point(np.mean(face_points, axis=0))
                for corner_key in face_keys:
                    add_edge_key(centroid_key, corner_key)

                for edge_index, length in enumerate(edge_lengths):
                    if length <= spacing * 1.75:
                        continue
                    start_index, end_index = ((0, 1), (1, 2), (2, 0))[edge_index]
                    midpoint_key = add_cluster_point((face_points[start_index] + face_points[end_index]) * 0.5)
                    add_edge_key(midpoint_key, face_keys[start_index])
                    add_edge_key(midpoint_key, face_keys[end_index])
                    add_edge_key(midpoint_key, centroid_key)

        cluster_points = {
            key: cluster_sums[key] / cluster_counts[key]
            for key in cluster_sums
        }

        max_edge_length = spacing * 2.6
        surface_edges: list[tuple[np.ndarray, np.ndarray]] = []
        for first_key, second_key in edge_keys:
            start = cluster_points[first_key]
            end = cluster_points[second_key]
            length = float(np.linalg.norm(end - start))
            if length < min_edge_length * 0.35 or length > max_edge_length:
                continue
            surface_edges.append((start, end))

        if len(surface_edges) >= max(18, int(surface_seed_count * 0.85)):
            return surface_edges

    return surface_edges


def create_mesh_surface_shell(
    mesh: pv.PolyData,
    surface_seed_count: int,
    tube_radius: float,
    random_seed: int,
    min_edge_length: float,
) -> tuple[pv.PolyData, list[tuple[np.ndarray, np.ndarray]]]:
    """Create a tube shell that follows an imported STL surface."""
    surface_edges = create_mesh_surface_lattice_edges(mesh, surface_seed_count, random_seed, min_edge_length)
    surface_edges, _ = collapse_short_edge_nodes(surface_edges, min_edge_length)
    return create_tube_mesh(surface_edges, tube_radius).clean(), surface_edges


def resolve_surface_seed_count(shape: str, requested_surface_points: int, inner_seed_count: int) -> int:
    """Choose surface density from inner density unless the user overrides it."""
    if requested_surface_points > 0:
        return requested_surface_points
    if shape == "mesh":
        return int(np.clip(round(inner_seed_count * 1.15), 48, 320))
    if shape == "box":
        return int(np.clip(round(inner_seed_count * 0.85), 36, 240))
    return int(np.clip(round(inner_seed_count * 0.7), 24, 180))


def unique_edge_points(edges: list[tuple[np.ndarray, np.ndarray]], decimals: int = 5) -> list[np.ndarray]:
    """Collect unique endpoints from edge centerlines."""
    points: dict[tuple[float, float, float], np.ndarray] = {}

    for start, end in edges:
        for point in (start, end):
            key = tuple(np.round(point, decimals))
            points[key] = point

    return list(points.values())


def box_boundary_distance(point: np.ndarray, half_size: float | np.ndarray) -> float:
    """Return distance from a point inside a box to the nearest face."""
    half_sizes = as_half_sizes(half_size)
    return float(np.min(half_sizes - np.abs(point)))


def nearest_box_face(point: np.ndarray, half_size: float | np.ndarray) -> tuple[int, float]:
    """Return nearest axis-aligned box face and sign."""
    half_sizes = as_half_sizes(half_size)
    margins = half_sizes - np.abs(point)
    axis = int(np.argmin(margins))
    sign = 1.0 if point[axis] >= 0 else -1.0
    return axis, sign


def same_box_face(point: np.ndarray, surface_point: np.ndarray, half_size: float | np.ndarray) -> bool:
    """Return True when an inner point and surface point belong to the same nearest face."""
    half_sizes = as_half_sizes(half_size)
    axis, sign = nearest_box_face(point, half_sizes)
    return bool(abs(surface_point[axis] - sign * half_sizes[axis]) <= 1e-6)


def point_key_3d(point: np.ndarray, decimals: int = 5) -> tuple[float, float, float]:
    """Create a stable rounded key for a 3D point."""
    return tuple(np.round(point, decimals))


def edge_key_3d(start: np.ndarray, end: np.ndarray, decimals: int = 5) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Create a stable undirected key for a 3D segment."""
    first = point_key_3d(start, decimals)
    second = point_key_3d(end, decimals)
    return (first, second) if first <= second else (second, first)


def create_box_connection_edges(
    inside_edges: list[tuple[np.ndarray, np.ndarray]],
    surface_edges: list[tuple[np.ndarray, np.ndarray]],
    half_size: float | np.ndarray,
    boundary_band: float,
    max_length: float,
    min_length: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Connect near-boundary inner lattice endpoints to nearby surface nodes."""
    surface_points = unique_edge_points(surface_edges)
    inner_points = [
        point
        for point in unique_edge_points(inside_edges)
        if 0.0 <= box_boundary_distance(point, half_size) <= boundary_band
    ]
    connector_edges: list[tuple[np.ndarray, np.ndarray]] = []
    seen_edges: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = set()
    max_connectors = max(48, min(len(surface_points) * 2, len(inner_points) * 3, 420))

    def add_connector(inner_point: np.ndarray, surface_point: np.ndarray) -> None:
        if len(connector_edges) >= max_connectors:
            return
        length = float(np.linalg.norm(surface_point - inner_point))
        if length < min_length or length > max_length:
            return

        key = edge_key_3d(inner_point, surface_point)
        if key in seen_edges:
            return
        seen_edges.add(key)
        connector_edges.append((inner_point, surface_point))

    for inner_point in inner_points:
        face_points = [point for point in surface_points if same_box_face(inner_point, point, half_size)]
        if not face_points:
            continue
        ranked_surface = sorted(face_points, key=lambda point: float(np.linalg.norm(point - inner_point)))
        for surface_point in ranked_surface[:2]:
            add_connector(inner_point, surface_point)

    for surface_point in surface_points:
        face_inner_points = [point for point in inner_points if same_box_face(point, surface_point, half_size)]
        if not face_inner_points:
            continue
        ranked_inner = sorted(face_inner_points, key=lambda point: float(np.linalg.norm(point - surface_point)))
        for inner_point in ranked_inner[:2]:
            add_connector(inner_point, surface_point)

    return connector_edges


def create_mesh_connection_edges(
    inside_edges: list[tuple[np.ndarray, np.ndarray]],
    surface_edges: list[tuple[np.ndarray, np.ndarray]],
    max_length: float,
    min_length: float,
    mesh: pv.PolyData | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Create a transition layer between imported-surface and inner lattice nodes."""
    surface_points = unique_edge_points(surface_edges)
    inner_points = unique_edge_points(inside_edges)
    if not surface_points or not inner_points:
        return []

    surface_array = np.asarray(surface_points)
    inner_array = np.asarray(inner_points)
    connector_edges: list[tuple[np.ndarray, np.ndarray]] = []
    seen_edges: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = set()
    max_connectors = max(64, min(len(surface_points) * 2, len(inner_points) * 3, 480))

    def add_connector(inner_point: np.ndarray, surface_point: np.ndarray) -> bool:
        if len(connector_edges) >= max_connectors:
            return False
        length = float(np.linalg.norm(surface_point - inner_point))
        if length < min_length or length > max_length:
            return False
        if mesh is not None and not edge_stays_inside_mesh(surface_point, inner_point, mesh):
            return False

        key = edge_key_3d(inner_point, surface_point)
        if key in seen_edges:
            return False
        seen_edges.add(key)
        connector_edges.append((inner_point, surface_point))
        return True

    for inner_point in inner_points:
        distances = np.linalg.norm(surface_array - inner_point, axis=1)
        ranked_surface = np.argsort(distances)
        added_for_inner = 0
        for surface_index in ranked_surface:
            if add_connector(inner_point, surface_array[int(surface_index)]):
                added_for_inner += 1
            if len(connector_edges) >= max_connectors:
                return connector_edges
            if added_for_inner >= 2:
                break

    for surface_point in surface_points:
        distances = np.linalg.norm(inner_array - surface_point, axis=1)
        ranked_inner = np.argsort(distances)
        added_for_surface = 0
        for inner_index in ranked_inner:
            if add_connector(inner_array[int(inner_index)], surface_point):
                added_for_surface += 1
            if len(connector_edges) >= max_connectors:
                return connector_edges
            if added_for_surface >= 2:
                break

    return connector_edges


def create_connection_edges(
    shape: str,
    inside_edges: list[tuple[np.ndarray, np.ndarray]],
    surface_edges: list[tuple[np.ndarray, np.ndarray]],
    radius: float,
    boundary_band: float,
    max_length: float,
    min_length: float,
    mesh: pv.PolyData | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Create connection struts between inner lattice and surface network."""
    if shape == "mesh":
        return create_mesh_connection_edges(inside_edges, surface_edges, max_length, min_length, mesh)
    if shape != "box" or not surface_edges:
        return []
    return create_box_connection_edges(inside_edges, surface_edges, radius, boundary_band, max_length, min_length)


def keep_edges_connected_to_surface(
    inside_edges: list[tuple[np.ndarray, np.ndarray]],
    connector_edges: list[tuple[np.ndarray, np.ndarray]],
    surface_edges: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[list[tuple[np.ndarray, np.ndarray]], list[tuple[np.ndarray, np.ndarray]], int]:
    """Remove imported-mesh inner islands that are not connected to the surface shell."""
    if not inside_edges or not surface_edges:
        return inside_edges, connector_edges, 0

    graph: dict[tuple[float, float, float], set[tuple[float, float, float]]] = {}
    surface_keys = {point_key_3d(point) for point in unique_edge_points(surface_edges)}

    def add_graph_edge(start: np.ndarray, end: np.ndarray) -> None:
        start_key = point_key_3d(start)
        end_key = point_key_3d(end)
        graph.setdefault(start_key, set()).add(end_key)
        graph.setdefault(end_key, set()).add(start_key)

    for start, end in inside_edges + connector_edges:
        add_graph_edge(start, end)

    visited: set[tuple[float, float, float]] = set()
    stack = [key for key in surface_keys if key in graph]
    while stack:
        key = stack.pop()
        if key in visited:
            continue
        visited.add(key)
        stack.extend(graph.get(key, set()) - visited)

    filtered_inside = [
        (start, end)
        for start, end in inside_edges
        if point_key_3d(start) in visited and point_key_3d(end) in visited
    ]
    filtered_connectors = [
        (start, end)
        for start, end in connector_edges
        if point_key_3d(start) in visited and point_key_3d(end) in visited
    ]
    removed_count = (len(inside_edges) - len(filtered_inside)) + (len(connector_edges) - len(filtered_connectors))
    return filtered_inside, filtered_connectors, removed_count


def build_node_degree(
    edges: list[tuple[np.ndarray, np.ndarray]],
    decimals: int = 5,
) -> tuple[dict[tuple[float, float, float], int], dict[tuple[float, float, float], np.ndarray]]:
    """Count how many struts touch each rounded endpoint."""
    degree: dict[tuple[float, float, float], int] = {}
    points: dict[tuple[float, float, float], np.ndarray] = {}

    for start, end in edges:
        for point in (start, end):
            key = point_key_3d(point, decimals)
            degree[key] = degree.get(key, 0) + 1
            points[key] = point

    return degree, points


def create_dangling_support_edges(
    candidate_edges: list[tuple[np.ndarray, np.ndarray]],
    anchor_edges: list[tuple[np.ndarray, np.ndarray]],
    half_size: float,
    min_length: float,
    max_length: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Add short braces from low-degree inner endpoints to nearby lattice nodes."""
    all_edges = candidate_edges + anchor_edges
    degree, points_by_key = build_node_degree(all_edges)
    candidate_degree, candidate_points_by_key = build_node_degree(candidate_edges)
    existing_edges = {edge_key_3d(start, end) for start, end in all_edges}
    anchor_points = list(points_by_key.values())
    support_edges: list[tuple[np.ndarray, np.ndarray]] = []
    seen_edges: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = set()

    for point_key in candidate_degree:
        degree_count = degree.get(point_key, 0)
        if degree_count > 1:
            continue

        point = candidate_points_by_key[point_key]
        if box_boundary_distance(point, half_size) <= min_length:
            continue

        candidates = []
        for anchor in anchor_points:
            key = edge_key_3d(point, anchor)
            if key in existing_edges or key in seen_edges:
                continue
            distance = float(np.linalg.norm(anchor - point))
            if min_length <= distance <= max_length:
                candidates.append((distance, anchor, key))

        if not candidates:
            continue

        _, anchor, key = min(candidates, key=lambda item: item[0])
        seen_edges.add(key)
        support_edges.append((point, anchor))

    return support_edges


def create_node_sphere_mesh(
    edges: list[tuple[np.ndarray, np.ndarray]],
    node_radius: float,
    theta_resolution: int = 8,
    phi_resolution: int = 8,
) -> pv.PolyData:
    """Create small spheres at strut endpoints to close visual/print gaps."""
    node_mesh = pv.PolyData()

    for point in unique_edge_points(edges):
        sphere = pv.Sphere(
            radius=node_radius,
            center=point,
            theta_resolution=theta_resolution,
            phi_resolution=phi_resolution,
        )
        node_mesh = sphere if node_mesh.n_points == 0 else node_mesh.merge(sphere)

    return node_mesh.clean()


def combine_meshes(meshes: list[pv.PolyData]) -> pv.PolyData:
    """Merge non-empty meshes into one PolyData object."""
    combined = pv.PolyData()

    for mesh in meshes:
        if mesh.n_points == 0:
            continue
        combined = mesh if combined.n_points == 0 else combined.merge(mesh)

    return combined.clean()


def is_point_inside_domain(point: np.ndarray, shape: str, domain: float | np.ndarray, tolerance: float = 0.0) -> bool:
    """Return whether a point lies in the supported generation domain."""
    if shape == "box":
        return bool(np.all(np.abs(point) <= as_half_sizes(domain) + tolerance))
    if shape == "sphere":
        return bool(np.linalg.norm(point) <= float(domain) + tolerance)
    raise ValueError(f"Point-domain query is not implemented for shape: {shape}")


def signed_distance_to_domain(point: np.ndarray, shape: str, domain: float | np.ndarray) -> float:
    """Return a positive distance inside the domain and negative outside."""
    if shape == "box":
        return float(np.min(as_half_sizes(domain) - np.abs(point)))
    if shape == "sphere":
        return float(domain) - float(np.linalg.norm(point))
    raise ValueError(f"Signed distance is not implemented for shape: {shape}")


def inset_edges_for_box(
    edges: list[tuple[np.ndarray, np.ndarray]],
    half_sizes: float | np.ndarray,
    geometry_radius: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Clamp centerlines into a box inset so their swept volume stays in the box.

    This is the current robust polygonal-box approximation. It preserves closed
    tube and node primitives and can later be replaced by a true mesh-domain
    intersection behind ``clip_final_geometry_to_domain``.
    """
    inset = as_half_sizes(half_sizes) - float(geometry_radius)
    if np.any(inset <= 0):
        raise ValueError("Strut/node radius is too large for the requested box dimensions.")

    clipped: list[tuple[np.ndarray, np.ndarray]] = []
    seen: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = set()
    for start, end in edges:
        adjusted_start = np.clip(np.asarray(start, dtype=float), -inset, inset)
        adjusted_end = np.clip(np.asarray(end, dtype=float), -inset, inset)
        if np.linalg.norm(adjusted_end - adjusted_start) <= 1e-8:
            continue
        key = edge_key_3d(adjusted_start, adjusted_end, decimals=6)
        if key in seen:
            continue
        seen.add(key)
        clipped.append((adjusted_start, adjusted_end))
    return clipped


def clip_final_geometry_to_domain(
    edges: list[tuple[np.ndarray, np.ndarray]],
    shape: str,
    domain: float | np.ndarray,
    geometry_radius: float,
    boundary_mode: str,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Prepare centerlines so the generated swept geometry respects its domain."""
    if boundary_mode == "centerline":
        return edges
    if boundary_mode != "exact":
        raise ValueError(f"Unknown boundary mode: {boundary_mode}")
    if shape != "box":
        # Exact general-mesh clipping intentionally remains behind this API.
        return edges
    return inset_edges_for_box(edges, domain, geometry_radius)


def analyze_strut_graph(
    edges: list[tuple[np.ndarray, np.ndarray]],
    extra_nodes: list[np.ndarray] | None = None,
    decimals: int = 6,
) -> dict:
    """Compute deterministic graph connectivity and degree statistics."""
    graph: dict[tuple[float, float, float], set[tuple[float, float, float]]] = {}
    for point in extra_nodes or []:
        graph.setdefault(point_key_3d(point, decimals), set())
    for start, end in edges:
        first = point_key_3d(start, decimals)
        second = point_key_3d(end, decimals)
        graph.setdefault(first, set()).add(second)
        graph.setdefault(second, set()).add(first)

    components: list[set[tuple[float, float, float]]] = []
    visited: set[tuple[float, float, float]] = set()
    for node in sorted(graph):
        if node in visited:
            continue
        component: set[tuple[float, float, float]] = set()
        stack = [node]
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(graph[current] - component)
        visited.update(component)
        components.append(component)

    degrees = [len(neighbors) for neighbors in graph.values()]
    return {
        "connectedComponentCount": len(components),
        "componentSizes": sorted((len(component) for component in components), reverse=True),
        "isolatedNodeCount": sum(degree == 0 for degree in degrees),
        "degreeOneNodeCount": sum(degree == 1 for degree in degrees),
        "averageNodeDegree": float(np.mean(degrees)) if degrees else 0.0,
        "maximumNodeDegree": max(degrees, default=0),
        "nodeCount": len(graph),
    }


def keep_largest_graph_component(
    edge_groups: list[list[tuple[np.ndarray, np.ndarray]]],
    decimals: int = 6,
) -> tuple[list[list[tuple[np.ndarray, np.ndarray]]], int, int]:
    """Keep only the largest connected strut component, preserving edge groups."""
    all_edges = [edge for group in edge_groups for edge in group]
    if not all_edges:
        return edge_groups, 0, 0

    adjacency: dict[tuple[float, float, float], set[tuple[float, float, float]]] = {}
    for start, end in all_edges:
        first = point_key_3d(start, decimals)
        second = point_key_3d(end, decimals)
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)

    components: list[set[tuple[float, float, float]]] = []
    remaining = set(adjacency)
    while remaining:
        component: set[tuple[float, float, float]] = set()
        stack = [min(remaining)]
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            stack.extend(adjacency[node] - component)
        remaining -= component
        components.append(component)

    largest = max(components, key=lambda component: (len(component), sorted(component)[0]))
    filtered_groups = [
        [
            (start, end)
            for start, end in group
            if point_key_3d(start, decimals) in largest and point_key_3d(end, decimals) in largest
        ]
        for group in edge_groups
    ]
    removed_edges = len(all_edges) - sum(len(group) for group in filtered_groups)
    return filtered_groups, max(0, len(components) - 1), removed_edges


def _mesh_faces(mesh: pv.PolyData) -> np.ndarray:
    """Return triangular face indices as an N x 3 array."""
    triangular = mesh.triangulate()
    if triangular.n_cells == 0:
        return np.empty((0, 3), dtype=np.int64)
    return np.asarray(triangular.faces, dtype=np.int64).reshape(-1, 4)[:, 1:4]


def validate_mesh(mesh: pv.PolyData, tolerance: float = 1e-7) -> dict:
    """Calculate topology and triangle-quality metrics from actual export geometry."""
    triangular = mesh.extract_surface(algorithm="dataset_surface").triangulate()
    points = np.asarray(triangular.points, dtype=float)
    faces = _mesh_faces(triangular)
    if len(points) == 0 or len(faces) == 0:
        return {
            "isWatertight": False, "isEdgeManifold": False, "boundaryEdgeCount": 0,
            "nonManifoldEdgeCount": 0, "degenerateTriangleCount": 0,
            "duplicateTriangleCount": 0, "unusedVertexCount": len(points),
            "connectedComponentCount": 0, "signedVolumeMm3": 0.0, "absoluteVolumeMm3": 0.0,
        }

    quantized = np.round(points / tolerance).astype(np.int64)
    _, canonical = np.unique(quantized, axis=0, return_inverse=True)
    canonical_faces = canonical[faces]
    a = points[faces[:, 0]]
    b = points[faces[:, 1]]
    c = points[faces[:, 2]]
    twice_areas = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    degenerate = (twice_areas <= tolerance * tolerance) | (
        (canonical_faces[:, 0] == canonical_faces[:, 1])
        | (canonical_faces[:, 1] == canonical_faces[:, 2])
        | (canonical_faces[:, 2] == canonical_faces[:, 0])
    )

    sorted_faces = np.sort(canonical_faces, axis=1)
    _, face_counts = np.unique(sorted_faces, axis=0, return_counts=True)
    duplicate_count = int(np.sum(np.maximum(face_counts - 1, 0)))

    edge_counts: dict[tuple[int, int], int] = {}
    for face in canonical_faces[~degenerate]:
        for first, second in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            key = (int(first), int(second)) if first < second else (int(second), int(first))
            edge_counts[key] = edge_counts.get(key, 0) + 1
    boundary_count = sum(count == 1 for count in edge_counts.values())
    non_manifold_count = sum(count > 2 for count in edge_counts.values())

    face_graph = [[] for _ in range(len(faces))]
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face_index, face in enumerate(canonical_faces):
        for first, second in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            key = (int(first), int(second)) if first < second else (int(second), int(first))
            edge_faces.setdefault(key, []).append(face_index)
    for indices in edge_faces.values():
        for face_index in indices[1:]:
            face_graph[indices[0]].append(face_index)
            face_graph[face_index].append(indices[0])
    visited_faces: set[int] = set()
    component_count = 0
    component_volumes: list[float] = []
    for face_index in range(len(faces)):
        if face_index in visited_faces:
            continue
        component_count += 1
        stack = [face_index]
        component_faces: list[int] = []
        while stack:
            current = stack.pop()
            if current in visited_faces:
                continue
            visited_faces.add(current)
            component_faces.append(current)
            stack.extend(face_graph[current])
        indices = np.asarray(component_faces, dtype=np.int64)
        component_volumes.append(abs(float(np.sum(np.einsum("ij,ij->i", a[indices], np.cross(b[indices], c[indices]))) / 6.0)))

    used = np.unique(faces)
    signed_volume = float(np.sum(np.einsum("ij,ij->i", a, np.cross(b, c))) / 6.0)
    return {
        "isWatertight": boundary_count == 0 and non_manifold_count == 0,
        "isEdgeManifold": non_manifold_count == 0,
        "boundaryEdgeCount": int(boundary_count),
        "nonManifoldEdgeCount": int(non_manifold_count),
        "degenerateTriangleCount": int(np.count_nonzero(degenerate)),
        "duplicateTriangleCount": duplicate_count,
        "unusedVertexCount": int(len(points) - len(used)),
        "connectedComponentCount": int(component_count),
        "componentVolumesMm3": component_volumes,
        "signedVolumeMm3": signed_volume,
        "absoluteVolumeMm3": float(np.sum(component_volumes)),
    }


def repair_mesh_for_export(mesh: pv.PolyData, tolerance: float = 1e-7) -> pv.PolyData:
    """Apply conservative vertex/face cleanup without changing topology intentionally."""
    cleaned = mesh.extract_surface(algorithm="dataset_surface").triangulate().clean(
        point_merging=True,
        tolerance=tolerance,
        absolute=True,
    )
    points = np.asarray(cleaned.points, dtype=float)
    faces = _mesh_faces(cleaned)
    if len(faces) == 0:
        return pv.PolyData()

    a = points[faces[:, 0]]
    b = points[faces[:, 1]]
    c = points[faces[:, 2]]
    valid = np.linalg.norm(np.cross(b - a, c - a), axis=1) > tolerance * tolerance
    faces = faces[valid]
    canonical = np.sort(faces, axis=1)
    _, unique_indices = np.unique(canonical, axis=0, return_index=True)
    faces = faces[np.sort(unique_indices)]
    face_data = np.hstack((np.full((len(faces), 1), 3, dtype=np.int64), faces)).ravel()
    repaired = pv.PolyData(points, face_data).clean(point_merging=True, tolerance=tolerance, absolute=True)
    validation = validate_mesh(repaired, tolerance)
    if validation["isWatertight"] and validation["signedVolumeMm3"] < 0:
        repaired.flip_faces(inplace=True)
    return repaired


def mesh_bounds_statistics(mesh: pv.PolyData, requested_sizes: np.ndarray | None = None) -> dict:
    """Return actual bounds and maximum excess beyond requested box dimensions."""
    bounds = np.asarray(mesh.bounds, dtype=float)
    actual = np.asarray([bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]])
    stats = {
        "boundsMinX": float(bounds[0]), "boundsMaxX": float(bounds[1]),
        "boundsMinY": float(bounds[2]), "boundsMaxY": float(bounds[3]),
        "boundsMinZ": float(bounds[4]), "boundsMaxZ": float(bounds[5]),
        "actualSizeX": float(actual[0]), "actualSizeY": float(actual[1]), "actualSizeZ": float(actual[2]),
    }
    if requested_sizes is None:
        stats.update({"requestedSizeX": None, "requestedSizeY": None, "requestedSizeZ": None, "maximumBoundaryOvershootMm": 0.0})
        return stats
    requested = np.asarray(requested_sizes, dtype=float)
    half = requested * 0.5
    overshoots = [
        max(0.0, -half[0] - bounds[0]), max(0.0, bounds[1] - half[0]),
        max(0.0, -half[1] - bounds[2]), max(0.0, bounds[3] - half[1]),
        max(0.0, -half[2] - bounds[4]), max(0.0, bounds[5] - half[2]),
    ]
    stats.update({
        "requestedSizeX": float(requested[0]), "requestedSizeY": float(requested[1]), "requestedSizeZ": float(requested[2]),
        "maximumBoundaryOvershootMm": float(max(overshoots)),
    })
    return stats


def build_generation_metadata(
    args: argparse.Namespace,
    points: np.ndarray,
    voronoi_vertex_count: int,
    all_edges_before_filtering: int,
    final_edges: list[tuple[np.ndarray, np.ndarray]],
    optimization_stats: OptimizationStats,
    graph_stats: dict,
    export_mesh: pv.PolyData,
    validation_before: dict,
    validation_after: dict,
    requested_sizes: np.ndarray | None,
    removed_component_count: int,
    removed_component_strut_count: int,
) -> dict:
    """Build reproducible JSON metadata for the generated export."""
    lengths = np.asarray([np.linalg.norm(end - start) for start, end in final_edges], dtype=float)
    statistics = {
        "seedCount": int(len(points)),
        "voronoiVertexCount": int(voronoi_vertex_count),
        "strutCountBeforeFiltering": int(all_edges_before_filtering),
        "strutCountAfterFiltering": int(len(final_edges)),
        "removedShortStrutCount": int(optimization_stats.removed_short_edges),
        "nodeCount": int(graph_stats["nodeCount"]),
        "minimumStrutLengthMm": float(np.min(lengths)) if len(lengths) else 0.0,
        "maximumStrutLengthMm": float(np.max(lengths)) if len(lengths) else 0.0,
        "averageStrutLengthMm": float(np.mean(lengths)) if len(lengths) else 0.0,
        "medianStrutLengthMm": float(np.median(lengths)) if len(lengths) else 0.0,
        "totalStrutLengthMm": float(np.sum(lengths)),
        **graph_stats,
        "removedComponentCount": int(removed_component_count),
        "removedComponentStrutCount": int(removed_component_strut_count),
        "meshVertexCount": int(export_mesh.n_points),
        "meshTriangleCount": int(export_mesh.n_cells),
        **mesh_bounds_statistics(export_mesh, requested_sizes),
    }
    dimensions = None if requested_sizes is None else {
        "x": float(requested_sizes[0]), "y": float(requested_sizes[1]), "z": float(requested_sizes[2])
    }
    return {
        "generatorVersion": "0.2.0",
        "units": "mm",
        "sourceType": "parametric-box" if requested_sizes is not None else ("imported-stl" if args.input_stl else args.shape),
        "dimensionsMm": dimensions,
        "seedCount": int(args.points),
        "randomSeed": int(args.random_seed),
        "strutDiameterMm": float(args.tube_radius * 2.0),
        "minimumStrutLengthMm": float(args.min_strut_length_mm),
        "boundaryMode": args.boundary_mode,
        "removeDisconnectedComponents": bool(args.remove_disconnected_components),
        "statistics": statistics,
        "meshValidationBeforeRepair": validation_before,
        "meshValidation": validation_after,
    }


def export_stl(mesh: pv.PolyData, output_path: str | Path) -> None:
    """Export the generated mesh as STL."""
    if mesh.n_points == 0:
        raise ValueError("Tube mesh is empty; nothing to export.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    mesh.save(output)
    print(f"Exported STL: {output.resolve()}")


def print_mesh_summary(
    edges: list[tuple[np.ndarray, np.ndarray]],
    connector_edges: list[tuple[np.ndarray, np.ndarray]],
    support_edges: list[tuple[np.ndarray, np.ndarray]],
    optimization_stats: OptimizationStats,
    surface_seed_count: int,
    tube_mesh: pv.PolyData,
    connector_mesh: pv.PolyData,
    shell_mesh: pv.PolyData,
    node_mesh: pv.PolyData,
    export_mesh: pv.PolyData,
) -> None:
    """Print a compact generation summary for slicer/debug checks."""
    print(
        "Generated "
        f"raw_edges={optimization_stats.raw_edges} "
        f"body_edges={optimization_stats.inside_edges} "
        f"removed_short_edges={optimization_stats.removed_short_edges} "
        f"collapsed_short_edges={optimization_stats.collapsed_short_edges} "
        f"inside_edges={len(edges)} "
        f"connector_edges={len(connector_edges)} "
        f"support_edges={len(support_edges)} "
        f"surface_seeds={surface_seed_count} "
        f"tube_cells={tube_mesh.n_cells} "
        f"connector_cells={connector_mesh.n_cells} "
        f"surface_shell_cells={shell_mesh.n_cells} "
        f"node_cells={node_mesh.n_cells} "
        f"combined_cells={export_mesh.n_cells} "
        f"combined_points={export_mesh.n_points}"
    )


def show_scene(
    shape: str,
    points: np.ndarray,
    edges: list[tuple[np.ndarray, np.ndarray]],
    tube_mesh: pv.PolyData,
    connector_mesh: pv.PolyData,
    shell_mesh: pv.PolyData,
    node_mesh: pv.PolyData,
    debug: bool = False,
) -> None:
    """Show the shell, tube mesh and optional debug seed points / lines."""
    plotter = pv.Plotter(window_size=(1100, 850))
    plotter.set_background("#111820")

    if shell_mesh.n_points > 0:
        plotter.add_mesh(shell_mesh, color="#9fb0b8", smooth_shading=True)

    if tube_mesh.n_points > 0:
        plotter.add_mesh(tube_mesh, color="#34302a", smooth_shading=True)

    if connector_mesh.n_points > 0:
        plotter.add_mesh(connector_mesh, color="#5d5548", smooth_shading=True)

    if node_mesh.n_points > 0:
        plotter.add_mesh(node_mesh, color="#2f2a24", smooth_shading=True)

    if debug:
        plotter.add_points(
            points,
            color="#55d6be",
            point_size=9,
            render_points_as_spheres=True,
        )

        for start, end in edges:
            plotter.add_mesh(pv.Line(start, end), color="#f2c46d", line_width=2)

    plotter.add_axes()
    plotter.add_text(
        f"3D Voronoi tubes inside {shape} | seeds: {len(points)} | edges: {len(edges)}",
        position="upper_left",
        font_size=11,
    )
    plotter.show()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voronoi tube MVP")
    parser.add_argument("--shape", choices=["sphere", "box"], default="box", help="Implicit body shape.")
    parser.add_argument("--input-stl", default="", help="Deprecated alias for --input-mesh.")
    parser.add_argument("--input-mesh", default="", help="Optional closed STL or OBJ volume domain.")
    parser.add_argument("--source-original-name", default="", help="Original upload name stored in metadata only.")
    parser.add_argument("--import-scale", type=float, default=1.0, help="Explicit STL/OBJ scale applied before all calculations.")
    parser.add_argument(
        "--component-mode",
        choices=["require-single", "keep-largest", "use-all-closed"],
        default="require-single",
        help="How multiple closed input components are handled.",
    )
    parser.add_argument(
        "--final-component-mode",
        choices=["keep-all", "keep-largest"],
        default="keep-all",
        help="Keep every output component or only the largest polygonal component.",
    )
    parser.add_argument("--boundary-offset-mm", type=float, default=0.0, help="Minimum seed distance from the imported surface.")
    parser.add_argument("--target-cell-size-mm", type=float, default=0.0, help="Estimate imported-mesh seed count from enclosed volume.")
    parser.add_argument("--maximum-sampling-attempts", type=int, default=1_000_000)
    parser.add_argument(
        "--boundary-structure-mode",
        choices=["open-volume", "conformal-surface"],
        default="open-volume",
    )
    parser.add_argument("--surface-sampling-mode", choices=["automatic", "custom"], default="automatic")
    parser.add_argument("--surface-sampling-step-mm", type=float, default=0.0)
    parser.add_argument("--surface-strut-diameter-mm", type=float, default=0.0)
    parser.add_argument("--surface-node-radius-mode", choices=["automatic", "custom"], default="automatic")
    parser.add_argument("--surface-node-radius-mm", type=float, default=0.0)
    parser.add_argument(
        "--surface-placement-mode",
        choices=["inset-inside", "on-surface-clipped"],
        default="inset-inside",
    )
    parser.add_argument("--surface-inset-mode", choices=["automatic", "custom"], default="automatic")
    parser.add_argument("--surface-inset-mm", type=float, default=0.0)
    parser.add_argument("--surface-smoothing-iterations", type=int, default=2)
    parser.add_argument("--surface-smoothing-strength", type=float, default=0.35)
    parser.add_argument("--connect-surface-to-interior", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--surface-connector-spacing-mm", type=float, default=5.0)
    parser.add_argument("--surface-connector-maximum-length-mm", type=float, default=15.0)
    parser.add_argument("--surface-connector-diameter-mm", type=float, default=0.0)
    parser.add_argument("--minimum-connectors-per-surface-component", type=int, default=1)
    parser.add_argument("--maximum-surface-working-triangles", type=int, default=300_000)
    parser.add_argument("--surface-topology-weld-reference-mm", type=float, default=0.0)
    parser.add_argument("--points", type=int, default=80, help="Number of random seed points inside the body.")
    parser.add_argument("--radius", type=float, default=1.0, help="Sphere radius or box half-size.")
    parser.add_argument("--box-size-x", type=float, default=0.0, help="Optional box X size in mm for parametric Voronoi boxes.")
    parser.add_argument("--box-size-y", type=float, default=0.0, help="Optional box Y size in mm for parametric Voronoi boxes.")
    parser.add_argument("--box-size-z", type=float, default=0.0, help="Optional box Z size in mm for parametric Voronoi boxes.")
    parser.add_argument("--tube-radius", type=float, default=0.025, help="Radius of generated tube struts.")
    parser.add_argument(
        "--surface-points",
        type=int,
        default=0,
        help="Number of seed points for surface Voronoi casing. Use 0 for automatic density.",
    )
    parser.add_argument("--surface-tube-radius", type=float, default=0.026, help="Radius of surface Voronoi casing struts.")
    parser.add_argument(
        "--min-strut-length",
        type=float,
        default=0.06,
        help="Minimum inner/surface strut length, relative to radius.",
    )
    parser.add_argument(
        "--min-strut-length-mm",
        type=float,
        default=0.0,
        help="Absolute minimum inner/surface strut length in mm. Overrides --min-strut-length when > 0.",
    )
    parser.add_argument("--no-optimize", action="store_true", help="Keep tiny struts instead of running automatic cleanup.")
    parser.add_argument(
        "--connector-min-length",
        type=float,
        default=0.08,
        help="Minimum connector strut length, relative to radius.",
    )
    parser.add_argument(
        "--support-max-length",
        type=float,
        default=0.28,
        help="Maximum support strut length for low-degree inner endpoints, relative to radius.",
    )
    parser.add_argument(
        "--node-radius-scale",
        type=float,
        default=1.0,
        help="Endpoint sphere radius multiplier relative to the connected strut radius.",
    )
    parser.add_argument("--no-nodes", action="store_true", help="Skip endpoint spheres at strut joints.")
    parser.add_argument("--no-supports", action="store_true", help="Skip stabilizing support struts for dangling endpoints.")
    parser.add_argument(
        "--connector-band",
        type=float,
        default=0.35,
        help="Near-boundary band used to connect inner lattice endpoints to the surface, relative to radius.",
    )
    parser.add_argument(
        "--connector-max-length",
        type=float,
        default=0.55,
        help="Maximum connector strut length, relative to radius.",
    )
    parser.add_argument("--random-seed", type=int, default=42, help="Random seed for repeatable results.")
    parser.add_argument(
        "--boundary-mode",
        choices=["centerline", "exact"],
        default="exact",
        help="Keep only centerlines inside the box or keep the complete swept geometry inside it.",
    )
    parser.add_argument(
        "--mesh-engine",
        choices=["legacy-primitives", "implicit-union"],
        default="legacy-primitives",
        help="Polygonal preview primitives or a unified signed-distance-field mesh.",
    )
    parser.add_argument(
        "--quality-preset",
        choices=["preview", "standard", "high", "custom"],
        default="standard",
        help="Voxel resolution preset for implicit union meshing.",
    )
    parser.add_argument(
        "--voxel-size-mm",
        type=float,
        default=0.0,
        help="Custom voxel size in millimeters when --quality-preset=custom.",
    )
    parser.add_argument(
        "--boundary-tolerance",
        type=float,
        default=0.02,
        help="Allowed numerical box-boundary tolerance in mm.",
    )
    parser.add_argument(
        "--remove-disconnected-components",
        action="store_true",
        help="Keep only the largest connected component of the strut graph.",
    )
    parser.add_argument("--debug", action="store_true", help="Show original seed points and Voronoi lines.")
    parser.add_argument("--no-shell", action="store_true", help="Export and show only inner Voronoi tubes without surface casing.")
    parser.add_argument("--surface-only", action="store_true", help="Export only the surface lattice shell.")
    parser.add_argument("--no-show", action="store_true", help="Generate and export without opening a PyVista window.")
    parser.add_argument(
        "--export-stl",
        default="exports/voronoi_lattice_with_surface.stl",
        help="Output STL path. Use an empty string to skip export.",
    )
    parser.add_argument("--metadata-json", default="", help="Optional path for reproducibility and validation metadata.")
    parser.add_argument("--debug-mode", choices=["none", "requested", "all"], default="none")
    parser.add_argument("--debug-layers", default="", help="Comma-separated debug layer names.")
    parser.add_argument("--debug-maximum-points", type=int, default=100_000)
    parser.add_argument("--debug-maximum-segments", type=int, default=200_000)
    parser.add_argument("--debug-manifest-json", default="")
    parser.add_argument("--debug-buffer-bin", default="")
    parser.add_argument("--cache-enabled", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--cache-directory", default="cache")
    parser.add_argument("--cache-maximum-size-gib", type=float, default=5.0)
    parser.add_argument("--cache-maximum-age-days", type=float, default=30.0)
    parser.add_argument("--material-density-g-per-cm3", type=float, default=0.0)
    return parser.parse_args(argv)


def map_implicit_progress(phase: str, fraction: float | None) -> float:
    local_fraction = min(1.0, max(0.0, float(fraction or 0.0)))
    phase_ranges = {
        "memory-preflight": (0.48, 0.50),
        "generating-final-mesh": (0.50, 0.72),
        "clipping-interior": (0.72, 0.82),
        "extracting-surface": (0.82, 0.84),
    }
    start, end = phase_ranges.get(phase, (0.48, 0.84))
    return start + (end - start) * local_fraction


def main(
    argv: list[str] | None = None,
    runtime_context: WorkerRuntime | None = None,
) -> dict:
    overall_started = perf_counter()
    args = parse_args(argv)
    cancellation_token = runtime_context.cancellation_token if runtime_context is not None else None

    def checkpoint() -> None:
        if cancellation_token is not None:
            cancellation_token.check()

    def report(phase: str, message: str, fraction: float | None = None, **metrics) -> None:
        if runtime_context is not None:
            runtime_context.report(phase, message, fraction, **metrics)

    report("job-start", "Spouštím generování geometrie.", 0.0)
    cache = CacheStore(
        args.cache_directory,
        enabled=args.cache_enabled,
        maximum_size_gib=max(args.cache_maximum_size_gib, 0.01),
        maximum_age_days=max(args.cache_maximum_age_days, 0.01),
    )
    cache_events: dict[str, dict] = {}

    def cache_get(level: str, key: str, expected: dict | None = None):
        checkpoint()
        started = perf_counter()
        value = runtime_context.memory_get(level, key) if runtime_context is not None else None
        memory_hit = value is not None
        if value is None:
            report("loading-disk-cache", f"Načítám diskovou cache: {level}.")
            value = cache.get(level, key, expected)
            if value is not None and runtime_context is not None:
                runtime_context.memory_put(level, key, value)
        cache_events[level] = {
            "hit": value is not None,
            "memoryHit": memory_hit,
            "keyPrefix": key[:12],
            "loadTimeSeconds": float(perf_counter() - started),
        }
        return value

    def cache_put(level: str, key: str, arrays: dict):
        checkpoint()
        started = perf_counter()
        cache.put(level, key, arrays)
        if runtime_context is not None:
            runtime_context.memory_put(level, key, arrays)
        event = cache_events.setdefault(level, {"hit": False, "keyPrefix": key[:12], "loadTimeSeconds": 0.0})
        event["writeTimeSeconds"] = float(perf_counter() - started)

    input_mesh_path = args.input_mesh or args.input_stl
    report("reading-input", "Čtu a ověřuji vstupní model.", 0.02)
    source_hash = (
        file_content_hash(input_mesh_path)
        if input_mesh_path
        else canonical_hash({"shape": args.shape, "radius": args.radius, "box": [args.box_size_x, args.box_size_y, args.box_size_z]})
    )
    if runtime_context is not None:
        runtime_context.activate(
            build_topology_session_key(source_hash, args),
            "imported-mesh" if input_mesh_path else f"parametric-{args.shape}",
        )
        report(
            "loading-memory-session",
            "RAM topologická session nalezena." if runtime_context.session_hit else "Zakládám RAM topologickou session.",
            0.03,
            memoryCacheHit=runtime_context.session_hit,
        )
    input_validation: dict | None = None
    seed_sampling: dict | None = None
    domain_clipping: dict | None = None
    triangle_domain: TriangleMeshDomain | None = None
    body_mesh = None
    if input_mesh_path:
        report("building-domain", "Připravuji TriangleMeshDomain a prostorový locator.", 0.05)
        domain_started = perf_counter()

        def build_triangle_domain():
            loaded_mesh, loaded_validation = load_triangle_mesh(input_mesh_path, args.import_scale)
            return TriangleMeshDomain(loaded_mesh, args.component_mode, loaded_validation), loaded_validation

        if runtime_context is not None:
            domain_pair, domain_reused = runtime_context.get_or_create("triangle-domain", build_triangle_domain)
            runtime_context.domain_reused = domain_reused
            runtime_context.locator_reused = domain_reused
            triangle_domain, loaded_validation = domain_pair
        else:
            triangle_domain, loaded_validation = build_triangle_domain()
        body_mesh = triangle_domain.mesh
        input_validation = {**loaded_validation, **triangle_domain.validate()}
        input_validation["domainBuildAndValidationTimeSeconds"] = float(perf_counter() - domain_started)
        if args.target_cell_size_mm > 0:
            estimated_count = int(round(input_validation["absoluteVolumeMm3"] / args.target_cell_size_mm**3))
            args.points = int(np.clip(estimated_count, 5, 5000))
    cache_parameters = {
        "format": Path(input_mesh_path).suffix.lower() if input_mesh_path else args.shape,
        "importScale": args.import_scale,
        "componentMode": args.component_mode,
        "seedCount": args.points,
        "targetCellSizeMm": args.target_cell_size_mm,
        "randomSeed": args.random_seed,
        "boundaryOffsetMm": args.boundary_offset_mm,
        "minimumPreliminaryStrutLength": args.min_strut_length_mm * 0.15,
        "minimumStrutLengthMm": args.min_strut_length_mm,
        "surfaceSamplingStepMm": args.surface_sampling_step_mm if args.surface_sampling_mode == "custom" else "automatic",
        "surfaceSmoothingIterations": args.surface_smoothing_iterations,
        "surfaceSmoothingStrength": args.surface_smoothing_strength,
        "surfacePlacementMode": args.surface_placement_mode,
        "surfaceInsetMode": args.surface_inset_mode,
        "surfaceInsetMm": args.surface_inset_mm,
        "surfaceStrutDiameterMm": args.surface_strut_diameter_mm,
        "surfaceTopologyWeldReferenceMm": args.surface_topology_weld_reference_mm,
        "connectorSpacingMm": args.surface_connector_spacing_mm,
        "connectorMaximumLengthMm": args.surface_connector_maximum_length_mm,
        "connectorDiameterMm": args.surface_connector_diameter_mm,
        "strutDiameterMm": args.tube_radius * 2.0,
        "nodeRadiusScale": args.node_radius_scale,
        "voxelSizeMm": args.voxel_size_mm if args.quality_preset == "custom" else args.quality_preset,
        "finalComponentMode": args.final_component_mode,
    }
    cache_keys = build_cache_keys(
        source_hash,
        cache_parameters,
        conformal=args.boundary_structure_mode == "conformal-surface",
    )
    shape = "mesh" if body_mesh is not None else args.shape
    body_domain: float | np.ndarray
    if body_mesh is not None:
        bounds = np.asarray(body_mesh.bounds, dtype=float)
        extents = np.asarray([bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]])
        body_radius = float(np.max(extents) * 0.5) or args.radius
        body_domain = body_radius
        if args.surface_only:
            points = np.empty((0, 3))
        else:
            cached_seeds = cache_get("seeds", cache_keys["seeds"], {"points": (None, 3)})
            if cached_seeds is not None:
                points = cached_seeds["points"]
                seed_sampling = {
                    "cacheHit": True,
                    "acceptedSeedCount": int(len(points)),
                    "requestedSeedCount": int(args.points),
                }
            else:
                report("generating-seeds", "Generuji seed body uvnitř domény.", 0.10)
                sampled = generate_points_in_domain(
                    triangle_domain,
                    args.points,
                    args.random_seed,
                    args.boundary_offset_mm,
                    args.maximum_sampling_attempts,
                    cancellation_token=cancellation_token,
                )
                points = sampled.points
                seed_sampling = sampled.metadata
                cache_put("seeds", cache_keys["seeds"], {"points": points})
    else:
        if shape == "box" and min(args.box_size_x, args.box_size_y, args.box_size_z) > 0:
            body_domain = np.asarray([args.box_size_x, args.box_size_y, args.box_size_z], dtype=float) * 0.5
            body_radius = box_reference_radius(body_domain)
        else:
            body_domain = args.radius
            body_radius = args.radius
        if args.surface_only:
            points = np.empty((0, 3))
        else:
            cached_seeds = cache_get("seeds", cache_keys["seeds"], {"points": (None, 3)})
            if cached_seeds is not None:
                points = cached_seeds["points"]
            else:
                points = generate_body_points(shape, args.points, body_domain, args.random_seed)
                cache_put("seeds", cache_keys["seeds"], {"points": points})

    checkpoint()
    report("computing-voronoi", "Počítám 3D Voronoi topologii.", 0.16)
    voronoi_started = perf_counter()
    if args.surface_only:
        edges = []
    elif triangle_domain is not None:
        cached_voronoi = cache_get("volume-voronoi", cache_keys["volume-voronoi"], {"edges": (None, 2, 3)})
        if cached_voronoi is not None:
            edges = [(edge[0], edge[1]) for edge in cached_voronoi["edges"]]
        else:
            domain_minimum, domain_maximum = triangle_domain.bounds()
            edges = compute_voronoi_edges_with_ghost_seeds(points, domain_minimum, domain_maximum)
            cache_put("volume-voronoi", cache_keys["volume-voronoi"], {"edges": np.asarray(edges, dtype=float).reshape((-1, 2, 3))})
    else:
        cached_voronoi = cache_get("volume-voronoi", cache_keys["volume-voronoi"], {"edges": (None, 2, 3)})
        if cached_voronoi is not None:
            edges = [(edge[0], edge[1]) for edge in cached_voronoi["edges"]]
        else:
            edges = compute_voronoi_edges(points)
            cache_put("volume-voronoi", cache_keys["volume-voronoi"], {"edges": np.asarray(edges, dtype=float).reshape((-1, 2, 3))})
    voronoi_seconds = perf_counter() - voronoi_started
    voronoi_vertex_count = 0 if args.surface_only else compute_voronoi_vertex_count(points)
    min_strut_length = 0.0 if args.no_optimize else (args.min_strut_length_mm if args.min_strut_length_mm > 0 else args.min_strut_length * body_radius)
    connector_min_length = 0.0 if args.no_optimize else args.connector_min_length * body_radius
    surface_seed_count = resolve_surface_seed_count(shape, args.surface_points, args.points)
    if args.surface_only:
        inside_edges = []
        optimization_stats = OptimizationStats(raw_edges=0, inside_edges=0, removed_short_edges=0)
    elif triangle_domain is not None:
        cached_clipped = cache_get("clipped-interior", cache_keys["clipped-interior"], {"edges": (None, 2, 3)})
        if cached_clipped is not None:
            inside_edges = [(edge[0], edge[1]) for edge in cached_clipped["edges"]]
            prefiltered_edges = edges
            cached_endpoints = unique_edge_points(inside_edges, decimals=6)
            endpoint_distances = (
                np.abs(triangle_domain.signed_distance(np.asarray(cached_endpoints)))
                if len(cached_endpoints)
                else np.empty(0)
            )
            domain_clipping = {
                "inputSegmentCount": int(len(edges)),
                "outputIntervalCount": int(len(inside_edges)),
                "removedShortIntervalCount": 0,
                "surfaceIntersectionNodeCount": int(np.count_nonzero(endpoint_distances <= max(args.tube_radius, 0.02))),
                "cacheHit": True,
            }
        else:
            prefiltered_edges = filter_edges_by_length(edges, min_strut_length * 0.15) if not args.no_optimize else edges
            imported_voxel_size = resolve_voxel_size(args.tube_radius * 2.0, args.quality_preset, args.voxel_size_mm)
            report("clipping-interior", "Ořezávám vnitřní Voronoi hrany podle tělesa.", 0.24)
            inside_edges, domain_clipping = clip_edges_to_domain(
                prefiltered_edges,
                triangle_domain,
                min(imported_voxel_size, args.tube_radius * 0.5),
                min_strut_length,
                cancellation_token=cancellation_token,
            )
            cache_put("clipped-interior", cache_keys["clipped-interior"], {"edges": np.asarray(inside_edges, dtype=float).reshape((-1, 2, 3))})
        optimization_stats = OptimizationStats(
            raw_edges=len(edges),
            inside_edges=len(inside_edges),
            removed_short_edges=len(edges) - len(prefiltered_edges) + domain_clipping["removedShortIntervalCount"],
        )
    else:
        cached_clipped = cache_get("clipped-interior", cache_keys["clipped-interior"], {"edges": (None, 2, 3)})
        if cached_clipped is not None:
            inside_edges = [(edge[0], edge[1]) for edge in cached_clipped["edges"]]
            optimization_stats = OptimizationStats(raw_edges=len(edges), inside_edges=len(inside_edges), removed_short_edges=0)
        else:
            inside_edges, optimization_stats = optimize_strut_network(
                shape,
                edges,
                body_domain,
                min_strut_length,
                enabled=not args.no_optimize,
            )
            cache_put("clipped-interior", cache_keys["clipped-interior"], {"edges": np.asarray(inside_edges, dtype=float).reshape((-1, 2, 3))})

    conformal_result = None
    conformal_surface_radius = args.surface_tube_radius
    conformal_connector_radius = args.tube_radius
    conformal_node_radius = args.surface_tube_radius * args.node_radius_scale
    if (
        triangle_domain is not None
        and args.boundary_structure_mode == "conformal-surface"
        and not args.no_shell
        and not args.surface_only
    ):
        report("creating-conformal-surface", "Vytvářím konformní povrchovou Voronoi síť.", 0.34)
        surface_diameter = args.surface_strut_diameter_mm if args.surface_strut_diameter_mm > 0 else args.tube_radius * 2.0
        conformal_surface_radius = surface_diameter * 0.5
        conformal_connector_radius = (
            args.surface_connector_diameter_mm * 0.5
            if args.surface_connector_diameter_mm > 0
            else args.tube_radius
        )
        conformal_node_radius = (
            args.surface_node_radius_mm
            if args.surface_node_radius_mode == "custom" and args.surface_node_radius_mm > 0
            else conformal_surface_radius * args.node_radius_scale
        )
        characteristic_cell_size = (
            args.target_cell_size_mm
            if args.target_cell_size_mm > 0
            else float((input_validation["absoluteVolumeMm3"] / max(len(points), 1)) ** (1.0 / 3.0))
        )
        automatic_sampling_step = min(characteristic_cell_size / 4.0, surface_diameter / 2.0)
        sampling_step = (
            args.surface_sampling_step_mm
            if args.surface_sampling_mode == "custom" and args.surface_sampling_step_mm > 0
            else automatic_sampling_step
        )
        sampling_step = float(np.clip(sampling_step, 0.05, max(characteristic_cell_size, 0.05)))
        inset = (
            args.surface_inset_mm
            if args.surface_inset_mode == "custom"
            else conformal_surface_radius
        )
        surface_parameters = SurfaceVoronoiParameters(
            sampling_step_mm=sampling_step,
            strut_radius_mm=conformal_surface_radius,
            node_radius_mm=conformal_node_radius,
            placement_mode=args.surface_placement_mode,
            inset_mm=max(0.0, inset),
            smoothing_iterations=max(0, args.surface_smoothing_iterations),
            smoothing_strength=float(np.clip(args.surface_smoothing_strength, 0.0, 1.0)),
            connector_spacing_mm=max(args.surface_connector_spacing_mm, 1e-6),
            connector_maximum_length_mm=max(args.surface_connector_maximum_length_mm, 0.0),
            connector_radius_mm=conformal_connector_radius,
            minimum_connectors_per_component=max(0, args.minimum_connectors_per_surface_component),
            maximum_working_triangles=max(100, args.maximum_surface_working_triangles),
            topology_weld_reference_mm=max(0.0, args.surface_topology_weld_reference_mm),
        )
        cached_surface = cache_get("placed-surface", cache_keys["placed-surface"])
        if cached_surface is not None:
            decode_edges = lambda name: [(edge[0], edge[1]) for edge in cached_surface[name]]
            cached_metadata = json.loads(bytes(cached_surface["metadata"].astype(np.uint8)).decode("utf-8"))
            conformal_result = SurfaceVoronoiResult(
                decode_edges("raw"),
                decode_edges("smoothed"),
                decode_edges("placed"),
                cached_surface["surface_nodes"],
                decode_edges("connectors"),
                cached_surface["connector_nodes"],
                cached_metadata,
            )
        else:
            cached_surface_graph = cache_get("surface-graph", cache_keys["surface-graph"])
            if cached_surface_graph is not None:
                decode_graph_edges = lambda name: [(edge[0], edge[1]) for edge in cached_surface_graph[name]]
                base_surface_metadata = json.loads(bytes(cached_surface_graph["metadata"].astype(np.uint8)).decode("utf-8"))
                conformal_result = place_conformal_surface_graph(
                    triangle_domain,
                    inside_edges,
                    surface_parameters,
                    decode_graph_edges("raw"),
                    decode_graph_edges("smoothed"),
                    base_surface_metadata,
                    connect_to_interior=args.connect_surface_to_interior,
                )
            else:
                conformal_result = generate_conformal_surface(
                    triangle_domain,
                    points,
                    inside_edges,
                    surface_parameters,
                    connect_to_interior=args.connect_surface_to_interior,
                )
                base_surface_metadata = {
                    "surfaceVoronoiStatistics": conformal_result.metadata["surfaceVoronoiStatistics"],
                    "surfaceGraph": conformal_result.metadata["surfaceGraph"],
                }
                cache_put("surface-graph", cache_keys["surface-graph"], {
                    "raw": np.asarray(conformal_result.raw_surface_segments, dtype=float).reshape((-1, 2, 3)),
                    "smoothed": np.asarray(conformal_result.smoothed_surface_segments, dtype=float).reshape((-1, 2, 3)),
                    "metadata": np.frombuffer(json.dumps(base_surface_metadata).encode("utf-8"), dtype=np.uint8),
                })
            cache_put("placed-surface", cache_keys["placed-surface"], {
                "raw": np.asarray(conformal_result.raw_surface_segments, dtype=float).reshape((-1, 2, 3)),
                "smoothed": np.asarray(conformal_result.smoothed_surface_segments, dtype=float).reshape((-1, 2, 3)),
                "placed": np.asarray(conformal_result.surface_segments, dtype=float).reshape((-1, 2, 3)),
                "surface_nodes": np.asarray(conformal_result.surface_nodes, dtype=float).reshape((-1, 3)),
                "connectors": np.asarray(conformal_result.connector_segments, dtype=float).reshape((-1, 2, 3)),
                "connector_nodes": np.asarray(conformal_result.connector_nodes, dtype=float).reshape((-1, 3)),
                "metadata": np.frombuffer(json.dumps(conformal_result.metadata).encode("utf-8"), dtype=np.uint8),
            })

    if args.no_shell:
        shell_mesh = pv.PolyData()
        surface_edges: list[tuple[np.ndarray, np.ndarray]] = []
    elif body_mesh is not None:
        shell_mesh = pv.PolyData()
        surface_edges = conformal_result.surface_segments if conformal_result is not None else []
    else:
        shell_mesh, surface_edges = create_surface_shell(
            shape,
            body_domain,
            surface_seed_count,
            args.surface_tube_radius,
            args.random_seed + 1000,
            min_strut_length,
        )

    connector_edges = (
        conformal_result.connector_segments
        if conformal_result is not None
        else []
        if args.surface_only or body_mesh is not None
        else create_connection_edges(
            shape,
            inside_edges,
            surface_edges,
            body_domain,
            args.connector_band * body_radius,
            args.connector_max_length * body_radius,
            connector_min_length,
            body_mesh,
        )
    )
    if not args.no_optimize and not args.surface_only and body_mesh is None:
        [inside_edges, connector_edges, surface_edges], global_collapsed = collapse_short_edges_across_groups(
            [inside_edges, connector_edges, surface_edges],
            min_strut_length,
        )
        if global_collapsed:
            optimization_stats = OptimizationStats(
                raw_edges=optimization_stats.raw_edges,
                inside_edges=optimization_stats.inside_edges,
                removed_short_edges=optimization_stats.removed_short_edges,
                collapsed_short_edges=optimization_stats.collapsed_short_edges + global_collapsed,
            )
            if body_mesh is not None:
                inside_edges = filter_edges_inside_mesh(inside_edges, body_mesh)
                connector_edges = [
                    (start, end)
                    for start, end in connector_edges
                    if edge_stays_inside_mesh(start, end, body_mesh) or edge_stays_inside_mesh(end, start, body_mesh)
                ]
            else:
                inside_edges = filter_edges_inside_body(shape, inside_edges, body_domain)
                connector_edges = filter_edges_inside_body(shape, connector_edges, body_domain)

    support_edges = (
        []
        if args.no_supports or shape != "box"
        else create_dangling_support_edges(
            inside_edges + connector_edges,
            surface_edges,
            body_domain,
            connector_min_length,
            args.support_max_length * body_radius,
        )
    )

    removed_component_count = 0
    removed_component_strut_count = 0
    if args.remove_disconnected_components:
        [inside_edges, connector_edges, support_edges, surface_edges], removed_component_count, removed_component_strut_count = keep_largest_graph_component(
            [inside_edges, connector_edges, support_edges, surface_edges]
        )

    used_mesh_engine = args.mesh_engine

    if used_mesh_engine == "legacy-primitives" and shape == "box" and args.boundary_mode == "exact":
        inner_node_radius = args.tube_radius * args.node_radius_scale if not args.no_nodes else args.tube_radius
        surface_node_radius = args.surface_tube_radius * args.node_radius_scale if not args.no_nodes else args.surface_tube_radius
        exact_inset_radius = max(args.tube_radius, args.surface_tube_radius, inner_node_radius, surface_node_radius)
        inside_edges = clip_final_geometry_to_domain(inside_edges, shape, body_domain, exact_inset_radius, args.boundary_mode)
        connector_edges = clip_final_geometry_to_domain(connector_edges, shape, body_domain, exact_inset_radius, args.boundary_mode)
        support_edges = clip_final_geometry_to_domain(support_edges, shape, body_domain, exact_inset_radius, args.boundary_mode)
        surface_edges = clip_final_geometry_to_domain(surface_edges, shape, body_domain, exact_inset_radius, args.boundary_mode)

    all_final_edges = inside_edges + connector_edges + support_edges + surface_edges
    graph_stats = analyze_strut_graph(all_final_edges)
    implicit_stats: dict = {"enabled": False}
    cleanup_seconds = 0.0
    validation_seconds = 0.0

    voxel_size = resolve_voxel_size(args.tube_radius * 2.0, args.quality_preset, args.voxel_size_mm)
    cached_final_mesh = (
        cache_get("final-mesh", cache_keys["final-mesh"], {"points": (None, 3), "faces": (None,)})
        if used_mesh_engine == "implicit-union"
        else None
    )
    if cached_final_mesh is not None:
        combined_mesh = pv.PolyData(cached_final_mesh["points"], cached_final_mesh["faces"].astype(np.int64))
        implicit_stats = {
            "enabled": True,
            "cacheHit": True,
            "voxelSizeMm": float(voxel_size),
            "gridSizeX": 0,
            "gridSizeY": 0,
            "gridSizeZ": 0,
            "totalVoxelCount": 0,
            "estimatedMemoryBytes": 0,
            "generationTimeSeconds": 0.0,
        }
        tube_mesh = combined_mesh
        shell_mesh = pv.PolyData()
        connector_mesh = pv.PolyData()
        node_mesh = pv.PolyData()
    elif used_mesh_engine == "implicit-union":
        report("generating-final-mesh", "Připravuji implicitní watertight mesh.", 0.48)

        def implicit_progress_callback(*, phase, message, fraction=None, metrics=None):
            report(
                phase,
                message,
                map_implicit_progress(phase, fraction),
                **(metrics or {}),
                phaseFraction=fraction,
            )

        capsules = [
            CapsulePrimitive(np.asarray(start), np.asarray(end), args.tube_radius)
            for start, end in inside_edges + support_edges
        ] + [
            CapsulePrimitive(np.asarray(start), np.asarray(end), conformal_connector_radius)
            for start, end in connector_edges
        ] + [
            CapsulePrimitive(np.asarray(start), np.asarray(end), conformal_surface_radius)
            for start, end in surface_edges
        ]
        node_radii: dict[tuple[float, float, float], tuple[np.ndarray, float]] = {}
        if not args.no_nodes:
            for group_edges, radius in (
                (inside_edges + support_edges, args.tube_radius * args.node_radius_scale),
                (connector_edges, conformal_connector_radius * args.node_radius_scale),
                (surface_edges, conformal_node_radius),
            ):
                for point in unique_edge_points(group_edges, decimals=6):
                    key = point_key_3d(point, decimals=6)
                    previous = node_radii.get(key)
                    if previous is None or radius > previous[1]:
                        node_radii[key] = (np.asarray(point), float(radius))
        spheres = [SpherePrimitive(center, radius) for center, radius in node_radii.values()]
        domain = triangle_domain if triangle_domain is not None else BoxDomain(as_half_sizes(body_domain))
        combined_mesh, implicit_stats = generate_implicit_union_mesh(
            domain,
            capsules,
            spheres,
            voxel_size,
            exact_domain_intersection=triangle_domain is not None or args.boundary_mode == "exact",
            progress_callback=implicit_progress_callback if runtime_context is not None else None,
            cancellation_token=cancellation_token,
        )
        tube_mesh = combined_mesh
        shell_mesh = pv.PolyData()
        connector_mesh = pv.PolyData()
        node_mesh = pv.PolyData()
    else:
        tube_mesh = create_tube_mesh(inside_edges, args.tube_radius)
        shell_mesh = create_tube_mesh(surface_edges, args.surface_tube_radius).clean() if surface_edges else pv.PolyData()
        connector_mesh = create_tube_mesh(connector_edges + support_edges, args.tube_radius)
        if args.no_nodes:
            node_mesh = pv.PolyData()
        else:
            inner_node_mesh = create_node_sphere_mesh(
                inside_edges + connector_edges + support_edges,
                args.tube_radius * args.node_radius_scale,
            )
            surface_node_mesh = create_node_sphere_mesh(surface_edges, args.surface_tube_radius * args.node_radius_scale)
            node_mesh = combine_meshes([inner_node_mesh, surface_node_mesh])
        combined_mesh = combine_meshes([shell_mesh, tube_mesh, connector_mesh, node_mesh])

    final_removed_mesh_components = 0
    if args.final_component_mode == "keep-largest" and combined_mesh.n_cells:
        connected_output = combined_mesh.connectivity()
        output_regions = np.unique(connected_output.cell_data["RegionId"])
        if len(output_regions) > 1:
            largest_output = connected_output.connectivity(extraction_mode="largest").extract_surface().triangulate().clean()
            combined_mesh = pv.PolyData(
                np.asarray(largest_output.points).copy(),
                np.asarray(largest_output.faces).copy(),
            ).clean()
            final_removed_mesh_components = int(len(output_regions) - 1)

    report("validating-final-mesh", "Kontroluji finální geometrii.", 0.85)
    validation_started = perf_counter()
    validation_before = validate_mesh(combined_mesh)
    validation_seconds += perf_counter() - validation_started
    report("repairing-final-mesh", "Opravuji a čistím exportní mesh.", 0.88)
    cleanup_started = perf_counter()
    export_mesh = repair_mesh_for_export(combined_mesh)
    cleanup_seconds = perf_counter() - cleanup_started
    if used_mesh_engine == "implicit-union" and cached_final_mesh is None:
        cache_put("final-mesh", cache_keys["final-mesh"], {
            "points": np.asarray(export_mesh.points),
            "faces": np.asarray(export_mesh.faces),
        })
    report("validating-export", "Ověřuji manifoldnost a hranice exportu.", 0.91)
    validation_started = perf_counter()
    validation_after = validate_mesh(export_mesh)
    validation_seconds += perf_counter() - validation_started
    requested_sizes = as_half_sizes(body_domain) * 2.0 if shape == "box" else None
    metadata = build_generation_metadata(
        args,
        points,
        voronoi_vertex_count,
        len(edges),
        all_final_edges,
        optimization_stats,
        graph_stats,
        export_mesh,
        validation_before,
        validation_after,
        requested_sizes,
        removed_component_count,
        removed_component_strut_count,
    )
    metadata["meshEngine"] = used_mesh_engine
    metadata["clippingImplementation"] = (
        "implicit-sdf-intersection"
        if used_mesh_engine == "implicit-union" and args.boundary_mode == "exact"
        else "eroded-centerline-approximation"
        if used_mesh_engine == "legacy-primitives" and args.boundary_mode == "exact" and shape == "box"
        else "centerline-domain-filter"
    )
    metadata["qualityPreset"] = args.quality_preset
    metadata["voxelSizeMm"] = implicit_stats.get("voxelSizeMm")
    implicit_stats["cleanupTimeSeconds"] = float(cleanup_seconds)
    implicit_stats["validationTimeSeconds"] = float(validation_seconds)
    if implicit_stats.get("enabled"):
        implicit_stats["generationTimeSeconds"] += float(cleanup_seconds + validation_seconds)
    metadata["implicitMeshing"] = implicit_stats
    metadata["meshValidationBeforeCleanup"] = validation_before
    metadata["meshValidationAfterCleanup"] = validation_after
    domain_volume = (
        float(input_validation["absoluteVolumeMm3"])
        if triangle_domain is not None
        else float(np.prod(as_half_sizes(body_domain) * 2.0))
    )
    volume_stats = density_statistics(domain_volume, validation_after.get("componentVolumesMm3", [validation_after["absoluteVolumeMm3"]]))
    metadata["volumeStatistics"] = volume_stats
    metadata["massEstimate"] = mass_estimate(
        volume_stats,
        args.material_density_g_per_cm3 if args.material_density_g_per_cm3 > 0 else None,
    )
    metadata["densityControl"] = {
        "mode": "direct-dimensions",
        "selectedGlobalRadiusScale": 1.0,
        "finalVerifiedDensity": volume_stats["relativeDensity"],
    }
    metadata["cache"] = {
        "enabled": bool(args.cache_enabled),
        **cache_events,
        "hitCount": int(sum(1 for event in cache_events.values() if event.get("hit"))),
        "missCount": int(sum(1 for event in cache_events.values() if not event.get("hit"))),
        "totalCacheReadTimeSeconds": float(sum(event.get("loadTimeSeconds", 0.0) for event in cache_events.values())),
        "totalCacheWriteTimeSeconds": float(sum(event.get("writeTimeSeconds", 0.0) for event in cache_events.values())),
    }
    if runtime_context is not None:
        metadata["executionMode"] = "persistent-worker"
        metadata["memoryCache"] = runtime_context.metadata()
        metadata["worker"] = {
            "sameProcessForAllEvaluations": True,
            "domainReused": runtime_context.domain_reused,
            "locatorReused": runtime_context.locator_reused,
            "topologySessionHit": runtime_context.session_hit,
        }
    if triangle_domain is not None:
        violation_tolerance = max(0.02, float(voxel_size) * 0.25)
        domain_distances = triangle_domain.signed_distance(np.asarray(export_mesh.points))
        outside_mask = domain_distances > violation_tolerance
        source_path = Path(input_mesh_path)
        metadata.update({
            "sourceType": "imported-mesh",
            "sourceFile": {
                "originalName": args.source_original_name or source_path.name,
                "format": input_validation.get("detectedFormat", source_path.suffix.lower().lstrip(".")),
                "fileSizeBytes": int(input_validation.get("fileSizeBytes", source_path.stat().st_size)),
                "importScale": float(args.import_scale),
            },
            "inputMeshValidation": input_validation,
            "componentMode": args.component_mode,
            "finalComponentMode": args.final_component_mode,
            "boundaryStructureMode": args.boundary_structure_mode,
            "removedFinalComponentCount": final_removed_mesh_components,
            "domainType": "triangle-mesh",
            "domain": triangle_domain.metadata(),
            "seedParameters": {
                "seedCount": int(args.points),
                "targetCellSizeMm": float(args.target_cell_size_mm) if args.target_cell_size_mm > 0 else None,
                "randomSeed": int(args.random_seed),
                "boundaryOffsetMm": float(args.boundary_offset_mm),
                "maximumSamplingAttempts": int(args.maximum_sampling_attempts),
            },
            "seedSampling": seed_sampling,
            "voronoiStatistics": {
                "vertexCount": int(voronoi_vertex_count),
                "rawEdgeCount": int(len(edges)),
                "generationTimeSeconds": float(voronoi_seconds),
            },
            "domainClipping": domain_clipping,
            "outputMeshValidation": validation_after,
            "maximumDomainViolationMm": float(max(0.0, np.max(domain_distances))) if len(domain_distances) else 0.0,
            "outsideVertexCount": int(np.count_nonzero(outside_mask)),
            "outsideVertexRatio": float(np.mean(outside_mask)) if len(outside_mask) else 0.0,
            "domainViolationToleranceMm": float(violation_tolerance),
            "nodeRadiusMm": float(args.tube_radius * args.node_radius_scale),
        })
        if conformal_result is not None:
            metadata.update(conformal_result.metadata)
            metadata["conformalSurfaceParameters"] = {
                "surfaceStrutDiameterMm": float(conformal_surface_radius * 2.0),
                "surfaceNodeRadiusMm": float(conformal_node_radius),
                "surfacePlacementMode": args.surface_placement_mode,
                "surfaceInsetMm": float(
                    args.surface_inset_mm
                    if args.surface_inset_mode == "custom"
                    else conformal_surface_radius
                ),
                "surfaceSmoothingIterations": int(args.surface_smoothing_iterations),
                "surfaceSmoothingStrength": float(args.surface_smoothing_strength),
                "connectSurfaceToInterior": bool(args.connect_surface_to_interior),
                "connectorDiameterMm": float(conformal_connector_radius * 2.0),
            }
            metadata["combinedConnectivity"] = {
                "interiorGraphComponentCount": int(analyze_strut_graph(inside_edges)["connectedComponentCount"]),
                "surfaceGraphComponentCount": int(
                    conformal_result.metadata["surfaceGraph"]["connectedComponentCount"]
                ),
                "connectorCount": int(len(connector_edges)),
                "unconnectedSurfaceComponentCount": int(
                    conformal_result.metadata["surfaceConnections"]["unconnectedSurfaceComponentCount"]
                ),
                "combinedGraphComponentCount": int(graph_stats["connectedComponentCount"]),
                "finalMeshComponentCount": int(validation_after["connectedComponentCount"]),
            }
    print_mesh_summary(
        inside_edges,
        connector_edges,
        support_edges,
        optimization_stats,
        surface_seed_count,
        tube_mesh,
        connector_mesh,
        shell_mesh,
        node_mesh,
        export_mesh,
    )

    export_seconds = 0.0
    if args.export_stl:
        checkpoint()
        report("exporting-files", "Exportuji výsledné STL.", 0.94)
        export_started = perf_counter()
        export_stl(export_mesh, args.export_stl)
        export_seconds = perf_counter() - export_started

    metadata["exportTimeSeconds"] = float(export_seconds)
    metadata["totalGenerationTimeSeconds"] = float(perf_counter() - overall_started)
    if args.cache_enabled:
        cache.cleanup()

    requested_debug = (
        set(ALL_LAYERS)
        if args.debug_mode == "all"
        else {name for name in args.debug_layers.split(",") if name in ALL_LAYERS}
        if args.debug_mode == "requested"
        else set()
    )
    if requested_debug and args.debug_manifest_json and args.debug_buffer_bin:
        checkpoint()
        interior_nodes = unique_edge_points(inside_edges + support_edges, decimals=6)
        debug_candidates: dict[str, object] = {
            "seed-points": points,
            "raw-volume-voronoi-edges": edges,
            "clipped-interior-centerlines": inside_edges + support_edges,
            "interior-nodes": interior_nodes,
            "surface-to-interior-connectors": connector_edges,
            "combined-centerline-graph": all_final_edges,
            "final-implicit-mesh": np.asarray(export_mesh.points)[
                np.asarray(export_mesh.faces).reshape((-1, 4))[:, 1:]
            ],
        }
        if conformal_result is not None:
            debug_candidates.update({
                "raw-surface-voronoi-segments": conformal_result.raw_surface_segments,
                "smoothed-surface-centerlines": conformal_result.smoothed_surface_segments,
                "placed-surface-centerlines": surface_edges,
                "surface-nodes": conformal_result.surface_nodes,
            })
        selected = {name: debug_candidates[name] for name in sorted(requested_debug) if name in debug_candidates}
        debug_manifest = write_debug_payload(
            selected,
            args.debug_manifest_json,
            args.debug_buffer_bin,
            max(1, args.debug_maximum_points),
            max(1, args.debug_maximum_segments),
        )
        metadata["debugGeometry"] = {
            "formatVersion": debug_manifest["formatVersion"],
            "requestedLayers": sorted(requested_debug),
            "availableLayers": sorted(debug_manifest["layers"]),
            "totalByteLength": debug_manifest["totalByteLength"],
        }

    if args.metadata_json:
        checkpoint()
        metadata_path = Path(args.metadata_json)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Exported metadata: {metadata_path.resolve()}")

    if not args.no_show:
        show_scene(shape, points, inside_edges, tube_mesh, connector_mesh, shell_mesh, node_mesh, debug=args.debug)
    report("result-ready", "Výsledná geometrie je připravena.", 1.0)
    return metadata


if __name__ == "__main__":
    main()
