import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINES = json.loads((ROOT / "python_app" / "geometry_baselines.json").read_text(encoding="utf-8"))


class GeometryBaselineTests(unittest.TestCase):
    def test_parametric_box_preview(self):
        baseline = BASELINES["parametricBoxPreview"]
        expected = baseline["expected"]
        tolerance = baseline["tolerances"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "baseline.stl"
            metadata_path = Path(directory) / "baseline.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "python_app" / "voronoi_sphere_lines_mvp.py"),
                    "--shape", "box",
                    "--box-size-x", "6", "--box-size-y", "6", "--box-size-z", "6",
                    "--points", "8", "--tube-radius", "0.5", "--surface-tube-radius", "0.5",
                    "--min-strut-length-mm", "0.4", "--random-seed", "4242",
                    "--mesh-engine", "implicit-union", "--quality-preset", "preview",
                    "--no-cache-enabled", "--no-show",
                    "--export-stl", str(output), "--metadata-json", str(metadata_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        statistics = metadata["statistics"]
        validation = metadata["meshValidation"]
        volume = metadata["volumeStatistics"]["latticeVolumeMm3"]
        self.assertEqual(metadata["seedCount"], expected["seedCount"])
        self.assertEqual(statistics["strutCountAfterFiltering"], expected["strutGraphCount"])
        for actual, reference in zip(
            [statistics["boundsMinX"], statistics["boundsMinY"], statistics["boundsMinZ"]],
            expected["boundsMin"],
        ):
            self.assertAlmostEqual(actual, reference, delta=tolerance["boundsAbsoluteMm"])
        for name in ("meshVertexCount", "meshTriangleCount"):
            self.assertAlmostEqual(
                statistics[name],
                expected[name],
                delta=expected[name] * tolerance["meshCountRelative"],
            )
        self.assertAlmostEqual(volume, expected["volumeMm3"], delta=expected["volumeMm3"] * tolerance["volumeRelative"])
        self.assertEqual(validation["boundaryEdgeCount"], expected["boundaryEdgeCount"])
        self.assertEqual(validation["nonManifoldEdgeCount"], expected["nonManifoldEdgeCount"])
        self.assertEqual(validation["connectedComponentCount"], expected["componentCount"])
        self.assertEqual(validation["isWatertight"], expected["watertight"])
        self.assertEqual(validation["isEdgeManifold"], expected["edgeManifold"])


if __name__ == "__main__":
    unittest.main()
