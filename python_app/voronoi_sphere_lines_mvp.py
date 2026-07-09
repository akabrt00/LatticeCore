from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyvista as pv
from scipy.spatial import SphericalVoronoi, Voronoi


@dataclass(frozen=True)
class OptimizationStats:
    """Basic counts from the automatic strut cleanup stage."""

    raw_edges: int
    inside_edges: int
    removed_short_edges: int


def generate_points_in_sphere(n: int, radius: float, random_seed: int = 42) -> np.ndarray:
    """Generate n random points inside a sphere centered at [0, 0, 0]."""
    rng = np.random.default_rng(random_seed)
    points: list[np.ndarray] = []

    while len(points) < n:
        candidate = rng.uniform(-radius, radius, size=3)
        if np.linalg.norm(candidate) <= radius:
            points.append(candidate)

    return np.asarray(points)


def generate_points_in_box(n: int, half_size: float, random_seed: int = 42) -> np.ndarray:
    """Generate n random points inside a box centered at [0, 0, 0]."""
    rng = np.random.default_rng(random_seed)
    return rng.uniform(-half_size, half_size, size=(n, 3))


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
    half_size: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Keep only edges whose both endpoints are inside the box."""
    filtered_edges: list[tuple[np.ndarray, np.ndarray]] = []

    for start, end in edges:
        if np.all(np.abs(start) <= half_size) and np.all(np.abs(end) <= half_size):
            filtered_edges.append((start, end))

    return filtered_edges


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
        optimized_edges = filter_edges_by_length(inside_edges, min_length)
    else:
        optimized_edges = inside_edges

    stats = OptimizationStats(
        raw_edges=len(edges),
        inside_edges=len(inside_edges),
        removed_short_edges=len(inside_edges) - len(optimized_edges),
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


def face_point_to_3d(face: str, point: np.ndarray, half_size: float) -> np.ndarray:
    """Map a 2D face point to a 3D point on one cube face."""
    u, v = point
    if face == "x+":
        return np.asarray([half_size, u, v])
    if face == "x-":
        return np.asarray([-half_size, u, v])
    if face == "y+":
        return np.asarray([u, half_size, v])
    if face == "y-":
        return np.asarray([u, -half_size, v])
    if face == "z+":
        return np.asarray([u, v, half_size])
    return np.asarray([u, v, -half_size])


def create_box_frame_edges(half_size: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """Create the 12 outer cube frame edges."""
    corners = [
        np.asarray([x, y, z])
        for x in (-half_size, half_size)
        for y in (-half_size, half_size)
        for z in (-half_size, half_size)
    ]
    edges = []

    for first_index, first in enumerate(corners):
        for second in corners[first_index + 1 :]:
            differing_axes = np.count_nonzero(np.abs(first - second) > 1e-9)
            if differing_axes == 1:
                edges.append((first, second))

    return edges


def create_box_surface_voronoi_edges(
    half_size: float,
    surface_seed_count: int,
    random_seed: int,
    min_edge_length: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Create Voronoi-like tube centerlines on each cube face."""
    faces = ["x+", "x-", "y+", "y-", "z+", "z-"]
    seeds_per_face = max(6, int(np.ceil(surface_seed_count / len(faces))))
    surface_edges: list[tuple[np.ndarray, np.ndarray]] = create_box_frame_edges(half_size)

    for face_index, face in enumerate(faces):
        points_2d = generate_points_on_square(seeds_per_face, half_size, random_seed + face_index * 101)
        edges_2d = compute_square_voronoi_edges(points_2d, half_size, min_edge_length)
        for start, end in edges_2d:
            surface_edges.append(
                (
                    face_point_to_3d(face, start, half_size),
                    face_point_to_3d(face, end, half_size),
                )
            )

    return surface_edges


def create_box_surface_voronoi_shell(
    half_size: float,
    surface_seed_count: int,
    tube_radius: float,
    random_seed: int,
    min_edge_length: float,
) -> tuple[pv.PolyData, list[tuple[np.ndarray, np.ndarray]]]:
    """Create a cube casing with Voronoi-like tube cells on each face."""
    surface_edges = create_box_surface_voronoi_edges(half_size, surface_seed_count, random_seed, min_edge_length)
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


def resolve_surface_seed_count(shape: str, requested_surface_points: int, inner_seed_count: int) -> int:
    """Choose surface density from inner density unless the user overrides it."""
    if requested_surface_points > 0:
        return requested_surface_points
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


def box_boundary_distance(point: np.ndarray, half_size: float) -> float:
    """Return distance from a point inside a box to the nearest face."""
    return float(half_size - np.max(np.abs(point)))


def nearest_box_face(point: np.ndarray) -> tuple[int, float]:
    """Return dominant axis and sign for the nearest box face."""
    axis = int(np.argmax(np.abs(point)))
    sign = 1.0 if point[axis] >= 0 else -1.0
    return axis, sign


def same_box_face(point: np.ndarray, surface_point: np.ndarray, half_size: float) -> bool:
    """Return True when an inner point and surface point belong to the same nearest face."""
    axis, sign = nearest_box_face(point)
    return bool(abs(surface_point[axis] - sign * half_size) <= 1e-6)


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
    half_size: float,
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

    for inner_point in inner_points:
        face_points = [point for point in surface_points if same_box_face(inner_point, point, half_size)]
        if not face_points:
            continue

        nearest_surface = min(face_points, key=lambda point: float(np.linalg.norm(point - inner_point)))
        length = float(np.linalg.norm(nearest_surface - inner_point))
        if length < min_length or length > max_length:
            continue

        key = edge_key_3d(inner_point, nearest_surface)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        connector_edges.append((inner_point, nearest_surface))

    return connector_edges


def create_connection_edges(
    shape: str,
    inside_edges: list[tuple[np.ndarray, np.ndarray]],
    surface_edges: list[tuple[np.ndarray, np.ndarray]],
    radius: float,
    boundary_band: float,
    max_length: float,
    min_length: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Create connection struts between inner lattice and surface network."""
    if shape != "box" or not surface_edges:
        return []
    return create_box_connection_edges(inside_edges, surface_edges, radius, boundary_band, max_length, min_length)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voronoi tube MVP")
    parser.add_argument("--shape", choices=["sphere", "box"], default="box", help="Implicit body shape.")
    parser.add_argument("--points", type=int, default=80, help="Number of random seed points inside the body.")
    parser.add_argument("--radius", type=float, default=1.0, help="Sphere radius or box half-size.")
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
    parser.add_argument("--debug", action="store_true", help="Show original seed points and Voronoi lines.")
    parser.add_argument("--no-shell", action="store_true", help="Export and show only inner Voronoi tubes without surface casing.")
    parser.add_argument("--no-show", action="store_true", help="Generate and export without opening a PyVista window.")
    parser.add_argument(
        "--export-stl",
        default="exports/voronoi_lattice_with_surface.stl",
        help="Output STL path. Use an empty string to skip export.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    points = generate_body_points(args.shape, args.points, args.radius, args.random_seed)
    edges = compute_voronoi_edges(points)
    min_strut_length = 0.0 if args.no_optimize else args.min_strut_length * args.radius
    connector_min_length = 0.0 if args.no_optimize else args.connector_min_length * args.radius
    surface_seed_count = resolve_surface_seed_count(args.shape, args.surface_points, args.points)
    inside_edges, optimization_stats = optimize_strut_network(
        args.shape,
        edges,
        args.radius,
        min_strut_length,
        enabled=not args.no_optimize,
    )
    tube_mesh = create_tube_mesh(inside_edges, args.tube_radius)
    if args.no_shell:
        shell_mesh = pv.PolyData()
        surface_edges: list[tuple[np.ndarray, np.ndarray]] = []
    else:
        shell_mesh, surface_edges = create_surface_shell(
            args.shape,
            args.radius,
            surface_seed_count,
            args.surface_tube_radius,
            args.random_seed + 1000,
            min_strut_length,
        )

    connector_edges = create_connection_edges(
        args.shape,
        inside_edges,
        surface_edges,
        args.radius,
        args.connector_band * args.radius,
        args.connector_max_length * args.radius,
        connector_min_length,
    )
    support_edges = (
        []
        if args.no_supports or args.shape != "box"
        else create_dangling_support_edges(
            inside_edges + connector_edges,
            surface_edges,
            args.radius,
            connector_min_length,
            args.support_max_length * args.radius,
        )
    )
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

    export_mesh = combine_meshes([shell_mesh, tube_mesh, connector_mesh, node_mesh])
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

    if args.export_stl:
        export_stl(export_mesh, args.export_stl)

    if not args.no_show:
        show_scene(args.shape, points, inside_edges, tube_mesh, connector_mesh, shell_mesh, node_mesh, debug=args.debug)


if __name__ == "__main__":
    main()
