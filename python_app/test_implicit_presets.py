import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "python_app" / "voronoi_sphere_lines_mvp.py"


class ImplicitReferencePresetTests(unittest.TestCase):
    def assert_reference_preset(self, seed_count: int, random_seed: int):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_stl = Path(temporary_directory) / f"lattice_{seed_count}_implicit.stl"
            output_json = Path(temporary_directory) / f"lattice_{seed_count}_metadata.json"
            subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--shape", "box",
                    "--box-size-x", "30",
                    "--box-size-y", "30",
                    "--box-size-z", "24",
                    "--points", str(seed_count),
                    "--tube-radius", "0.5",
                    "--surface-tube-radius", "0.52",
                    "--min-strut-length-mm", "2",
                    "--random-seed", str(random_seed),
                    "--mesh-engine", "implicit-union",
                    "--quality-preset", "standard",
                    "--boundary-mode", "exact",
                    "--no-show",
                    "--export-stl", str(output_stl),
                    "--metadata-json", str(output_json),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertTrue(output_stl.exists())
            self.assertGreater(output_stl.stat().st_size, 84)
            metadata = json.loads(output_json.read_text(encoding="utf-8"))
            validation = metadata["meshValidation"]
            statistics = metadata["statistics"]
            self.assertEqual(metadata["meshEngine"], "implicit-union")
            self.assertEqual(metadata["clippingImplementation"], "implicit-sdf-intersection")
            self.assertEqual(metadata["qualityPreset"], "standard")
            self.assertLessEqual(statistics["maximumBoundaryOvershootMm"], 0.02)
            self.assertEqual(validation["boundaryEdgeCount"], 0)
            self.assertEqual(validation["nonManifoldEdgeCount"], 0)
            self.assertEqual(validation["degenerateTriangleCount"], 0)
            self.assertEqual(validation["connectedComponentCount"], 1)
            self.assertTrue(validation["isWatertight"])
            self.assertTrue(validation["isEdgeManifold"])
            self.assertGreater(validation["signedVolumeMm3"], 0)

    def test_reference_122_standard_implicit(self):
        self.assert_reference_preset(122, 1221)

    def test_reference_80_standard_implicit(self):
        self.assert_reference_preset(80, 801)


if __name__ == "__main__":
    unittest.main()
