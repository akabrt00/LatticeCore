import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from debug_payload import deterministic_stride, write_debug_payload


class DebugPayloadTests(unittest.TestCase):
    def test_deterministic_downsampling(self):
        values = np.arange(300, dtype=np.float32).reshape((-1, 3))
        first, reduced = deterministic_stride(values, 17)
        second, _ = deterministic_stride(values, 17)
        self.assertTrue(reduced)
        np.testing.assert_array_equal(first, second)

    def test_manifest_offsets_and_finite_binary_data(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "debug.json"
            buffer_path = Path(directory) / "debug.bin"
            manifest = write_debug_payload({
                "seed-points": np.arange(30, dtype=float).reshape((-1, 3)),
                "clipped-interior-centerlines": np.arange(60, dtype=float).reshape((-1, 2, 3)),
            }, manifest_path, buffer_path, maximum_points=4, maximum_segments=7)
            seed = manifest["layers"]["seed-points"]
            edges = manifest["layers"]["clipped-interior-centerlines"]
            self.assertEqual(seed["byteOffset"], 0)
            self.assertEqual(edges["byteOffset"], seed["byteLength"])
            self.assertEqual(manifest["totalByteLength"], buffer_path.stat().st_size)
            self.assertEqual(json.loads(manifest_path.read_text())["formatVersion"], 1)
            self.assertTrue(np.all(np.isfinite(np.frombuffer(buffer_path.read_bytes(), dtype=np.float32))))

    def test_nonequivalent_shapes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                write_debug_payload(
                    {"seed-points": np.ones((2, 2))},
                    Path(directory) / "a.json",
                    Path(directory) / "a.bin",
                )


if __name__ == "__main__":
    unittest.main()
