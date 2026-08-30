import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np
import pyvista as pv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from implicit_meshing import BoxDomain
from imported_mesh import (
    TriangleMeshDomain,
    apply_component_mode,
    clean_triangle_mesh,
    clip_segment_to_domain_intervals,
    generate_points_in_domain,
    load_triangle_mesh,
    validate_surface_mesh,
)


class TriangleMeshDomainTests(unittest.TestCase):
    @staticmethod
    def _five_closed_components():
        boxes = [
            pv.Box(bounds=(index * 3.0, index * 3.0 + 1.0, 0, 1, 0, 1)).triangulate()
            for index in range(5)
        ]
        return pv.merge(boxes, merge_points=False).extract_surface(
            algorithm="dataset_surface"
        ).triangulate()

    def test_multi_component_modes_are_explicit_and_deterministic(self):
        mesh = self._five_closed_components()

        selected, removed = apply_component_mode(mesh, "use-all-closed")
        self.assertEqual(removed, 0)
        self.assertEqual(validate_surface_mesh(selected)["connectedComponentCount"], 5)

        largest, removed = apply_component_mode(mesh, "keep-largest")
        self.assertEqual(removed, 4)
        self.assertEqual(validate_surface_mesh(largest)["connectedComponentCount"], 1)

        with self.assertRaisesRegex(ValueError, "5 components"):
            apply_component_mode(mesh, "require-single")

    def test_domain_defaults_to_all_closed_components(self):
        domain = TriangleMeshDomain(self._five_closed_components())
        self.assertEqual(domain.validate()["connectedComponentCount"], 5)
        self.assertEqual(domain.component_mode, "use-all-closed")

    def test_box_signed_distance_and_closest_point(self):
        mesh = pv.Box(bounds=(-2, 2, -1, 1, -0.5, 0.5)).triangulate()
        cleaned, validation = clean_triangle_mesh(mesh)
        domain = TriangleMeshDomain(cleaned, validation=validation)
        values = domain.signed_distance(np.asarray([[0, 0, 0], [3, 0, 0], [2, 0, 0]], dtype=float))
        self.assertLess(values[0], 0)
        self.assertGreater(values[1], 0)
        self.assertAlmostEqual(values[2], 0.0, places=5)
        np.testing.assert_allclose(domain.closest_points([[3, 0, 0]])[0], [2, 0, 0], atol=1e-6)

    def test_sphere_bounds_and_contains(self):
        mesh, validation = clean_triangle_mesh(pv.Sphere(radius=2.0, theta_resolution=24, phi_resolution=24))
        domain = TriangleMeshDomain(mesh, validation=validation)
        minimum, maximum = domain.bounds()
        np.testing.assert_allclose(minimum, [-2, -2, -2], atol=0.03)
        np.testing.assert_allclose(maximum, [2, 2, 2], atol=0.03)
        np.testing.assert_array_equal(domain.contains([[0, 0, 0], [3, 0, 0]]), [True, False])

    def test_reversed_orientation_is_calibrated(self):
        mesh = pv.Box(bounds=(-1, 1, -1, 1, -1, 1)).triangulate()
        mesh.flip_faces(inplace=True)
        cleaned, validation = clean_triangle_mesh(mesh)
        domain = TriangleMeshDomain(cleaned, validation=validation)
        self.assertLess(float(domain.signed_distance([0, 0, 0])), 0)
        self.assertGreater(float(domain.signed_distance([3, 0, 0])), 0)

    def test_open_box_is_rejected(self):
        box = pv.Box(bounds=(-1, 1, -1, 1, -1, 1)).triangulate()
        faces = box.faces.reshape(-1, 4)[:-2].ravel()
        open_box = pv.PolyData(np.asarray(box.points), faces)
        with self.assertRaisesRegex(ValueError, "open"):
            TriangleMeshDomain(open_box)

    def test_non_manifold_surface_is_rejected(self):
        box = pv.Box(bounds=(-1, 1, -1, 1, -1, 1)).triangulate()
        faces = box.faces.reshape(-1, 4)
        extra = faces[0].copy()
        extra[1], extra[2] = extra[2], extra[1]
        broken = pv.PolyData(np.asarray(box.points), np.vstack((faces, extra)).ravel())
        with self.assertRaisesRegex(ValueError, "non-manifold"):
            TriangleMeshDomain(broken)

    def test_degenerate_triangle_cleanup(self):
        box = pv.Box(bounds=(-1, 1, -1, 1, -1, 1)).triangulate()
        faces = box.faces.reshape(-1, 4)
        degenerate = np.asarray([3, 0, 0, 1])
        dirty = pv.PolyData(np.asarray(box.points), np.vstack((faces, degenerate)).ravel())
        cleaned, validation = clean_triangle_mesh(dirty)
        self.assertEqual(validation["degenerateTriangleCount"], 0)
        self.assertTrue(TriangleMeshDomain(cleaned, validation=validation).validate()["isWatertight"])

    def test_chunked_distance_matches_direct_batch(self):
        mesh, validation = clean_triangle_mesh(pv.Sphere(radius=1.0))
        domain = TriangleMeshDomain(mesh, validation=validation)
        points = np.random.default_rng(7).uniform(-2, 2, size=(100, 3))
        direct = domain._raw_signed_distance(points, chunk_size=100)
        chunked = domain._raw_signed_distance(points, chunk_size=9)
        np.testing.assert_allclose(chunked, direct)

    def test_stl_and_obj_loading_preserve_coordinates_and_scale(self):
        mesh = pv.Box(bounds=(10, 12, 20, 24, 30, 36)).triangulate()
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".stl", ".obj"):
                path = Path(directory) / f"shape{suffix}"
                mesh.save(path)
                loaded, validation = load_triangle_mesh(path, import_scale=2.0)
                self.assertEqual(validation["detectedFormat"], suffix[1:])
                np.testing.assert_allclose(loaded.bounds, [20, 24, 40, 48, 60, 72], atol=1e-5)


class DomainSamplingAndClippingTests(unittest.TestCase):
    def test_seed_sampling_is_deterministic_and_respects_offset(self):
        domain = BoxDomain(np.asarray([2.0, 2.0, 2.0]))
        first = generate_points_in_domain(domain, 30, 99, boundary_offset_mm=0.25)
        second = generate_points_in_domain(domain, 30, 99, boundary_offset_mm=0.25)
        np.testing.assert_allclose(first.points, second.points)
        self.assertTrue(np.all(domain.signed_distance(first.points) <= -0.25))
        self.assertEqual(first.metadata["acceptedSeedCount"], 30)

    def test_impossible_offset_reports_error(self):
        domain = BoxDomain(np.asarray([1.0, 1.0, 1.0]))
        with self.assertRaisesRegex(ValueError, "boundaryOffsetMm"):
            generate_points_in_domain(domain, 10, 1, boundary_offset_mm=2.0, maximum_sampling_attempts=3000)

    def test_box_segment_cases(self):
        domain = BoxDomain(np.asarray([1.0, 1.0, 1.0]))
        inside = clip_segment_to_domain_intervals([-0.5, 0, 0], [0.5, 0, 0], domain, 0.1)
        outside = clip_segment_to_domain_intervals([2, 0, 0], [3, 0, 0], domain, 0.1)
        crossing = clip_segment_to_domain_intervals([-2, 0, 0], [2, 0, 0], domain, 0.1)
        self.assertEqual(len(inside), 1)
        self.assertEqual(len(outside), 0)
        self.assertEqual(len(crossing), 1)
        np.testing.assert_allclose(crossing[0][0], [-1, 0, 0], atol=1e-4)
        np.testing.assert_allclose(crossing[0][1], [1, 0, 0], atol=1e-4)

    def test_sphere_crossing_and_surface_roots(self):
        mesh, validation = clean_triangle_mesh(pv.Sphere(radius=1.0, theta_resolution=32, phi_resolution=32))
        domain = TriangleMeshDomain(mesh, validation=validation)
        intervals = clip_segment_to_domain_intervals([-2, 0, 0], [2, 0, 0], domain, 0.05)
        self.assertEqual(len(intervals), 1)
        self.assertLess(abs(float(domain.signed_distance(intervals[0][0]))), 1e-4)
        self.assertLess(abs(float(domain.signed_distance(intervals[0][1]))), 1e-4)

    def test_torus_can_produce_multiple_intervals(self):
        mesh, validation = clean_triangle_mesh(pv.ParametricTorus(ringradius=2.0, crosssectionradius=0.5))
        domain = TriangleMeshDomain(mesh, validation=validation)
        intervals = clip_segment_to_domain_intervals([-3, 0, 0], [3, 0, 0], domain, 0.05)
        self.assertEqual(len(intervals), 2)


if __name__ == "__main__":
    unittest.main()
