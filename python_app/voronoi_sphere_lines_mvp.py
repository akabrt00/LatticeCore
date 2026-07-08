from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyvista as pv
from scipy.spatial import Voronoi


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


def export_stl(tube_mesh: pv.PolyData, output_path: str | Path) -> None:
    """Export the tube mesh as STL."""
    if tube_mesh.n_points == 0:
        raise ValueError("Tube mesh is empty; nothing to export.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tube_mesh.save(output)
    print(f"Exported STL: {output.resolve()}")


def show_scene(
    points: np.ndarray,
    edges: list[tuple[np.ndarray, np.ndarray]],
    tube_mesh: pv.PolyData,
    debug: bool = False,
) -> None:
    """Show the sphere, tube mesh and optional debug seed points / lines."""
    plotter = pv.Plotter(window_size=(1100, 850))
    plotter.set_background("#111820")

    sphere = pv.Sphere(radius=1.0, theta_resolution=64, phi_resolution=64)
    plotter.add_mesh(sphere, color="#9fb0b8", opacity=0.16, style="wireframe")

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
    parser.add_argument("--random-seed", type=int, default=42, help="Random seed for repeatable results.")
    parser.add_argument("--debug", action="store_true", help="Show original seed points and Voronoi lines.")
    parser.add_argument("--no-show", action="store_true", help="Generate and export without opening a PyVista window.")
    parser.add_argument(
        "--export-stl",
        default="exports/voronoi_sphere_tubes.stl",
        help="Output STL path. Use an empty string to skip export.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    points = generate_points_in_sphere(args.points, args.radius, args.random_seed)
    edges = compute_voronoi_edges(points)
    inside_edges = filter_edges_inside_sphere(edges, args.radius)
    tube_mesh = create_tube_mesh(inside_edges, args.tube_radius)

    if args.export_stl:
        export_stl(tube_mesh, args.export_stl)

    if not args.no_show:
        show_scene(points, inside_edges, tube_mesh, debug=args.debug)


if __name__ == "__main__":
    main()
