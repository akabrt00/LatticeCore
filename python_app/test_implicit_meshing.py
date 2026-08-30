import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from implicit_meshing import (
    BoxDomain,
    CapsulePrimitive,
    SpherePrimitive,
    capsule_sdf,
    generate_implicit_union_mesh,
    intersection_sdf,
    sphere_sdf,
    union_sdf,
)
from voronoi_sphere_lines_mvp import repair_mesh_for_export, validate_mesh


class SignedDistanceTests(unittest.TestCase):
    def test_sphere_sdf_signs(self):
        values = sphere_sdf(
            np.asarray([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=float),
            np.zeros(3),
            1.0,
        )
        self.assertLess(values[0], 0)
        self.assertAlmostEqual(values[1], 0.0)
        self.assertGreater(values[2], 0)

    def test_capsule_sdf_axis_surface_outside_and_endcap(self):
        points = np.asarray([[0, 0, 0], [0, 0.5, 0], [0, 0.8, 0], [2.5, 0, 0]], dtype=float)
        values = capsule_sdf(points, np.asarray([-1, 0, 0]), np.asarray([1, 0, 0]), 0.5)
        self.assertAlmostEqual(values[0], -0.5)
        self.assertAlmostEqual(values[1], 0.0)
        self.assertGreater(values[2], 0)
        self.assertAlmostEqual(values[3], 1.0)

    def test_degenerate_capsule_behaves_as_sphere(self):
        points = np.asarray([[0, 0, 0], [1, 0, 0]], dtype=float)
        values = capsule_sdf(points, np.zeros(3), np.zeros(3), 0.5)
        np.testing.assert_allclose(values, [-0.5, 0.5])

    def test_box_sdf_center_face_edge_and_outside(self):
        domain = BoxDomain(np.asarray([2.0, 3.0, 4.0]))
        values = domain.signed_distance(np.asarray([[0, 0, 0], [2, 0, 0], [2, 3, 0], [2.5, 0, 0]], dtype=float))
        self.assertLess(values[0], 0)
        self.assertAlmostEqual(values[1], 0.0)
        self.assertAlmostEqual(values[2], 0.0)
        self.assertGreater(values[3], 0)

    def test_union_uses_minimum(self):
        first = np.asarray([-1.0, 2.0])
        second = np.asarray([0.5, -2.0])
        np.testing.assert_allclose(union_sdf(first, second), [-1.0, -2.0])

    def test_intersection_uses_maximum(self):
        lattice = np.asarray([-1.0, -1.0, 1.0])
        domain = np.asarray([-2.0, 0.5, -2.0])
        np.testing.assert_allclose(intersection_sdf(lattice, domain), [-1.0, 0.5, 1.0])

    def test_box_intersection_signs(self):
        domain = BoxDomain(np.asarray([1.0, 1.0, 1.0]))
        points = np.asarray([[0, 0, 0], [2, 0, 0]], dtype=float)
        lattice = sphere_sdf(points, np.zeros(3), 3.0)
        final = intersection_sdf(lattice, domain.signed_distance(points))
        self.assertLess(final[0], 0)
        self.assertGreater(final[1], 0)


class ImplicitUnionIntegrationTests(unittest.TestCase):
    @staticmethod
    def generate(capsules=None, spheres=None, voxel_size=0.15, half_sizes=(3.0, 3.0, 3.0)):
        mesh, stats = generate_implicit_union_mesh(
            BoxDomain(np.asarray(half_sizes, dtype=float)),
            capsules or [],
            spheres or [],
            voxel_size,
            exact_domain_intersection=True,
        )
        mesh = repair_mesh_for_export(mesh)
        return mesh, validate_mesh(mesh), stats

    def assert_printable(self, validation, components=1):
        self.assertTrue(validation["isWatertight"])
        self.assertTrue(validation["isEdgeManifold"])
        self.assertEqual(validation["boundaryEdgeCount"], 0)
        self.assertEqual(validation["nonManifoldEdgeCount"], 0)
        self.assertEqual(validation["connectedComponentCount"], components)
        self.assertGreater(validation["signedVolumeMm3"], 0)

    def test_two_overlapping_spheres_are_one_printable_component(self):
        spheres = [SpherePrimitive(np.asarray([-0.45, 0, 0]), 1.0), SpherePrimitive(np.asarray([0.45, 0, 0]), 1.0)]
        _, validation, _ = self.generate(spheres=spheres)
        self.assert_printable(validation)

    def test_sphere_connected_to_capsule(self):
        capsules = [CapsulePrimitive(np.asarray([-1.5, 0, 0]), np.asarray([1.5, 0, 0]), 0.45)]
        spheres = [SpherePrimitive(np.asarray([1.5, 0, 0]), 0.7)]
        _, validation, _ = self.generate(capsules, spheres)
        self.assert_printable(validation)

    def test_intersecting_struts_have_true_union(self):
        capsules = [
            CapsulePrimitive(np.asarray([-2, 0, 0]), np.asarray([2, 0, 0]), 0.45),
            CapsulePrimitive(np.asarray([0, -2, 0]), np.asarray([0, 2, 0]), 0.45),
        ]
        _, validation, _ = self.generate(capsules)
        self.assert_printable(validation)

    def test_capsule_is_closed_at_box_cut(self):
        capsules = [CapsulePrimitive(np.asarray([-4, 0, 0]), np.asarray([4, 0, 0]), 0.55)]
        mesh, validation, _ = self.generate(capsules, half_sizes=(2.0, 2.0, 2.0))
        self.assert_printable(validation)
        self.assertGreaterEqual(mesh.bounds[0], -2.02)
        self.assertLessEqual(mesh.bounds[1], 2.02)

    def test_partially_outside_node_is_clipped_and_closed(self):
        spheres = [SpherePrimitive(np.asarray([1.8, 0, 0]), 0.7)]
        mesh, validation, _ = self.generate(spheres=spheres, half_sizes=(2.0, 2.0, 2.0))
        self.assert_printable(validation)
        self.assertLessEqual(mesh.bounds[1], 2.02)

    def test_manual_lattice_has_positive_volume(self):
        capsules = [
            CapsulePrimitive(np.asarray([-1.5, 0, 0]), np.asarray([0, 0, 1]), 0.4),
            CapsulePrimitive(np.asarray([0, 0, 1]), np.asarray([1.5, 0, 0]), 0.4),
            CapsulePrimitive(np.asarray([0, 0, 1]), np.asarray([0, 1.5, 0]), 0.4),
        ]
        _, validation, _ = self.generate(capsules)
        self.assert_printable(validation)

    def test_resolution_convergence(self):
        capsules = [CapsulePrimitive(np.asarray([-1.5, 0, 0]), np.asarray([1.5, 0, 0]), 0.5)]
        volumes = []
        for voxel_size in (0.25, 0.15, 0.10):
            _, validation, _ = self.generate(capsules, voxel_size=voxel_size, half_sizes=(2.5, 2.0, 2.0))
            self.assert_printable(validation)
            volumes.append(validation["absoluteVolumeMm3"])
        self.assertLess(abs(volumes[2] - volumes[1]) / volumes[2], 0.04)


if __name__ == "__main__":
    unittest.main()
