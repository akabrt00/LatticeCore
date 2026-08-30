import os
import unittest
from unittest.mock import patch

from memory_metrics import (
    MIB,
    MemoryLimitExceeded,
    memory_snapshot,
    voxel_memory_preflight,
)
from worker_runtime import TopologySessionCache


class ProcessMemoryTests(unittest.TestCase):
    def test_unavailable_process_memory_is_null(self):
        with patch("memory_metrics.process_memory", return_value=(None, None)):
            snapshot = memory_snapshot()
        self.assertIsNone(snapshot["processWorkingSetBytes"])
        self.assertIsNone(snapshot["processPeakWorkingSetBytes"])
        self.assertIn("pythonTrackedCurrentBytes", snapshot)

    def test_metadata_contains_no_paths(self):
        snapshot = memory_snapshot(estimated_numpy_bytes=123)
        encoded = str(snapshot)
        self.assertNotIn("C:\\Users\\", encoded)
        self.assertNotIn("/tmp/", encoded)


class MemoryLimitTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "LATTICE_WORKER_MEMORY_SOFT_LIMIT_MIB": "100",
                "LATTICE_WORKER_MEMORY_HARD_LIMIT_MIB": "400",
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_estimate_below_soft_limit(self):
        with patch("memory_metrics.process_memory", return_value=(20 * MIB, 30 * MIB)):
            result = voxel_memory_preflight(10 * MIB)
        self.assertFalse(result["softLimitExceeded"])

    def test_estimate_above_soft_limit(self):
        with patch("memory_metrics.process_memory", return_value=(250 * MIB, 250 * MIB)):
            result = voxel_memory_preflight(20 * MIB)
        self.assertTrue(result["softLimitExceeded"])
        self.assertFalse(result["hardLimitExceeded"])

    def test_estimate_above_hard_limit_is_rejected(self):
        with patch("memory_metrics.process_memory", return_value=(390 * MIB, 390 * MIB)):
            with self.assertRaises(MemoryLimitExceeded):
                voxel_memory_preflight(20 * MIB)


class SessionMemoryTests(unittest.TestCase):
    def test_metrics_and_eviction_preserve_active_session(self):
        cache = TopologySessionCache(maximum_sessions=3)
        active, _ = cache.acquire("active-session", "imported-mesh")
        active.values["cache:topology:graph"] = bytearray(1024)
        inactive, _ = cache.acquire("inactive-session", "parametric-box")
        cache.release(inactive)
        details = cache.evict_unused()
        self.assertEqual(details["removedSessionCount"], 1)
        self.assertEqual(details["retainedActiveSessionCount"], 1)
        metrics = cache.session_metrics()
        self.assertEqual(metrics[0]["sourceType"], "imported-mesh")
        self.assertEqual(metrics[0]["activeJobCount"], 1)
        self.assertNotIn("sourceHash", metrics[0])
        cache.release(active)


if __name__ == "__main__":
    unittest.main()
