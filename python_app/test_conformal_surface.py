import sys
import unittest
from pathlib import Path

import numpy as np
import pyvista as pv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conformal_surface import (
    clean_surface_graph,
    create_surface_connectors,
    extract_triangle_voronoi_segments,
    place_surface_points,
    smooth_surface_graph,
    solve_equal_distance_on_edge,
)
from imported_mesh import TriangleMeshDomain, clean_triangle_mesh


class EqualDistanceSolverTests(unittest.TestCase):
    def test_symmetric_midpoint(self):
        point = solve_equal_distance_on_edge([0, 0, 0], [2, 0, 0], [0, 0, 0], [2, 0, 0])
        np.testing.assert_allclose(point, [1, 0, 0])

    def test_asymmetric_solution(self):
        point = solve_equal_distance_on_edge([0, 0, 0], [4, 0, 0], [-1, 0, 0], [3, 0, 0])
        np.testing.assert_allclose(point, [1, 0, 0])

    def test_solution_outside_edge_is_rejected(self):
        self.assertIsNone(solve_equal_distance_on_edge([0, 0, 0], [1, 0, 0], [-5, 0, 0], [-3, 0, 0]))

    def test_zero_edge_and_equal_seeds_are_rejected(self):
        self.assertIsNone(solve_equal_distance_on_edge([0, 0, 0], [0, 0, 0], [-1, 0, 0], [1, 0, 0]))
        self.assertIsNone(solve_equal_distance_on_edge([0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 0, 0]))


class TriangleExtractionTests(unittest.TestCase):
    triangle = np.asarray([[0, 0, 0], [2, 0, 0], [0, 2, 0]], dtype=float)

    def test_one_label_produces_no_segment(self):
        self.assertEqual(extract_triangle_voronoi_segments(self.triangle, [0, 0, 0], [[0, 0, 0]]), [])

    def test_two_labels_produce_segment_inside_triangle(self):
        seeds = np.asarray([[0, 0, 0], [2, 2, 0]], dtype=float)
        segments = extract_triangle_voronoi_segments(self.triangle, [0, 1, 1], seeds)
        self.assertEqual(len(segments), 1)
        for point in segments[0]:
            self.assertGreaterEqual(point[0], -1e-8)
            self.assertGreaterEqual(point[1], -1e-8)
            self.assertLessEqual(point[0] + point[1], 2 + 1e-8)

    def test_three_labels_produce_deterministic_junction(self):
        seeds = np.asarray([[0, 0, 0], [2, 0, 0], [0, 2, 0]], dtype=float)
        first = extract_triangle_voronoi_segments(self.triangle, [0, 1, 2], seeds)
        second = extract_triangle_voronoi_segments(self.triangle, [0, 1, 2], seeds)
        self.assertGreaterEqual(len(first), 2)
        for left, right in zip(first, second):
            np.testing.assert_allclose(left, right)

    def test_degenerate_triangle_is_safe(self):
        line = np.asarray([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=float)
        self.assertEqual(extract_triangle_voronoi_segments(line, [0, 1, 1], [[0, 0, 0], [2, 0, 0]]), [])


class SurfaceGraphTests(unittest.TestCase):
    def test_cleanup_removes_duplicate_and_zero_segments_and_computes_degrees(self):
        segments = [
            (np.asarray([0, 0, 0.0]), np.asarray([1, 0, 0.0])),
            (np.asarray([1, 0, 0.0]), np.asarray([0, 0, 0.0])),
            (np.asarray([1, 0, 0.0]), np.asarray([2, 0, 0.0])),
            (np.asarray([2, 0, 0.0]), np.asarray([2, 0, 0.0])),
        ]
        clean, nodes, stats, components = clean_surface_graph(segments, 1e-5)
        self.assertEqual(len(clean), 2)
        self.assertEqual(len(nodes), 3)
        self.assertEqual(stats["removedDuplicateSegmentCount"], 1)
        self.assertEqual(stats["removedZeroLengthSegmentCount"], 1)
        self.assertEqual(stats["maximumNodeDegree"], 2)
        self.assertEqual(len(components), 1)

    def test_smoothing_preserves_edge_count_and_projects_to_surface(self):
        mesh, validation = clean_triangle_mesh(pv.Sphere(radius=2, theta_resolution=24, phi_resolution=24))
        domain = TriangleMeshDomain(mesh, validation=validation)
        points = [np.asarray([2, 0, 0.0]), np.asarray([1.4, 1.4, 0.0]), np.asarray([0, 2, 0.0])]
        segments = [(points[0], points[1]), (points[1], points[2])]
        smoothed = smooth_surface_graph(segments, domain, 2, 0.35, 1e-5)
        self.assertEqual(len(smoothed), 2)
        middle = smoothed[0][1]
        self.assertLess(abs(float(domain.signed_distance(middle))), 1e-4)


class PlacementAndConnectorTests(unittest.TestCase):
    def test_sphere_inset_moves_points_inward(self):
        mesh, validation = clean_triangle_mesh(pv.Sphere(radius=2, theta_resolution=32, phi_resolution=32))
        domain = TriangleMeshDomain(mesh, validation=validation)
        placed, stats = place_surface_points([[2, 0, 0]], domain, "inset-inside", 0.25)
        self.assertLess(np.linalg.norm(placed[0]), 2)
        self.assertEqual(stats["outsidePointCount"], 0)

    def test_reversed_input_normals_do_not_break_inset(self):
        mesh = pv.Box(bounds=(-1, 1, -1, 1, -1, 1)).triangulate()
        mesh.flip_faces(inplace=True)
        cleaned, validation = clean_triangle_mesh(mesh)
        domain = TriangleMeshDomain(cleaned, validation=validation)
        placed, stats = place_surface_points([[1, 0, 0]], domain, "inset-inside", 0.2)
        self.assertLess(placed[0, 0], 1)
        self.assertEqual(stats["outsidePointCount"], 0)

    def test_connector_accepts_near_node_and_rejects_too_long(self):
        mesh, validation = clean_triangle_mesh(pv.Box(bounds=(-2, 2, -2, 2, -2, 2)).triangulate())
        domain = TriangleMeshDomain(mesh, validation=validation)
        surface = np.asarray([[1.8, 0, 0]], dtype=float)
        interior = [(np.asarray([0, 0, 0.0]), np.asarray([0, 1, 0.0]))]
        accepted, stats = create_surface_connectors(surface, [[0]], interior, domain, 5, 3, 1)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(stats["acceptedConnectorCount"], 1)
        rejected, stats = create_surface_connectors(surface, [[0]], interior, domain, 5, 0.5, 1)
        self.assertEqual(rejected, [])
        self.assertEqual(stats["unconnectedSurfaceComponentCount"], 1)


if __name__ == "__main__":
    unittest.main()
