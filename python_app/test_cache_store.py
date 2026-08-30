import tempfile
import unittest
from pathlib import Path

import numpy as np

from cache_store import CacheStore, build_cache_keys, canonical_hash


class CacheKeyTests(unittest.TestCase):
    def parameters(self):
        return {
            "format": "stl", "seedCount": 80, "randomSeed": 42,
            "strutDiameterMm": 1.0, "surfaceStrutDiameterMm": 1.0,
            "surfaceSamplingStepMm": 0.5, "surfaceSmoothingIterations": 2,
            "surfaceSmoothingStrength": 0.35, "surfacePlacementMode": "inset-inside",
            "surfaceInsetMode": "custom", "surfaceInsetMm": 0.5,
            "connectorSpacingMm": 5, "connectorMaximumLengthMm": 15,
            "voxelSizeMm": 0.15,
        }

    def test_canonical_key_is_stable(self):
        self.assertEqual(canonical_hash({"b": 2, "a": 1}), canonical_hash({"a": 1, "b": 2}))

    def test_voxel_only_invalidates_final_mesh(self):
        first = self.parameters()
        second = {**first, "voxelSizeMm": 0.2}
        a, b = build_cache_keys("source", first), build_cache_keys("source", second)
        self.assertEqual(a["seeds"], b["seeds"])
        self.assertEqual(a["volume-voronoi"], b["volume-voronoi"])
        self.assertEqual(a["surface-graph"], b["surface-graph"])
        self.assertNotEqual(a["final-mesh"], b["final-mesh"])

    def test_strut_diameter_preserves_seed_and_voronoi(self):
        first = self.parameters()
        second = {**first, "strutDiameterMm": 1.2}
        a, b = build_cache_keys("source", first), build_cache_keys("source", second)
        self.assertEqual(a["seeds"], b["seeds"])
        self.assertEqual(a["volume-voronoi"], b["volume-voronoi"])
        self.assertNotEqual(a["primitives"], b["primitives"])

    def test_random_seed_invalidates_dependent_layers(self):
        first = self.parameters()
        second = {**first, "randomSeed": 99}
        a, b = build_cache_keys("source", first), build_cache_keys("source", second)
        for level in ("seeds", "volume-voronoi", "surface-labels", "surface-graph", "final-mesh"):
            self.assertNotEqual(a[level], b[level])

    def test_surface_sampling_does_not_invalidate_volume(self):
        first = self.parameters()
        second = {**first, "surfaceSamplingStepMm": 0.8}
        a, b = build_cache_keys("source", first), build_cache_keys("source", second)
        self.assertEqual(a["volume-voronoi"], b["volume-voronoi"])
        self.assertNotEqual(a["surface-working-mesh"], b["surface-working-mesh"])

    def test_smoothing_does_not_invalidate_labels(self):
        first = self.parameters()
        second = {**first, "surfaceSmoothingStrength": 0.7}
        a, b = build_cache_keys("source", first), build_cache_keys("source", second)
        self.assertEqual(a["surface-labels"], b["surface-labels"])
        self.assertNotEqual(a["surface-graph"], b["surface-graph"])


class CacheIoTests(unittest.TestCase):
    def test_round_trip_and_disabled_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CacheStore(directory)
            values = np.arange(18, dtype=np.float64).reshape((3, 2, 3))
            self.assertTrue(store.put("seeds", "a" * 64, {"values": values}))
            loaded = store.get("seeds", "a" * 64, {"values": (None, 2, 3)})
            np.testing.assert_array_equal(loaded["values"], values)
            disabled = CacheStore(Path(directory) / "disabled", enabled=False)
            self.assertFalse(disabled.put("seeds", "b" * 64, {"values": values}))
            self.assertFalse(disabled.root.exists())

    def test_corrupt_and_nonfinite_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CacheStore(directory)
            key = "c" * 64
            store.put("seeds", key, {"values": np.ones((2, 3))})
            (store._entry("seeds", key) / "manifest.json").write_text("{broken", encoding="utf-8")
            self.assertIsNone(store.get("seeds", key))
            with self.assertRaises(ValueError):
                store.put("seeds", "d" * 64, {"values": np.asarray([[np.nan, 0, 0]])})

    def test_clear_rejects_arbitrary_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                CacheStore(directory).clear("../outside")


if __name__ == "__main__":
    unittest.main()
