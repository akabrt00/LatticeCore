import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyvista as pv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from voronoi_sphere_lines_mvp import (
    OptimizationStats,
    analyze_strut_graph,
    build_generation_metadata,
    collapse_short_edge_nodes,
    combine_meshes,
    compute_voronoi_edges,
    create_node_sphere_mesh,
    create_tube_mesh,
    export_stl,
    filter_edges_inside_box,
    generate_points_in_box,
    inset_edges_for_box,
    keep_largest_graph_component,
    repair_mesh_for_export,
    validate_mesh,
)


class VoronoiCoreTests(unittest.TestCase):
    @staticmethod
    def make_mesh(points, faces):
        face_data = np.hstack((np.full((len(faces), 1), 3), np.asarray(faces))).astype(np.int64).ravel()
        return pv.PolyData(np.asarray(points, dtype=float), face_data)

    def test_box_points_are_reproducible(self):
        first = generate_points_in_box(20, np.asarray([15.0, 15.0, 12.0]), random_seed=1221)
        second = generate_points_in_box(20, np.asarray([15.0, 15.0, 12.0]), random_seed=1221)
        np.testing.assert_allclose(first, second)

    def test_points_stay_inside_rectangular_box(self):
        half_sizes = np.asarray([15.0, 15.0, 12.0])
        points = generate_points_in_box(200, half_sizes, random_seed=5)
        self.assertTrue(np.all(np.abs(points) <= half_sizes))

    def test_filter_edges_inside_rectangular_box(self):
        half_sizes = np.asarray([15.0, 15.0, 12.0])
        inside = (np.asarray([0.0, 0.0, 0.0]), np.asarray([14.0, 0.0, 0.0]))
        outside = (np.asarray([0.0, 0.0, 0.0]), np.asarray([16.0, 0.0, 0.0]))
        self.assertEqual(filter_edges_inside_box([inside, outside], half_sizes), [inside])

    def test_short_edge_contraction_removes_tiny_strut(self):
        edges = [
            (np.asarray([0.0, 0.0, 0.0]), np.asarray([0.5, 0.0, 0.0])),
            (np.asarray([0.5, 0.0, 0.0]), np.asarray([4.0, 0.0, 0.0])),
        ]
        collapsed_edges, collapsed_count = collapse_short_edge_nodes(edges, min_length=2.0)
        self.assertGreaterEqual(collapsed_count, 1)
        self.assertTrue(all(np.linalg.norm(end - start) >= 2.0 for start, end in collapsed_edges))

    def test_exact_bounds_for_reference_box(self):
        edges = [(np.asarray([-15.0, -8.0, 0.0]), np.asarray([-15.0, 8.0, 0.0]))]
        exact_edges = inset_edges_for_box(edges, np.asarray([15.0, 15.0, 12.0]), 0.5)
        mesh = combine_meshes([create_tube_mesh(exact_edges, 0.5), create_node_sphere_mesh(exact_edges, 0.5)])
        bounds = np.asarray(mesh.bounds)
        self.assertGreaterEqual(bounds[0], -15.02)
        self.assertLessEqual(bounds[1], 15.02)
        self.assertGreaterEqual(bounds[2], -15.02)
        self.assertLessEqual(bounds[3], 15.02)
        self.assertGreaterEqual(bounds[4], -12.02)
        self.assertLessEqual(bounds[5], 12.02)

    def test_exact_bounds_for_rectangular_box(self):
        half = np.asarray([10.0, 7.0, 4.0])
        edges = [(np.asarray([10.0, -7.0, -4.0]), np.asarray([10.0, 7.0, 4.0]))]
        clipped = inset_edges_for_box(edges, half, 0.4)
        mesh = combine_meshes([create_tube_mesh(clipped, 0.4), create_node_sphere_mesh(clipped, 0.4)])
        bounds = np.asarray(mesh.bounds)
        self.assertTrue(np.all(bounds[[0, 2, 4]] >= -np.repeat(half, 2)[::2] - 0.02))
        self.assertTrue(np.all(bounds[[1, 3, 5]] <= half + 0.02))

    def test_centerline_mode_can_overshoot_by_radius(self):
        edges = [(np.asarray([15.0, -4.0, 0.0]), np.asarray([15.0, 4.0, 0.0]))]
        mesh = create_tube_mesh(edges, 0.5)
        self.assertGreater(mesh.bounds[1], 15.45)

    def test_same_seed_has_same_voronoi_edge_statistics(self):
        first = compute_voronoi_edges(generate_points_in_box(32, [15, 15, 12], 801))
        second = compute_voronoi_edges(generate_points_in_box(32, [15, 15, 12], 801))
        first_lengths = sorted(round(float(np.linalg.norm(b - a)), 8) for a, b in first)
        second_lengths = sorted(round(float(np.linalg.norm(b - a)), 8) for a, b in second)
        self.assertEqual(first_lengths, second_lengths)

    def test_graph_connected_components(self):
        edges = [
            (np.asarray([0, 0, 0]), np.asarray([1, 0, 0])),
            (np.asarray([5, 0, 0]), np.asarray([6, 0, 0])),
        ]
        self.assertEqual(analyze_strut_graph(edges)["connectedComponentCount"], 2)

    def test_graph_isolated_node(self):
        graph = analyze_strut_graph([], extra_nodes=[np.asarray([2, 2, 2])])
        self.assertEqual(graph["isolatedNodeCount"], 1)

    def test_keep_largest_graph_component(self):
        large = [
            (np.asarray([0, 0, 0]), np.asarray([1, 0, 0])),
            (np.asarray([1, 0, 0]), np.asarray([2, 0, 0])),
        ]
        small = [(np.asarray([8, 0, 0]), np.asarray([9, 0, 0]))]
        groups, removed_components, removed_edges = keep_largest_graph_component([large + small])
        self.assertEqual(len(groups[0]), 2)
        self.assertEqual(removed_components, 1)
        self.assertEqual(removed_edges, 1)

    def test_open_triangle_has_three_boundary_edges(self):
        mesh = self.make_mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]])
        validation = validate_mesh(mesh)
        self.assertEqual(validation["boundaryEdgeCount"], 3)
        self.assertFalse(validation["isWatertight"])

    def test_closed_tetrahedron_is_edge_manifold_and_has_volume(self):
        mesh = self.make_mesh(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
            [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        )
        validation = validate_mesh(mesh)
        self.assertTrue(validation["isEdgeManifold"])
        self.assertTrue(validation["isWatertight"])
        self.assertAlmostEqual(validation["absoluteVolumeMm3"], 1.0 / 6.0, places=6)

    def test_non_manifold_edge_is_detected(self):
        mesh = self.make_mesh(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]],
            [[0, 1, 2], [1, 0, 3], [0, 1, 4]],
        )
        self.assertEqual(validate_mesh(mesh)["nonManifoldEdgeCount"], 1)

    def test_degenerate_triangle_is_detected(self):
        mesh = self.make_mesh([[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 1, 2]])
        self.assertEqual(validate_mesh(mesh)["degenerateTriangleCount"], 1)

    def test_duplicate_triangle_is_detected(self):
        mesh = self.make_mesh(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            [[0, 1, 2], [2, 0, 1]],
        )
        self.assertEqual(validate_mesh(mesh)["duplicateTriangleCount"], 1)

    def test_repair_removes_unused_vertex(self):
        mesh = self.make_mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0], [9, 9, 9]], [[0, 1, 2]])
        repaired = repair_mesh_for_export(mesh)
        self.assertEqual(validate_mesh(repaired)["unusedVertexCount"], 0)
        self.assertEqual(repaired.n_points, 3)

    def test_metadata_contains_required_parameters(self):
        args = SimpleNamespace(
            input_stl="", shape="box", points=80, random_seed=801, tube_radius=0.5,
            min_strut_length_mm=2.0, boundary_mode="exact", remove_disconnected_components=False,
        )
        edge = (np.asarray([0.0, 0.0, 0.0]), np.asarray([3.0, 0.0, 0.0]))
        mesh = create_tube_mesh([edge], 0.5)
        validation = validate_mesh(mesh)
        graph = analyze_strut_graph([edge])
        metadata = build_generation_metadata(
            args, np.zeros((80, 3)), 10, 12, [edge], OptimizationStats(12, 1, 11), graph,
            mesh, validation, validation, np.asarray([30.0, 30.0, 24.0]), 0, 0,
        )
        for key in ("generatorVersion", "sourceType", "dimensionsMm", "randomSeed", "strutDiameterMm", "boundaryMode", "statistics", "meshValidation"):
            self.assertIn(key, metadata)

    def test_reference_presets_can_export_stl(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            for count, seed in ((122, 1221), (80, 801)):
                points = generate_points_in_box(count, [15, 15, 12], seed)
                edges = filter_edges_inside_box(compute_voronoi_edges(points), [15, 15, 12])[:12]
                output = Path(temporary_directory) / f"preset_{count}.stl"
                export_stl(create_tube_mesh(edges, 0.5), output)
                self.assertTrue(output.exists())
                self.assertGreater(output.stat().st_size, 84)


if __name__ == "__main__":
    unittest.main()
