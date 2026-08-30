"""Restricted 3D Voronoi network on a closed triangular surface."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np
import pyvista as pv
from scipy.spatial import cKDTree

from imported_mesh import TriangleMeshDomain, clip_segment_to_domain_intervals


@dataclass(frozen=True)
class SurfaceVoronoiParameters:
    sampling_step_mm: float
    strut_radius_mm: float
    node_radius_mm: float
    placement_mode: str = "inset-inside"
    inset_mm: float = 0.0
    smoothing_iterations: int = 2
    smoothing_strength: float = 0.35
    connector_spacing_mm: float = 5.0
    connector_maximum_length_mm: float = 15.0
    connector_radius_mm: float = 0.5
    minimum_connectors_per_component: int = 1
    maximum_working_triangles: int = 300_000
    topology_weld_reference_mm: float = 0.0


@dataclass
class SurfaceVoronoiResult:
    raw_surface_segments: list[tuple[np.ndarray, np.ndarray]]
    smoothed_surface_segments: list[tuple[np.ndarray, np.ndarray]]
    surface_segments: list[tuple[np.ndarray, np.ndarray]]
    surface_nodes: np.ndarray
    connector_segments: list[tuple[np.ndarray, np.ndarray]]
    connector_nodes: np.ndarray
    metadata: dict


def solve_equal_distance_on_edge(
    p0: np.ndarray,
    p1: np.ndarray,
    seed_a: np.ndarray,
    seed_b: np.ndarray,
    tolerance: float = 1e-9,
) -> np.ndarray | None:
    first, second = np.asarray(p0, float), np.asarray(p1, float)
    a, b = np.asarray(seed_a, float), np.asarray(seed_b, float)
    direction = second - first
    if not np.all(np.isfinite([first, second, a, b])) or np.dot(direction, direction) <= tolerance**2:
        return None
    seed_delta = b - a
    denominator = 2.0 * float(np.dot(direction, seed_delta))
    if abs(denominator) <= tolerance or np.dot(seed_delta, seed_delta) <= tolerance**2:
        return None
    numerator = float(np.dot(b, b) - np.dot(a, a) - 2.0 * np.dot(first, seed_delta))
    parameter = numerator / denominator
    if parameter < -tolerance or parameter > 1.0 + tolerance:
        return None
    point = first + np.clip(parameter, 0.0, 1.0) * direction
    return point if np.all(np.isfinite(point)) else None


def _triple_junction(
    triangle: np.ndarray,
    seeds: np.ndarray,
    tolerance: float,
) -> np.ndarray | None:
    origin = triangle[0]
    basis = np.column_stack((triangle[1] - origin, triangle[2] - origin))
    if np.linalg.matrix_rank(basis, tol=tolerance) < 2:
        return None
    a, b, c = seeds
    matrix = np.asarray([
        2.0 * basis.T @ (b - a),
        2.0 * basis.T @ (c - a),
    ])
    rhs = np.asarray([
        np.dot(b, b) - np.dot(a, a) - 2.0 * np.dot(origin, b - a),
        np.dot(c, c) - np.dot(a, a) - 2.0 * np.dot(origin, c - a),
    ])
    if abs(np.linalg.det(matrix)) <= tolerance:
        return None
    uv = np.linalg.solve(matrix, rhs)
    barycentric = np.asarray([1.0 - uv[0] - uv[1], uv[0], uv[1]])
    if np.any(barycentric < -tolerance) or np.any(barycentric > 1.0 + tolerance):
        return None
    point = origin + basis @ uv
    return point if np.all(np.isfinite(point)) else None


def extract_triangle_voronoi_segments(
    triangle: np.ndarray,
    labels: np.ndarray,
    seed_points: np.ndarray,
    tolerance: float = 1e-8,
) -> list[tuple[np.ndarray, np.ndarray]]:
    vertices = np.asarray(triangle, float)
    labels = np.asarray(labels, int)
    if vertices.shape != (3, 3) or np.linalg.norm(np.cross(vertices[1] - vertices[0], vertices[2] - vertices[0])) <= tolerance:
        return []
    unique = np.unique(labels)
    if len(unique) <= 1:
        return []
    edge_pairs = ((0, 1), (1, 2), (2, 0))
    crossings: dict[tuple[int, int], list[np.ndarray]] = {}
    for first_index, second_index in edge_pairs:
        first_label, second_label = int(labels[first_index]), int(labels[second_index])
        if first_label == second_label:
            continue
        pair = tuple(sorted((first_label, second_label)))
        point = solve_equal_distance_on_edge(
            vertices[first_index],
            vertices[second_index],
            seed_points[pair[0]],
            seed_points[pair[1]],
            tolerance,
        )
        if point is not None:
            crossings.setdefault(pair, []).append(point)
    if len(unique) == 2:
        points = [point for pair_points in crossings.values() for point in pair_points]
        return [(points[0], points[1])] if len(points) == 2 and np.linalg.norm(points[1] - points[0]) > tolerance else []

    ordered_labels = labels.tolist()
    junction = _triple_junction(vertices, seed_points[ordered_labels], tolerance)
    if junction is None:
        # Deterministic local fallback: use the centroid projected into the triangle.
        junction = np.mean(vertices, axis=0)
    segments = []
    for pair_points in crossings.values():
        for point in pair_points:
            if np.linalg.norm(point - junction) > tolerance:
                segments.append((junction.copy(), point.copy()))
    return segments


def create_working_surface_mesh(
    source_mesh: pv.PolyData,
    sampling_step_mm: float,
    maximum_triangles: int,
) -> tuple[pv.PolyData, dict]:
    started = perf_counter()
    mesh = source_mesh.extract_surface(algorithm="dataset_surface").triangulate().clean()
    if sampling_step_mm <= 0:
        raise ValueError("surfaceSamplingStepMm must be positive.")
    area = max(float(mesh.area), 1e-12)
    estimated = max(mesh.n_cells, int(np.ceil(area * 4.0 / (np.sqrt(3.0) * sampling_step_mm**2))))
    if estimated > maximum_triangles:
        raise ValueError(
            f"Surface working mesh is estimated at {estimated:,} triangles; limit is {maximum_triangles:,}. "
            "Increase surfaceSamplingStepMm."
        )
    if mesh.n_cells < maximum_triangles:
        mesh = mesh.subdivide_adaptive(
            max_edge_len=float(sampling_step_mm),
            max_n_tris=int(maximum_triangles),
            max_n_passes=12,
        ).triangulate().clean()
    if mesh.n_cells > maximum_triangles:
        raise ValueError("Surface subdivision exceeded maximumSurfaceWorkingTriangles.")
    return mesh, {
        "estimatedWorkingTriangleCount": int(estimated),
        "estimatedMemoryBytes": int((mesh.n_points * 3 + mesh.n_cells * 4) * 8),
        "subdivisionTimeSeconds": float(perf_counter() - started),
    }


def label_surface_vertices(mesh: pv.PolyData, seeds: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    started = perf_counter()
    distances, labels = cKDTree(np.asarray(seeds, float)).query(np.asarray(mesh.points), k=1, workers=1)
    labels = np.asarray(labels, dtype=int)
    touched = int(len(np.unique(labels)))
    return labels, np.square(distances), {
        "workingSurfaceVertexCount": int(mesh.n_points),
        "workingSurfaceTriangleCount": int(mesh.n_cells),
        "seedCount": int(len(seeds)),
        "seedsTouchingSurface": touched,
        "seedsNotTouchingSurface": int(len(seeds) - touched),
        "labelingTimeSeconds": float(perf_counter() - started),
    }


def extract_surface_segments(mesh: pv.PolyData, labels: np.ndarray, seeds: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    faces = np.asarray(mesh.faces).reshape(-1, 4)[:, 1:]
    segments: list[tuple[np.ndarray, np.ndarray]] = []
    for face in faces:
        segments.extend(extract_triangle_voronoi_segments(mesh.points[face], labels[face], seeds))
    return segments


def _point_key(point: np.ndarray, tolerance: float) -> tuple[int, int, int]:
    return tuple(np.rint(np.asarray(point) / tolerance).astype(np.int64).tolist())


def clean_surface_graph(
    segments: list[tuple[np.ndarray, np.ndarray]],
    weld_tolerance: float,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], np.ndarray, dict, list[list[int]]]:
    tolerance = max(float(weld_tolerance), 1e-9)
    invalid = zero = duplicates = 0
    sums: dict[tuple[int, int, int], np.ndarray] = {}
    counts: dict[tuple[int, int, int], int] = {}
    raw_pairs = []
    for start, end in segments:
        first, second = np.asarray(start, float), np.asarray(end, float)
        if not np.all(np.isfinite([first, second])):
            invalid += 1
            continue
        if np.linalg.norm(second - first) <= tolerance:
            zero += 1
            continue
        keys = (_point_key(first, tolerance), _point_key(second, tolerance))
        for key, point in zip(keys, (first, second)):
            sums[key] = sums.get(key, np.zeros(3)) + point
            counts[key] = counts.get(key, 0) + 1
        raw_pairs.append(keys)
    ordered_keys = sorted(sums)
    key_to_index = {key: index for index, key in enumerate(ordered_keys)}
    nodes = np.asarray([sums[key] / counts[key] for key in ordered_keys], dtype=float)
    unique_pairs = set()
    pairs = []
    for first_key, second_key in raw_pairs:
        pair = tuple(sorted((key_to_index[first_key], key_to_index[second_key])))
        if pair[0] == pair[1]:
            zero += 1
        elif pair in unique_pairs:
            duplicates += 1
        else:
            unique_pairs.add(pair)
            pairs.append(pair)
    pairs.sort()
    adjacency = [set() for _ in range(len(nodes))]
    for first, second in pairs:
        adjacency[first].add(second)
        adjacency[second].add(first)
    components = []
    unseen = set(range(len(nodes)))
    while unseen:
        root = min(unseen)
        stack, component = [root], []
        unseen.remove(root)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(adjacency[current], reverse=True):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))
    clean_segments = [(nodes[a].copy(), nodes[b].copy()) for a, b in pairs]
    lengths = np.asarray([np.linalg.norm(nodes[b] - nodes[a]) for a, b in pairs])
    degrees = np.asarray([len(neighbors) for neighbors in adjacency], dtype=int)
    polyline_count = sum(1 for degree in degrees if degree != 2) or (1 if len(pairs) else 0)
    stats = {
        "rawSegmentCount": int(len(segments)),
        "removedInvalidSegmentCount": invalid,
        "removedZeroLengthSegmentCount": zero,
        "removedDuplicateSegmentCount": duplicates,
        "cleanSegmentCount": int(len(pairs)),
        "nodeCount": int(len(nodes)),
        "polylineCount": int(polyline_count),
        "connectedComponentCount": int(len([item for item in components if item])),
        "totalLengthMm": float(np.sum(lengths)) if len(lengths) else 0.0,
        "minimumSegmentLengthMm": float(np.min(lengths)) if len(lengths) else 0.0,
        "averageSegmentLengthMm": float(np.mean(lengths)) if len(lengths) else 0.0,
        "medianSegmentLengthMm": float(np.median(lengths)) if len(lengths) else 0.0,
        "maximumSegmentLengthMm": float(np.max(lengths)) if len(lengths) else 0.0,
        "averageNodeDegree": float(np.mean(degrees)) if len(degrees) else 0.0,
        "maximumNodeDegree": int(np.max(degrees)) if len(degrees) else 0,
    }
    return clean_segments, nodes, stats, components


def smooth_surface_graph(
    segments: list[tuple[np.ndarray, np.ndarray]],
    domain: TriangleMeshDomain,
    iterations: int,
    strength: float,
    weld_tolerance: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    clean, nodes, _, _ = clean_surface_graph(segments, weld_tolerance)
    pairs = [(_point_key(a, weld_tolerance), _point_key(b, weld_tolerance)) for a, b in clean]
    key_to_index = {_point_key(point, weld_tolerance): index for index, point in enumerate(nodes)}
    indexed = [(key_to_index[a], key_to_index[b]) for a, b in pairs]
    adjacency = [set() for _ in range(len(nodes))]
    for first, second in indexed:
        adjacency[first].add(second)
        adjacency[second].add(first)
    for _ in range(max(0, int(iterations))):
        candidate = nodes.copy()
        for index, neighbors in enumerate(adjacency):
            if len(neighbors) == 2:
                average = np.mean(nodes[sorted(neighbors)], axis=0)
                candidate[index] = nodes[index] + np.clip(strength, 0.0, 1.0) * (average - nodes[index])
        movable = [index for index, neighbors in enumerate(adjacency) if len(neighbors) == 2]
        if movable:
            candidate[movable] = domain.closest_points(candidate[movable])
        nodes = candidate
    return [(nodes[first].copy(), nodes[second].copy()) for first, second in indexed]


def place_surface_points(
    points: np.ndarray,
    domain: TriangleMeshDomain,
    placement_mode: str,
    inset_mm: float,
) -> tuple[np.ndarray, dict]:
    source = np.asarray(points, float)
    if placement_mode == "on-surface-clipped" or inset_mm <= 0:
        placed = domain.closest_points(source)
        distances = np.linalg.norm(placed - source, axis=1)
        sdf = domain.signed_distance(placed)
        adaptive = 0
    else:
        surface = domain.closest_points(source)
        extent = np.linalg.norm(domain.bounds()[1] - domain.bounds()[0])
        epsilon = max(extent * 1e-5, inset_mm * 0.05, 1e-5)
        gradient = np.column_stack([
            (domain.signed_distance(surface + np.eye(3)[axis] * epsilon) - domain.signed_distance(surface - np.eye(3)[axis] * epsilon)) / (2 * epsilon)
            for axis in range(3)
        ])
        norms = np.linalg.norm(gradient, axis=1)
        gradient[norms > 1e-12] /= norms[norms > 1e-12, None]
        placed = surface - gradient * inset_mm
        wrong = domain.signed_distance(placed) > 0
        placed[wrong] = surface[wrong] + gradient[wrong] * inset_mm
        adaptive = 0
        for index in range(len(placed)):
            if domain.signed_distance(placed[index]) > -inset_mm * 0.5:
                low, high = 0.0, inset_mm
                direction = placed[index] - surface[index]
                direction_norm = np.linalg.norm(direction)
                if direction_norm <= 1e-12:
                    continue
                direction /= direction_norm
                best = surface[index]
                for _ in range(20):
                    distance = (low + high) * 0.5
                    test = surface[index] + direction * distance
                    if domain.signed_distance(test) <= 0:
                        best, low = test, distance
                    else:
                        high = distance
                placed[index] = best
                adaptive += 1
        distances = np.linalg.norm(placed - surface, axis=1)
        sdf = domain.signed_distance(placed)
    return placed, {
        "originalSurfacePointCount": int(len(source)),
        "placedSurfacePointCount": int(len(placed)),
        "maximumDistanceFromSourceSurfaceMm": float(np.max(distances)) if len(distances) else 0.0,
        "averageDistanceFromSourceSurfaceMm": float(np.mean(distances)) if len(distances) else 0.0,
        "minimumDomainSdfMm": float(np.min(sdf)) if len(sdf) else 0.0,
        "maximumDomainSdfMm": float(np.max(sdf)) if len(sdf) else 0.0,
        "outsidePointCount": int(np.count_nonzero(sdf > 1e-6)),
        "adaptiveInsetPointCount": int(adaptive),
        "onSurfaceFallbackPointCount": 0,
    }


def create_surface_connectors(
    surface_nodes: np.ndarray,
    surface_components: list[list[int]],
    interior_segments: list[tuple[np.ndarray, np.ndarray]],
    domain: TriangleMeshDomain,
    spacing_mm: float,
    maximum_length_mm: float,
    minimum_per_component: int,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], dict]:
    interior_nodes = np.asarray([point for edge in interior_segments for point in edge], dtype=float)
    if not len(interior_nodes):
        return [], {
            "requestedConnectorCount": int(len(surface_components) * minimum_per_component),
            "acceptedConnectorCount": 0,
            "rejectedTooLongCount": 0,
            "rejectedOutsideCount": 0,
            "removedDuplicateCount": 0,
            "unconnectedSurfaceComponentCount": int(len(surface_components)),
            "totalConnectorLengthMm": 0.0,
            "averageConnectorLengthMm": 0.0,
        }
    tree = cKDTree(interior_nodes)
    accepted, used = [], set()
    rejected_long = rejected_outside = duplicates = unconnected = requested = 0
    for component in surface_components:
        if not component:
            continue
        ordered = sorted(component)
        component_extent = np.ptp(surface_nodes[ordered], axis=0)
        target_count = max(
            minimum_per_component,
            int(np.ceil(np.linalg.norm(component_extent) / max(spacing_mm, 1e-6))),
        )
        candidate_indices = np.linspace(0, len(ordered) - 1, min(target_count, len(ordered)), dtype=int)
        component_accepted = 0
        for selection in candidate_indices:
            requested += 1
            start = surface_nodes[ordered[int(selection)]]
            _, nearest = tree.query(start, k=1)
            end = interior_nodes[int(nearest)]
            length = float(np.linalg.norm(end - start))
            if maximum_length_mm > 0 and length > maximum_length_mm:
                rejected_long += 1
                continue
            intervals = clip_segment_to_domain_intervals(start, end, domain, max(length / 24.0, 1e-4))
            if not intervals:
                rejected_outside += 1
                continue
            segment = max(intervals, key=lambda item: np.linalg.norm(item[1] - item[0]))
            if np.linalg.norm(segment[1] - segment[0]) < length * 0.9:
                rejected_outside += 1
                continue
            key = tuple(sorted((_point_key(segment[0], 1e-5), _point_key(segment[1], 1e-5))))
            if key in used:
                duplicates += 1
                continue
            used.add(key)
            accepted.append((segment[0].copy(), segment[1].copy()))
            component_accepted += 1
        if component_accepted < minimum_per_component:
            unconnected += 1
    lengths = np.asarray([np.linalg.norm(b - a) for a, b in accepted])
    return accepted, {
        "requestedConnectorCount": int(requested),
        "acceptedConnectorCount": int(len(accepted)),
        "rejectedTooLongCount": int(rejected_long),
        "rejectedOutsideCount": int(rejected_outside),
        "removedDuplicateCount": int(duplicates),
        "unconnectedSurfaceComponentCount": int(unconnected),
        "totalConnectorLengthMm": float(np.sum(lengths)) if len(lengths) else 0.0,
        "averageConnectorLengthMm": float(np.mean(lengths)) if len(lengths) else 0.0,
    }


def generate_conformal_surface(
    domain: TriangleMeshDomain,
    seed_points: np.ndarray,
    interior_segments: list[tuple[np.ndarray, np.ndarray]],
    parameters: SurfaceVoronoiParameters,
    connect_to_interior: bool = True,
) -> SurfaceVoronoiResult:
    working, working_stats = create_working_surface_mesh(
        domain.mesh,
        parameters.sampling_step_mm,
        parameters.maximum_working_triangles,
    )
    labels, squared_distances, label_stats = label_surface_vertices(working, seed_points)
    raw = extract_surface_segments(working, labels, seed_points)
    weld_reference = parameters.topology_weld_reference_mm or parameters.strut_radius_mm * 2.0
    weld = max(min(parameters.sampling_step_mm, weld_reference) * 0.05, 1e-6)
    clean, _, graph_stats, _ = clean_surface_graph(raw, weld)
    smoothed = smooth_surface_graph(
        clean,
        domain,
        parameters.smoothing_iterations,
        parameters.smoothing_strength,
        weld,
    )
    base_metadata = {
        "surfaceVoronoiStatistics": {
            **working_stats,
            **label_stats,
            "samplingStepMm": float(parameters.sampling_step_mm),
            "minimumSquaredSeedDistanceMm2": float(np.min(squared_distances)) if len(squared_distances) else 0.0,
        },
        "surfaceGraph": graph_stats,
    }
    return place_conformal_surface_graph(
        domain,
        interior_segments,
        parameters,
        raw,
        smoothed,
        base_metadata,
        connect_to_interior,
    )


def place_conformal_surface_graph(
    domain: TriangleMeshDomain,
    interior_segments: list[tuple[np.ndarray, np.ndarray]],
    parameters: SurfaceVoronoiParameters,
    raw: list[tuple[np.ndarray, np.ndarray]],
    smoothed: list[tuple[np.ndarray, np.ndarray]],
    base_metadata: dict,
    connect_to_interior: bool = True,
) -> SurfaceVoronoiResult:
    weld_reference = parameters.topology_weld_reference_mm or parameters.strut_radius_mm * 2.0
    weld = max(min(parameters.sampling_step_mm, weld_reference) * 0.05, 1e-6)
    _, source_nodes, _, components = clean_surface_graph(smoothed, weld)
    placed_nodes, placement_stats = place_surface_points(
        source_nodes,
        domain,
        parameters.placement_mode,
        parameters.inset_mm,
    )
    key_to_index = {_point_key(point, weld): index for index, point in enumerate(source_nodes)}
    placed_segments = [
        (placed_nodes[key_to_index[_point_key(start, weld)]], placed_nodes[key_to_index[_point_key(end, weld)]])
        for start, end in smoothed
    ]
    connectors, connection_stats = (
        create_surface_connectors(
            placed_nodes,
            components,
            interior_segments,
            domain,
            parameters.connector_spacing_mm,
            parameters.connector_maximum_length_mm,
            parameters.minimum_connectors_per_component,
        )
        if connect_to_interior
        else ([], {
            "requestedConnectorCount": 0,
            "acceptedConnectorCount": 0,
            "rejectedTooLongCount": 0,
            "rejectedOutsideCount": 0,
            "removedDuplicateCount": 0,
            "unconnectedSurfaceComponentCount": int(len(components)),
            "totalConnectorLengthMm": 0.0,
            "averageConnectorLengthMm": 0.0,
        })
    )
    connector_nodes = np.asarray([point for segment in connectors for point in segment], dtype=float)
    metadata = {
        **base_metadata,
        "surfacePlacementValidation": placement_stats,
        "surfaceConnections": connection_stats,
    }
    return SurfaceVoronoiResult(
        raw,
        smoothed,
        placed_segments,
        placed_nodes,
        connectors,
        connector_nodes,
        metadata,
    )
