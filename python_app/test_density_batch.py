import tempfile
import unittest
import zipfile
from pathlib import Path

from density_batch import (
    EvaluationRegistry,
    final_quality_correction,
    parse_batch_targets,
    target_filename_token,
    warm_start_bracket,
)
from density_solver import DensityEvaluation, canonical_scale, solve_target_relative_density


class DensityBatchParsingTests(unittest.TestCase):
    def test_parses_common_separators_and_sorts(self):
        original, targets, duplicates = parse_batch_targets("15, 5; 10  20")
        self.assertEqual(original, [15, 5, 10, 20])
        self.assertEqual(targets, [5, 10, 15, 20])
        self.assertEqual(duplicates, [])

    def test_decimal_targets(self):
        self.assertEqual(parse_batch_targets("7.5, 12.25")[1], [7.5, 12.25])

    def test_duplicates_are_reported_and_removed(self):
        original, targets, duplicates = parse_batch_targets("5, 10, 5")
        self.assertEqual(original, [5, 10, 5])
        self.assertEqual(targets, [5, 10])
        self.assertEqual(duplicates, [5])

    def test_rejects_empty_input(self):
        with self.assertRaisesRegex(ValueError, "EMPTY"):
            parse_batch_targets("")

    def test_rejects_zero_and_over_hundred(self):
        for text in ("0, 5", "5, 101"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "OUT_OF_RANGE"):
                parse_batch_targets(text)

    def test_rejects_more_than_ten(self):
        with self.assertRaisesRegex(ValueError, "TEN"):
            parse_batch_targets(",".join(str(item) for item in range(1, 12)))

    def test_requires_two_unique_targets(self):
        with self.assertRaisesRegex(ValueError, "UNIQUE"):
            parse_batch_targets("5, 5")

    def test_safe_decimal_filename(self):
        self.assertEqual(target_filename_token(5), "05pct")
        self.assertEqual(target_filename_token(7.5), "07p5pct")
        self.assertNotIn("/", target_filename_token(7.5))


class EvaluationRegistryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def evaluator(scale, quality):
            self.calls.append((canonical_scale(scale), quality))
            density = scale * 0.1 if quality == "preview" else scale * scale * 0.1
            return DensityEvaluation(scale, density, density * 1000, {
                "meshValidation": {"isWatertight": True, "isEdgeManifold": True},
                "generationTimeSeconds": 1,
            }), f"{quality}-{canonical_scale(scale)}"

        self.registry = EvaluationRegistry(
            evaluator,
            {"preview": 0.2, "standard": 0.1, "final-quality": 0.05},
        )

    def test_registry_reuses_canonical_scale(self):
        first = self.registry.evaluate(1, "preview")
        second = self.registry.evaluate(1.000000, "preview")
        self.assertIs(first, second)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.registry.reused_evaluation_count, 1)

    def test_quality_is_part_of_registry_key(self):
        self.registry.evaluate(1, "preview")
        self.registry.evaluate(1, "final-quality")
        self.assertEqual(len(self.calls), 2)

    def test_warm_start_uses_known_curve(self):
        for scale in (0.5, 1.0, 1.5):
            self.registry.evaluate(scale, "preview")
        self.assertEqual(warm_start_bracket(self.registry.curve("preview"), 0.12, 0.25, 2.0), (1.0, 1.5))

    def test_final_correction_skips_when_verified(self):
        result = final_quality_correction(self.registry, 1.0, 0.1, 0.001, 0.25, 2.0)
        self.assertTrue(result["converged"])
        self.assertFalse(result["correctionWasRequired"])
        self.assertEqual(result["correctionIterations"], [])

    def test_final_correction_converges_with_local_expansion(self):
        result = final_quality_correction(
            self.registry, 1.0, 0.144, 0.005, 0.25, 2.0, maximum_iterations=4,
        )
        self.assertTrue(result["correctionWasRequired"])
        self.assertTrue(result["converged"])
        self.assertEqual(result["terminationReason"], "FINAL_TOLERANCE_REACHED")

    def test_final_correction_returns_best_at_iteration_limit(self):
        result = final_quality_correction(
            self.registry, 1.0, 0.19, 0.00001, 0.25, 2.0, maximum_iterations=1,
        )
        self.assertFalse(result["converged"])
        self.assertIsNotNone(result["selectedFinalScale"])
        self.assertLessEqual(len(result["correctionIterations"]), 1)

    def test_batch_order_does_not_change_synthetic_results(self):
        def solve(targets):
            solved = {}
            for target in sorted(targets):
                low, high = warm_start_bracket(self.registry.curve("preview"), target, 0.25, 2.0)
                result = solve_target_relative_density(
                    lambda scale: self.registry.evaluate(scale, "preview"),
                    target, 0.001, low, high, 12, 0.0001,
                )
                solved[target] = result["selectedGlobalRadiusScale"]
            return solved

        self.assertEqual(solve([0.05, 0.1, 0.15]), solve([0.15, 0.05, 0.1]))

    def test_zip_can_contain_only_explicit_safe_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "model_density_05pct.stl"
            expected.write_bytes(b"solid")
            archive_path = root / "series.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.write(expected, arcname=expected.name)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.namelist(), [expected.name])
                self.assertFalse(any(".." in item or item.startswith("/") for item in archive.namelist()))


if __name__ == "__main__":
    unittest.main()
