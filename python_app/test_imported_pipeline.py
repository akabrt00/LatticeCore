import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyvista as pv


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "python_app" / "voronoi_sphere_lines_mvp.py"


class ImportedMeshPipelineTests(unittest.TestCase):
    def run_pipeline(
        self,
        source: Path,
        output: Path,
        metadata_path: Path,
        *,
        points: int,
        seed: int,
        tube_radius: float,
        minimum_length: float,
        final_component_mode: str = "keep-all",
        extra_args: list[str] | None = None,
    ) -> dict:
        command = [
                sys.executable,
                str(GENERATOR),
                "--input-mesh", str(source),
                "--source-original-name", source.name,
                "--points", str(points),
                "--tube-radius", str(tube_radius),
                "--min-strut-length-mm", str(minimum_length),
                "--random-seed", str(seed),
                "--mesh-engine", "implicit-union",
                "--quality-preset", "preview",
                "--boundary-mode", "exact",
                "--final-component-mode", final_component_mode,
                "--no-show",
                "--export-stl", str(output),
                "--metadata-json", str(metadata_path),
            ]
        command.extend(extra_args or [])
        subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def assert_valid_imported_output(self, output: Path, metadata: dict) -> None:
        validation = metadata["outputMeshValidation"]
        self.assertTrue(output.exists())
        self.assertEqual(metadata["sourceType"], "imported-mesh")
        self.assertEqual(metadata["domainType"], "triangle-mesh")
        self.assertTrue(metadata["inputMeshValidation"]["isWatertight"])
        self.assertEqual(validation["boundaryEdgeCount"], 0)
        self.assertEqual(validation["nonManifoldEdgeCount"], 0)
        self.assertTrue(validation["isWatertight"])
        self.assertTrue(validation["isEdgeManifold"])
        self.assertGreater(validation["signedVolumeMm3"], 0)
        self.assertEqual(metadata["outsideVertexCount"], 0)
        self.assertLessEqual(metadata["maximumDomainViolationMm"], metadata["domainViolationToleranceMm"])

    def test_closed_imported_box_exports_implicit_lattice(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "offset-box.stl"
            output = temporary / "offset-box_voronoi_implicit.stl"
            metadata_path = temporary / "offset-box_voronoi_metadata.json"
            pv.Box(bounds=(10, 20, -8, 4, 30, 38)).triangulate().save(source)
            metadata = self.run_pipeline(
                source,
                output,
                metadata_path,
                points=24,
                seed=311,
                tube_radius=0.4,
                minimum_length=0.6,
            )
            self.assert_valid_imported_output(output, metadata)
            self.assertEqual(metadata["seedSampling"]["acceptedSeedCount"], 24)
            self.assertGreaterEqual(metadata["statistics"]["boundsMinX"], 10 - 1e-4)
            self.assertLessEqual(metadata["statistics"]["boundsMaxX"], 20 + 1e-4)

    def test_closed_imported_sphere_exports_single_valid_component(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "sphere.stl"
            output = temporary / "sphere_voronoi_implicit.stl"
            metadata_path = temporary / "sphere_voronoi_metadata.json"
            pv.Sphere(radius=6, center=(8, -4, 12), theta_resolution=32, phi_resolution=32).save(source)
            metadata = self.run_pipeline(
                source,
                output,
                metadata_path,
                points=36,
                seed=907,
                tube_radius=0.45,
                minimum_length=0.6,
                final_component_mode="keep-largest",
            )
            self.assert_valid_imported_output(output, metadata)
            self.assertEqual(metadata["seedSampling"]["acceptedSeedCount"], 36)
            self.assertEqual(metadata["outputMeshValidation"]["connectedComponentCount"], 1)

    def test_conformal_sphere_adds_surface_network_and_connectors(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "conformal-sphere.stl"
            output = temporary / "conformal-sphere_voronoi_implicit.stl"
            metadata_path = temporary / "conformal-sphere_voronoi_metadata.json"
            pv.Sphere(radius=6, theta_resolution=24, phi_resolution=24).save(source)
            metadata = self.run_pipeline(
                source,
                output,
                metadata_path,
                points=28,
                seed=417,
                tube_radius=0.45,
                minimum_length=0.55,
                final_component_mode="keep-largest",
                extra_args=[
                    "--boundary-structure-mode", "conformal-surface",
                    "--surface-sampling-mode", "custom",
                    "--surface-sampling-step-mm", "1.0",
                    "--surface-strut-diameter-mm", "0.9",
                    "--surface-connector-spacing-mm", "6",
                    "--surface-connector-maximum-length-mm", "10",
                ],
            )
            self.assert_valid_imported_output(output, metadata)
            self.assertEqual(metadata["boundaryStructureMode"], "conformal-surface")
            self.assertGreater(metadata["surfaceGraph"]["cleanSegmentCount"], 0)
            self.assertGreater(metadata["surfaceConnections"]["acceptedConnectorCount"], 0)
            self.assertEqual(metadata["surfacePlacementValidation"]["outsidePointCount"], 0)

    def test_closed_concave_l_shape_is_clipped_as_a_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "concave-l.stl"
            output = temporary / "concave-l_voronoi_implicit.stl"
            metadata_path = temporary / "concave-l_voronoi_metadata.json"
            footprint = np.asarray([[0, 0], [12, 0], [12, 4], [4, 4], [4, 12], [0, 12]], dtype=float)
            points = np.vstack((
                np.column_stack((footprint, np.zeros(len(footprint)))),
                np.column_stack((footprint, np.full(len(footprint), 8.0))),
            ))
            faces = [
                [6, 5, 4, 3, 2, 1, 0],
                [6, 6, 7, 8, 9, 10, 11],
            ]
            for index in range(6):
                next_index = (index + 1) % 6
                faces.append([4, index, next_index, next_index + 6, index + 6])
            pv.PolyData(points, np.asarray([value for face in faces for value in face])).triangulate().save(source)
            metadata = self.run_pipeline(
                source,
                output,
                metadata_path,
                points=40,
                seed=121,
                tube_radius=0.42,
                minimum_length=0.55,
            )
            self.assert_valid_imported_output(output, metadata)
            self.assertEqual(metadata["seedSampling"]["acceptedSeedCount"], 40)
            self.assertGreater(metadata["domainClipping"]["outputIntervalCount"], 0)
            self.assertGreater(metadata["domainClipping"]["surfaceIntersectionNodeCount"], 0)


if __name__ == "__main__":
    unittest.main()
