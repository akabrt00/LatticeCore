"""Compact, optional debug geometry payloads for LatticeCore."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

POINT_LAYERS = {"seed-points", "interior-nodes", "surface-nodes"}
SEGMENT_LAYERS = {
    "raw-volume-voronoi-edges",
    "clipped-interior-centerlines",
    "raw-surface-voronoi-segments",
    "smoothed-surface-centerlines",
    "placed-surface-centerlines",
    "surface-to-interior-connectors",
    "combined-centerline-graph",
}
TRIANGLE_LAYERS = {"final-implicit-mesh"}
ALL_LAYERS = POINT_LAYERS | SEGMENT_LAYERS | TRIANGLE_LAYERS


def _as_elements(values: object, primitive: str) -> np.ndarray:
    width = 3 if primitive == "points" else 9 if primitive == "triangles" else 6
    array = np.asarray(values, dtype=np.float32)
    if array.size == 0:
        return np.empty((0, width), dtype=np.float32)
    array = array.reshape((-1, width))
    if not np.all(np.isfinite(array)):
        raise ValueError("Debug geometry contains NaN or infinity.")
    return np.ascontiguousarray(array)


def deterministic_stride(array: np.ndarray, maximum: int) -> tuple[np.ndarray, bool]:
    if maximum <= 0 or len(array) <= maximum:
        return array, False
    indices = np.floor(np.arange(maximum, dtype=np.float64) * len(array) / maximum).astype(np.int64)
    return np.ascontiguousarray(array[indices]), True


def write_debug_payload(
    layers: dict[str, object],
    manifest_path: str | Path,
    buffer_path: str | Path,
    maximum_points: int = 100_000,
    maximum_segments: int = 200_000,
) -> dict:
    chunks: list[bytes] = []
    manifest_layers: dict[str, dict] = {}
    byte_offset = 0
    for name, values in layers.items():
        if name not in ALL_LAYERS:
            continue
        primitive = "points" if name in POINT_LAYERS else "triangles" if name in TRIANGLE_LAYERS else "segments"
        elements = _as_elements(values, primitive)
        original_count = len(elements)
        maximum = maximum_points if primitive == "points" else maximum_segments
        returned, reduced = deterministic_stride(elements, maximum)
        payload = returned.reshape(-1).tobytes(order="C")
        manifest_layers[name] = {
            "primitive": primitive,
            "byteOffset": byte_offset,
            "elementCount": int(returned.size),
            "originalElementCount": int(original_count),
            "returnedElementCount": int(len(returned)),
            "isDownsampled": bool(reduced),
            "downsamplingMethod": "deterministic-stride" if reduced else None,
            "byteLength": len(payload),
        }
        chunks.append(payload)
        byte_offset += len(payload)
    manifest = {
        "formatVersion": 1,
        "coordinateType": "float32",
        "byteOrder": "little",
        "layers": manifest_layers,
        "totalByteLength": byte_offset,
    }
    manifest_file, buffer_file = Path(manifest_path), Path(buffer_path)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    buffer_file.parent.mkdir(parents=True, exist_ok=True)
    buffer_file.write_bytes(b"".join(chunks))
    manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest
