"""Shared runtime state for the persistent LatticeCore worker."""

from __future__ import annotations

import gc
import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable

from memory_metrics import MemoryLimits, estimate_object_bytes, memory_snapshot


class JobCancelledError(RuntimeError):
    """Raised at cooperative cancellation checkpoints."""


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    def check(self) -> None:
        if self.is_cancelled:
            raise JobCancelledError("JOB_CANCELLED")


@dataclass
class TopologySession:
    key: str
    values: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=monotonic)
    last_used_at: float = field(default_factory=monotonic)
    active_count: int = 0
    source_type: str = "unknown"

    def touch(self) -> None:
        self.last_used_at = monotonic()

    def release(self) -> None:
        self.values.clear()

    def estimated_size_bytes(self) -> int:
        return estimate_object_bytes(self.values)

    def metrics(self) -> dict[str, Any]:
        domain = self.values.get("triangle-domain")
        topology = sum(
            estimate_object_bytes(value)
            for name, value in self.values.items()
            if name.startswith("cache:topology")
        )
        surface = sum(
            estimate_object_bytes(value)
            for name, value in self.values.items()
            if "surface" in name
        )
        return {
            "sessionKeyPrefix": self.key[:12],
            "sourceType": self.source_type,
            "createdAt": datetime.fromtimestamp(
                datetime.now().timestamp() - max(0.0, monotonic() - self.created_at),
                tz=timezone.utc,
            ).isoformat(),
            "lastAccessedAt": datetime.fromtimestamp(
                datetime.now().timestamp() - max(0.0, monotonic() - self.last_used_at),
                tz=timezone.utc,
            ).isoformat(),
            "activeJobCount": self.active_count,
            "estimatedSizeBytes": self.estimated_size_bytes(),
            "domainSizeBytes": estimate_object_bytes(domain),
            "topologySizeBytes": topology,
            "surfaceSizeBytes": surface,
            "locatorPresent": bool(domain and getattr(domain[0] if isinstance(domain, tuple) else domain, "locator", None)),
            "meshPresent": bool(domain),
        }


class TopologySessionCache:
    def __init__(self, maximum_sessions: int = 3, idle_minutes: float = 30.0) -> None:
        self.maximum_sessions = max(1, int(maximum_sessions))
        self.idle_seconds = max(1.0, float(idle_minutes) * 60.0)
        self._sessions: OrderedDict[str, TopologySession] = OrderedDict()
        self._lock = threading.RLock()

    def acquire(self, key: str, source_type: str = "unknown") -> tuple[TopologySession, bool]:
        with self._lock:
            self._evict_idle()
            session = self._sessions.get(key)
            hit = session is not None
            if session is None:
                session = TopologySession(key, source_type=source_type)
                self._sessions[key] = session
            session.active_count += 1
            session.touch()
            self._sessions.move_to_end(key)
            self._evict_lru()
            return session, hit

    def release(self, session: TopologySession | None) -> None:
        if session is None:
            return
        with self._lock:
            session.active_count = max(0, session.active_count - 1)
            session.touch()
            self._evict_lru()

    def clear_details(self, scope: str = "unused") -> dict[str, int]:
        if scope not in {"unused", "all"}:
            raise ValueError("INVALID_CACHE_SCOPE")
        with self._lock:
            removable = [key for key, value in self._sessions.items() if value.active_count == 0]
            for key in removable:
                self._sessions.pop(key).release()
            gc.collect()
            return {
                "removedSessionCount": len(removable),
                "retainedActiveSessionCount": sum(value.active_count > 0 for value in self._sessions.values()),
            }

    def clear(self) -> int:
        return self.clear_details("unused")["removedSessionCount"]

    def evict_unused(self) -> dict[str, int]:
        return self.clear_details("unused")

    def estimated_size_bytes(self) -> int:
        with self._lock:
            return sum(value.estimated_size_bytes() for value in self._sessions.values())

    def session_metrics(self) -> list[dict[str, Any]]:
        with self._lock:
            return [value.metrics() for value in self._sessions.values()]

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "memorySessionCount": len(self._sessions),
                "activeMemorySessionCount": sum(value.active_count > 0 for value in self._sessions.values()),
                "maximumSessions": self.maximum_sessions,
                "idleMinutes": self.idle_seconds / 60.0,
                "sessionKeyPrefixes": [key[:12] for key in self._sessions],
                "estimatedSessionCacheBytes": self.estimated_size_bytes(),
            }

    def _evict_idle(self) -> None:
        now = monotonic()
        stale = [
            key for key, value in self._sessions.items()
            if value.active_count == 0 and now - value.last_used_at >= self.idle_seconds
        ]
        for key in stale:
            self._sessions.pop(key).release()

    def _evict_lru(self) -> None:
        while len(self._sessions) > self.maximum_sessions:
            removable = next(
                (key for key, value in self._sessions.items() if value.active_count == 0),
                None,
            )
            if removable is None:
                return
            self._sessions.pop(removable).release()


def build_topology_session_key(source_hash: str, arguments: Any) -> str:
    """Build a key containing topology inputs but no thickness/density inputs."""

    payload = {
        "sourceHash": source_hash,
        "importScale": arguments.import_scale,
        "componentMode": arguments.component_mode,
        "seedCount": arguments.points,
        "targetCellSizeMm": arguments.target_cell_size_mm,
        "randomSeed": arguments.random_seed,
        "boundaryOffsetMm": arguments.boundary_offset_mm,
        "minimumStrutLengthMm": arguments.min_strut_length_mm,
        "boundaryStructureMode": arguments.boundary_structure_mode,
        "surfaceSamplingMode": arguments.surface_sampling_mode,
        "surfaceSamplingStepMm": arguments.surface_sampling_step_mm,
        "surfacePlacementMode": arguments.surface_placement_mode,
        "surfaceInsetMode": arguments.surface_inset_mode,
        "surfaceInsetMm": arguments.surface_inset_mm if arguments.surface_inset_mode == "custom" else "automatic",
        "surfaceSmoothingIterations": arguments.surface_smoothing_iterations,
        "surfaceSmoothingStrength": arguments.surface_smoothing_strength,
        "connectorSpacingMm": arguments.surface_connector_spacing_mm,
        "connectorMaximumLengthMm": arguments.surface_connector_maximum_length_mm,
        "connectSurfaceToInterior": arguments.connect_surface_to_interior,
        "maximumSurfaceWorkingTriangles": arguments.maximum_surface_working_triangles,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class WorkerRuntime:
    def __init__(
        self,
        session_cache: TopologySessionCache,
        progress_callback: Callable[..., None] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.session_cache = session_cache
        self.progress_callback = progress_callback
        self.cancellation_token = cancellation_token or CancellationToken()
        self.session: TopologySession | None = None
        self.session_hit = False
        self.domain_reused = False
        self.locator_reused = False
        self.topology_reused = False

    def report(self, phase: str, message: str, fraction: float | None = None, **metrics: Any) -> None:
        self.cancellation_token.check()
        snapshot = memory_snapshot(
            estimated_session_cache_bytes=self.session_cache.estimated_size_bytes()
        )
        working_set = snapshot["processWorkingSetBytes"]
        limits = MemoryLimits.from_environment()
        if (
            working_set is not None
            and working_set > limits.soft_bytes
            and phase in {
                "building-domain", "computing-voronoi", "generating-final-mesh",
                "validating-final-mesh", "exporting-files", "result-ready",
            }
        ):
            eviction = self.session_cache.evict_unused()
            gc.collect()
            metrics = {
                **metrics,
                "memorySoftLimitExceeded": True,
                "memorySoftLimitBytes": limits.soft_bytes,
                "memoryEviction": eviction,
            }
        if self.progress_callback is not None:
            self.progress_callback(phase=phase, message=message, fraction=fraction, metrics=metrics)

    def activate(self, key: str, source_type: str = "unknown") -> None:
        if self.session is not None and self.session.key == key:
            return
        self.close()
        self.session, self.session_hit = self.session_cache.acquire(key, source_type)

    def get_or_create(self, name: str, factory: Callable[[], Any]) -> tuple[Any, bool]:
        self.cancellation_token.check()
        if self.session is not None and name in self.session.values:
            self.session.touch()
            return self.session.values[name], True
        value = factory()
        if self.session is not None:
            self.session.values[name] = value
            self.session.touch()
        return value, False

    def memory_get(self, level: str, key: str) -> Any | None:
        if self.session is None:
            return None
        value = self.session.values.get(f"cache:{level}:{key}")
        if value is not None:
            self.topology_reused = True
            self.session.touch()
        return value

    def memory_put(self, level: str, key: str, value: Any) -> None:
        if self.session is not None:
            self.session.values[f"cache:{level}:{key}"] = value
            self.session.touch()

    def metadata(self) -> dict[str, Any]:
        return {
            "sessionKeyPrefix": self.session.key[:12] if self.session else None,
            "hit": self.session_hit,
            "createdNewSession": bool(self.session and not self.session_hit),
            "domainReused": self.domain_reused,
            "locatorReused": self.locator_reused,
            "topologyReused": self.topology_reused,
        }

    def close(self) -> None:
        if self.session is not None:
            self.session_cache.release(self.session)
            self.session = None

    def status(self) -> dict[str, Any]:
        return {
            **self.session_cache.status(),
            "memory": memory_snapshot(
                estimated_session_cache_bytes=self.session_cache.estimated_size_bytes()
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
