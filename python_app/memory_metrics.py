"""Process and allocation memory metrics for the persistent worker."""

from __future__ import annotations

import ctypes
import os
import tracemalloc
from dataclasses import dataclass
from typing import Any


MIB = 1024**2


class MemoryLimitExceeded(RuntimeError):
    error_code = "MEMORY_LIMIT_EXCEEDED"


def _windows_process_memory() -> tuple[int | None, int | None]:
    if os.name != "nt":
        return None, None
    try:
        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            ctypes.c_ulong,
        ]
        get_process_memory_info.restype = ctypes.c_int
        process = get_current_process()
        ok = get_process_memory_info(
            process, ctypes.byref(counters), counters.cb
        )
        if not ok:
            return None, None
        return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)
    except (AttributeError, OSError, ValueError):
        return None, None


def process_memory() -> tuple[int | None, int | None]:
    try:
        import psutil

        info = psutil.Process().memory_info()
        return int(info.rss), int(getattr(info, "peak_wset", 0) or 0) or None
    except (ImportError, OSError, RuntimeError):
        return _windows_process_memory()


def start_python_tracking() -> None:
    if not tracemalloc.is_tracing():
        # One frame is sufficient for current/peak counters and avoids the
        # substantial allocation overhead of deep traceback collection.
        tracemalloc.start(1)


def python_tracked_memory() -> tuple[int | None, int | None]:
    if not tracemalloc.is_tracing():
        return None, None
    current, peak = tracemalloc.get_traced_memory()
    return int(current), int(peak)


def estimate_object_bytes(value: Any, seen: set[int] | None = None) -> int:
    """Estimate cached NumPy/VTK/Python payload without retaining new references."""
    if value is None:
        return 0
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    nbytes = getattr(value, "nbytes", None)
    if isinstance(nbytes, (int, float)):
        return max(0, int(nbytes))
    if isinstance(value, dict):
        return sum(estimate_object_bytes(item, seen) for item in value.values())
    if isinstance(value, (tuple, list, set)):
        return sum(estimate_object_bytes(item, seen) for item in value)
    points = getattr(value, "points", None)
    faces = getattr(value, "faces", None)
    if points is not None or faces is not None:
        return estimate_object_bytes(points, seen) + estimate_object_bytes(faces, seen)
    return 0


def memory_snapshot(
    *,
    estimated_numpy_bytes: int = 0,
    estimated_voxel_field_bytes: int = 0,
    estimated_session_cache_bytes: int = 0,
) -> dict[str, int | None]:
    working_set, peak_working_set = process_memory()
    python_current, python_peak = python_tracked_memory()
    return {
        "processWorkingSetBytes": working_set,
        "processPeakWorkingSetBytes": peak_working_set,
        "pythonTrackedCurrentBytes": python_current,
        "pythonTrackedPeakBytes": python_peak,
        "estimatedNumpyBytes": int(max(0, estimated_numpy_bytes)),
        "estimatedVoxelFieldBytes": int(max(0, estimated_voxel_field_bytes)),
        "estimatedSessionCacheBytes": int(max(0, estimated_session_cache_bytes)),
    }


@dataclass(frozen=True)
class MemoryLimits:
    soft_bytes: int
    hard_bytes: int

    @classmethod
    def from_environment(cls) -> "MemoryLimits":
        soft = max(256.0, float(os.environ.get("LATTICE_WORKER_MEMORY_SOFT_LIMIT_MIB", "4096")))
        hard = max(soft, float(os.environ.get("LATTICE_WORKER_MEMORY_HARD_LIMIT_MIB", "6144")))
        return cls(int(soft * MIB), int(hard * MIB))


def voxel_memory_preflight(estimated_bytes: int, overhead_factor: float = 1.5) -> dict[str, Any]:
    limits = MemoryLimits.from_environment()
    working_set, _ = process_memory()
    projected = None if working_set is None else int(working_set + estimated_bytes * overhead_factor)
    hard_exceeded = projected is not None and projected > limits.hard_bytes
    soft_exceeded = projected is not None and projected > limits.soft_bytes
    result = {
        "workingSetBeforeBytes": working_set,
        "estimatedNewBytes": int(estimated_bytes),
        "estimatedProjectedBytes": projected,
        "temporaryOverheadFactor": float(overhead_factor),
        "softLimitBytes": limits.soft_bytes,
        "hardLimitBytes": limits.hard_bytes,
        "softLimitExceeded": soft_exceeded,
        "hardLimitExceeded": hard_exceeded,
    }
    if hard_exceeded:
        raise MemoryLimitExceeded(
            "Odhad paměti překračuje hard limit workeru. "
            "Zvětšete voxelSizeMm nebo snižte rozlišení."
        )
    return result
