from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyvista as pv
from scipy.spatial import SphericalVoronoi, Voronoi


def generate_points_in_sphere(n: int, radius: float, random_seed: int = 42) -> np.ndarray:
    """Generate n random points inside a sphere centered at [0, 0, 0]."""
    rng = np.random.default_rng(random_seed)
    points: list[np.ndarray] = []

    while len(points) < n:
        candidate = rng.uniform(-radius, radius, size=3)
        if np.linalg.norm(candidate) <= radius:
            points.append(candidate)

    return np.asarray(points)


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
    tube_mesh: pv.PolyData,
    shell_mesh: pv.PolyData,
    export_mesh: pv.PolyData,
) -> None:
    """Print a compact generation summary for slicer/debug checks."""
    print(
        "Generated "
        f"inside_edges={len(edges)} "
        f"tube_cells={tube_mesh.n_cells} "
        f"surface_shell_cells={shell_mesh.n_cells} "
        f"combined_cells={export_mesh.n_cells} "
        f"combined_points={export_mesh.n_points}"
    )


def show_scene(
    points: np.ndarray,
    edges: list[tuple[np.ndarray, np.ndarray]],
    tube_mesh: pv.PolyData,
    shell_mesh: pv.PolyData,
    debug: bool = False,
) -> None:
    """Show the shell, tube mesh and optional debug seed points / lines."""
    plotter = pv.Plotter(window_size=(1100, 850))
    plotter.set_background("#111820")

    if shell_mesh.n_points > 0:
        plotter.add_mesh(shell_mesh, color="#9fb0b8", smooth_shading=True)

    if tube_mesh.n_points > 0:
        plotter.add_mesh(tube_mesh, color="#34302a", smooth_shading=True)

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
        f"3D Voronoi tubes inside sphere | seeds: {len(points)} | edges: {len(edges)}",
        position="upper_left",
        font_size=11,
    )
    plotter.show()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voronoi sphere tube MVP")
    parser.add_argument("--points", type=int, default=80, help="Number of random seed points inside the sphere.")
    parser.add_argument("--radius", type=float, default=1.0, help="Sphere radius.")
    parser.add_argument("--tube-radius", type=float, default=0.025, help="Radius of generated tube struts.")
    parser.add_argument("--surface-points", type=int, default=55, help="Number of seed points for surface Voronoi casing.")
    parser.add_argument("--surface-tube-radius", type=float, default=0.026, help="Radius of surface Voronoi casing struts.")
    parser.add_argument("--random-seed", type=int, default=42, help="Random seed for repeatable results.")
    parser.add_argument("--debug", action="store_true", help="Show original seed points and Voronoi lines.")
    parser.add_argument("--no-shell", action="store_true", help="Export and show only inner Voronoi tubes without surface casing.")
    parser.add_argument("--no-show", action="store_true", help="Generate and export without opening a PyVista window.")
    parser.add_argument(
        "--export-stl",
        default="exports/voronoi_sphere_with_shell.stl",
        help="Output STL path. Use an empty string to skip export.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    points = generate_points_in_sphere(args.points, args.radius, args.random_seed)
    edges = compute_voronoi_edges(points)
    inside_edges = filter_edges_inside_sphere(edges, args.radius)
    tube_mesh = create_tube_mesh(inside_edges, args.tube_radius)
    shell_mesh = (
        pv.PolyData()
        if args.no_shell
        else create_surface_voronoi_shell(
            args.radius,
            args.surface_points,
            args.surface_tube_radius,
            args.random_seed + 1000,
        )
    )
    export_mesh = combine_meshes([shell_mesh, tube_mesh])
    print_mesh_summary(inside_edges, tube_mesh, shell_mesh, export_mesh)

    if args.export_stl:
        export_stl(export_mesh, args.export_stl)

    if not args.no_show:
        show_scene(points, inside_edges, tube_mesh, shell_mesh, debug=args.debug)


if __name__ == "__main__":
    main()
