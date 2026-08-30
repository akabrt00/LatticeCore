import unittest
from types import SimpleNamespace

from worker_runtime import (
    CancellationToken,
    JobCancelledError,
    TopologySessionCache,
    build_topology_session_key,
)


def arguments(**overrides):
    values = {
        "import_scale": 1.0,
        "component_mode": "require-single",
        "points": 80,
        "target_cell_size_mm": 0.0,
        "random_seed": 42,
        "boundary_offset_mm": 0.0,
        "min_strut_length_mm": 0.4,
        "boundary_structure_mode": "conformal-surface",
        "surface_sampling_mode": "automatic",
        "surface_sampling_step_mm": 0.5,
        "surface_placement_mode": "inset-inside",
        "surface_inset_mode": "automatic",
        "surface_inset_mm": 0.3,
        "surface_smoothing_iterations": 2,
        "surface_smoothing_strength": 0.35,
        "surface_connector_spacing_mm": 5.0,
        "surface_connector_maximum_length_mm": 15.0,
        "connect_surface_to_interior": True,
        "maximum_surface_working_triangles": 50_000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class CancellationTests(unittest.TestCase):
    def test_token_raises_controlled_error(self):
        token = CancellationToken()
        token.cancel()
        with self.assertRaises(JobCancelledError):
            token.check()


class SessionKeyTests(unittest.TestCase):
    def test_density_and_voxel_independent_values_are_not_in_key(self):
        first = build_topology_session_key("source", arguments())
        second = build_topology_session_key("source", arguments())
        self.assertEqual(first, second)

    def test_random_seed_changes_key(self):
        self.assertNotEqual(
            build_topology_session_key("source", arguments()),
            build_topology_session_key("source", arguments(random_seed=43)),
        )

    def test_surface_sampling_changes_key(self):
        self.assertNotEqual(
            build_topology_session_key("source", arguments()),
            build_topology_session_key("source", arguments(surface_sampling_step_mm=0.8)),
        )


class SessionCacheTests(unittest.TestCase):
    def test_reuses_compatible_session(self):
        cache = TopologySessionCache()
        first, hit = cache.acquire("same")
        self.assertFalse(hit)
        cache.release(first)
        second, hit = cache.acquire("same")
        self.assertTrue(hit)
        self.assertIs(first, second)
        cache.release(second)

    def test_lru_removes_oldest_inactive_session(self):
        cache = TopologySessionCache(maximum_sessions=2)
        first, _ = cache.acquire("first")
        cache.release(first)
        second, _ = cache.acquire("second")
        cache.release(second)
        third, _ = cache.acquire("third")
        cache.release(third)
        self.assertEqual(cache.status()["sessionKeyPrefixes"], ["second", "third"])

    def test_active_session_is_not_removed(self):
        cache = TopologySessionCache(maximum_sessions=1)
        active, _ = cache.acquire("active")
        other, _ = cache.acquire("other")
        self.assertEqual(cache.status()["memorySessionCount"], 2)
        cache.release(other)
        self.assertEqual(cache.status()["sessionKeyPrefixes"], ["active"])
        cache.release(active)

    def test_clear_keeps_active_and_removes_inactive(self):
        cache = TopologySessionCache()
        active, _ = cache.acquire("active")
        inactive, _ = cache.acquire("inactive")
        cache.release(inactive)
        self.assertEqual(cache.clear(), 1)
        self.assertEqual(cache.status()["memorySessionCount"], 1)
        cache.release(active)
        self.assertEqual(cache.clear(), 1)


if __name__ == "__main__":
    unittest.main()
