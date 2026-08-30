import unittest

import pyvista as pv

from density_solver import DensityEvaluation, canonical_scale, density_statistics, mass_estimate, solve_target_relative_density
from voronoi_sphere_lines_mvp import validate_mesh


class DensityMetricTests(unittest.TestCase):
    def test_closed_box_volume(self):
        result = validate_mesh(pv.Box(bounds=(0, 2, 0, 3, 0, 4)).triangulate())
        self.assertTrue(result["isWatertight"])
        self.assertAlmostEqual(result["absoluteVolumeMm3"], 24.0, places=6)

    def test_multiple_components_sum_absolute_volumes_even_if_reversed(self):
        first = pv.Box(bounds=(0, 1, 0, 1, 0, 1)).triangulate()
        second = pv.Box(bounds=(3, 5, 0, 1, 0, 1)).triangulate()
        second.flip_faces(inplace=True)
        result = validate_mesh(first.merge(second, merge_points=False))
        self.assertEqual(result["connectedComponentCount"], 2)
        self.assertAlmostEqual(result["absoluteVolumeMm3"], 3.0, places=6)
        self.assertEqual(len(result["componentVolumesMm3"]), 2)

    def test_open_mesh_is_not_valid_for_exact_volume(self):
        result = validate_mesh(pv.Plane().triangulate())
        self.assertFalse(result["isWatertight"])

    def test_density_porosity_and_mass(self):
        stats = density_statistics(1000.0, [80.0, -20.0])
        self.assertAlmostEqual(stats["relativeDensity"], 0.1)
        self.assertAlmostEqual(stats["porosity"], 0.9)
        mass = mass_estimate(stats, 1.24)
        self.assertAlmostEqual(mass["latticeVolumeCm3"], 0.1)
        self.assertAlmostEqual(mass["estimatedMassG"], 0.124)
        self.assertAlmostEqual(mass["massReductionPercent"], 90.0)

    def test_missing_material_density_returns_null_mass(self):
        self.assertIsNone(mass_estimate(density_statistics(1000, [100]), None)["estimatedMassG"])

    def test_invalid_domain_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "DOMAIN_VOLUME_INVALID"):
            density_statistics(0, [1])


class DensitySolverTests(unittest.TestCase):
    @staticmethod
    def evaluator(scale):
        return DensityEvaluation(scale, 0.04 * scale * scale, 40 * scale * scale, {"cacheHit": scale != 0.25})

    def test_monotonic_solver_converges(self):
        result = solve_target_relative_density(self.evaluator, 0.16, tolerance=0.0002)
        self.assertTrue(result["converged"])
        self.assertAlmostEqual(result["selectedGlobalRadiusScale"], 2.0, delta=0.01)

    def test_exact_bounds(self):
        self.assertEqual(solve_target_relative_density(self.evaluator, 0.0025)["selectedGlobalRadiusScale"], 0.25)
        self.assertEqual(solve_target_relative_density(self.evaluator, 0.36)["selectedGlobalRadiusScale"], 3.0)

    def test_outside_bracket_has_specific_reason(self):
        result = solve_target_relative_density(self.evaluator, 0.8)
        self.assertFalse(result["converged"])
        self.assertEqual(result["terminationReason"], "TARGET_DENSITY_NOT_BRACKETED")

    def test_maximum_iterations_keeps_best(self):
        result = solve_target_relative_density(self.evaluator, 0.13, tolerance=1e-9, maximum_iterations=1)
        self.assertFalse(result["converged"])
        self.assertEqual(result["terminationReason"], "maximum-iterations")

    def test_significant_nonmonotonicity_is_reported(self):
        result = solve_target_relative_density(
            lambda scale: DensityEvaluation(scale, 0.3 - 0.05 * scale, (0.3 - 0.05 * scale) * 1000),
            0.2,
            tolerance=0.001,
        )
        self.assertTrue(result["monotonicityWarning"])

    def test_scale_key_is_canonical(self):
        self.assertEqual(canonical_scale(1), canonical_scale(1.0))
        self.assertEqual(canonical_scale(1.0), canonical_scale(1.000000))


if __name__ == "__main__":
    unittest.main()
