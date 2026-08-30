"""Versioned local NPZ/JSON cache with validation and atomic writes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
GENERATOR_VERSION = "latticecore-2026.07"
ALGORITHM_VERSIONS = {
    "input-mesh": "mesh-cleanup-v1",
    "domain": "triangle-domain-v1",
    "seeds": "seed-sampling-v1",
    "volume-voronoi": "scipy-voronoi-v1",
    "clipped-interior": "domain-clipping-v1",
    "surface-working-mesh": "surface-subdivision-v1",
    "surface-labels": "nearest-seed-v1",
    "surface-graph": "restricted-voronoi-v1",
    "placed-surface": "surface-placement-v1",
    "connectors": "surface-connectors-v1",
    "primitives": "implicit-primitives-v1",
    "final-mesh": "flying-edges-v1",
}


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_content_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_cache_keys(source_hash: str, parameters: dict, conformal: bool = True) -> dict[str, str]:
    def key(level: str, dependencies: dict) -> str:
        return canonical_hash({
            "schemaVersion": SCHEMA_VERSION,
            "algorithmVersion": ALGORITHM_VERSIONS[level],
            "dependencies": dependencies,
        })

    keys: dict[str, str] = {}
    keys["input-mesh"] = key("input-mesh", {
        "sourceHash": source_hash,
        "format": parameters.get("format"),
        "importScale": parameters.get("importScale", 1.0),
        "componentMode": parameters.get("componentMode", "require-single"),
    })
    keys["domain"] = key("domain", {"inputMesh": keys["input-mesh"]})
    keys["seeds"] = key("seeds", {
        "domain": keys["domain"],
        "seedCount": parameters.get("seedCount"),
        "targetCellSizeMm": parameters.get("targetCellSizeMm", 0),
        "randomSeed": parameters.get("randomSeed"),
        "boundaryOffsetMm": parameters.get("boundaryOffsetMm", 0),
    })
    keys["volume-voronoi"] = key("volume-voronoi", {
        "seeds": keys["seeds"],
        "minimumPreliminaryStrutLength": parameters.get("minimumPreliminaryStrutLength", 0),
    })
    keys["clipped-interior"] = key("clipped-interior", {
        "voronoi": keys["volume-voronoi"],
        "domain": keys["domain"],
        "minimumStrutLengthMm": parameters.get("minimumStrutLengthMm", 0),
    })
    if conformal:
        keys["surface-working-mesh"] = key("surface-working-mesh", {
            "inputMesh": keys["input-mesh"],
            "surfaceSamplingStepMm": parameters.get("surfaceSamplingStepMm"),
        })
        keys["surface-labels"] = key("surface-labels", {
            "workingMesh": keys["surface-working-mesh"],
            "seeds": keys["seeds"],
        })
        keys["surface-graph"] = key("surface-graph", {
            "labels": keys["surface-labels"],
            "smoothingIterations": parameters.get("surfaceSmoothingIterations", 2),
            "smoothingStrength": parameters.get("surfaceSmoothingStrength", 0.35),
            "topologyWeldReferenceMm": parameters.get("surfaceTopologyWeldReferenceMm", 0),
        })
        keys["placed-surface"] = key("placed-surface", {
            "surfaceGraph": keys["surface-graph"],
            "placementMode": parameters.get("surfacePlacementMode"),
            "surfaceInsetMm": parameters.get("surfaceInsetMm"),
            "surfaceStrutDiameterMm": parameters.get("surfaceStrutDiameterMm")
            if parameters.get("surfaceInsetMode") == "automatic" else None,
        })
        keys["connectors"] = key("connectors", {
            "placedSurface": keys["placed-surface"],
            "clippedInterior": keys["clipped-interior"],
            "spacing": parameters.get("connectorSpacingMm"),
            "maximumLength": parameters.get("connectorMaximumLengthMm"),
        })
    keys["primitives"] = key("primitives", {
        "clippedInterior": keys["clipped-interior"],
        "placedSurface": keys.get("placed-surface"),
        "connectors": keys.get("connectors"),
        "strutDiameterMm": parameters.get("strutDiameterMm"),
        "surfaceStrutDiameterMm": parameters.get("surfaceStrutDiameterMm"),
        "connectorDiameterMm": parameters.get("connectorDiameterMm"),
        "nodeRadiusScale": parameters.get("nodeRadiusScale", 1),
    })
    keys["final-mesh"] = key("final-mesh", {
        "primitives": keys["primitives"],
        "domain": keys["domain"],
        "voxelSizeMm": parameters.get("voxelSizeMm"),
        "finalComponentMode": parameters.get("finalComponentMode"),
    })
    return keys


class CacheStore:
    def __init__(self, root: str | Path, enabled: bool = True, maximum_size_gib: float = 5, maximum_age_days: float = 30):
        self.root = Path(root) / f"schema-v{SCHEMA_VERSION}"
        self.enabled = enabled
        self.maximum_size = int(maximum_size_gib * 1024**3)
        self.maximum_age = maximum_age_days * 86400

    def _entry(self, level: str, key: str) -> Path:
        return self.root / level / key

    @contextmanager
    def _lock(self, entry: Path, timeout: float = 30, stale_after: float = 900):
        lock = entry.with_suffix(".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + timeout
        while True:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(descriptor)
                break
            except FileExistsError:
                if time.time() - lock.stat().st_mtime > stale_after:
                    lock.unlink(missing_ok=True)
                    continue
                if time.time() >= deadline:
                    raise TimeoutError(f"Cache lock timed out for {entry.name[:12]}.")
                time.sleep(0.05)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    def put(self, level: str, key: str, arrays: dict[str, np.ndarray], dependencies: dict | None = None) -> bool:
        if not self.enabled:
            return False
        entry = self._entry(level, key)
        with self._lock(entry):
            if entry.exists():
                return True
            temporary = entry.with_name(f".{entry.name}.{uuid.uuid4().hex}.tmp")
            temporary.mkdir(parents=True, exist_ok=False)
            normalized = {name: np.ascontiguousarray(value) for name, value in arrays.items()}
            for value in normalized.values():
                if not np.all(np.isfinite(value)):
                    shutil.rmtree(temporary, ignore_errors=True)
                    raise ValueError("Cache arrays must contain finite values.")
            np.savez_compressed(temporary / "arrays.npz", **normalized)
            checksum = hashlib.sha256((temporary / "arrays.npz").read_bytes()).hexdigest()
            now = datetime.now(timezone.utc).isoformat()
            manifest = {
                "schemaVersion": SCHEMA_VERSION,
                "generatorVersion": GENERATOR_VERSION,
                "algorithmVersion": ALGORITHM_VERSIONS[level],
                "cacheLevel": level,
                "cacheKey": key,
                "createdAt": now,
                "lastAccessedAt": now,
                "dependencies": dependencies or {},
                "arrays": {name: {"dtype": str(value.dtype), "shape": list(value.shape)} for name, value in normalized.items()},
                "dataSha256": checksum,
            }
            (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            manifest["sizeBytes"] = sum(item.stat().st_size for item in temporary.iterdir())
            (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            entry.parent.mkdir(parents=True, exist_ok=True)
            for attempt in range(20):
                try:
                    os.replace(temporary, entry)
                    break
                except PermissionError:
                    if entry.exists():
                        shutil.rmtree(temporary, ignore_errors=True)
                        return True
                    if attempt == 19:
                        shutil.rmtree(temporary, ignore_errors=True)
                        raise
                    time.sleep(0.1)
        return True

    def get(self, level: str, key: str, expected_shapes: dict[str, tuple[int | None, ...]] | None = None) -> dict[str, np.ndarray] | None:
        if not self.enabled:
            return None
        entry = self._entry(level, key)
        try:
            manifest = json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
            data_path = entry / "arrays.npz"
            if manifest["schemaVersion"] != SCHEMA_VERSION or manifest["algorithmVersion"] != ALGORITHM_VERSIONS[level]:
                return None
            if hashlib.sha256(data_path.read_bytes()).hexdigest() != manifest["dataSha256"]:
                raise ValueError("checksum")
            with np.load(data_path, allow_pickle=False) as loaded:
                arrays = {name: loaded[name].copy() for name in loaded.files}
            for name, value in arrays.items():
                specification = manifest["arrays"][name]
                if list(value.shape) != specification["shape"] or str(value.dtype) != specification["dtype"]:
                    raise ValueError("shape or dtype")
                if not np.all(np.isfinite(value)):
                    raise ValueError("non-finite")
                expected = (expected_shapes or {}).get(name)
                if expected and (len(expected) != value.ndim or any(want is not None and want != got for want, got in zip(expected, value.shape))):
                    raise ValueError("unexpected shape")
            os.utime(entry, None)
            return arrays
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            if entry.exists():
                shutil.rmtree(entry, ignore_errors=True)
            return None

    def clear(self, scope: str) -> int:
        allowed = {
            "final-mesh": ["final-mesh"],
            "surface": ["surface-working-mesh", "surface-labels", "surface-graph", "placed-surface", "connectors"],
            "all": list(ALGORITHM_VERSIONS),
        }
        if scope not in allowed:
            raise ValueError("Unsupported cache clear scope.")
        removed = 0
        for level in allowed[scope]:
            directory = self.root / level
            if directory.exists():
                removed += sum(1 for child in directory.iterdir() if child.is_dir())
                shutil.rmtree(directory, ignore_errors=True)
        return removed

    def status(self) -> dict:
        entries = [path for path in self.root.glob("*/*") if path.is_dir()] if self.root.exists() else []
        size = sum(file.stat().st_size for entry in entries for file in entry.rglob("*") if file.is_file())
        oldest = min((entry.stat().st_mtime for entry in entries), default=None)
        return {
            "enabled": self.enabled,
            "sizeBytes": size,
            "maximumSizeBytes": self.maximum_size,
            "itemCount": len(entries),
            "oldestItem": datetime.fromtimestamp(oldest, timezone.utc).isoformat() if oldest else None,
        }

    def cleanup(self) -> int:
        if not self.root.exists():
            return 0
        entries = [path for path in self.root.glob("*/*") if path.is_dir()]
        now = time.time()
        removed = 0
        for entry in list(entries):
            if now - entry.stat().st_mtime > self.maximum_age:
                shutil.rmtree(entry, ignore_errors=True)
                entries.remove(entry)
                removed += 1
        total = sum(file.stat().st_size for entry in entries for file in entry.rglob("*") if file.is_file())
        for entry in sorted(entries, key=lambda item: item.stat().st_mtime):
            if total <= self.maximum_size:
                break
            size = sum(file.stat().st_size for file in entry.rglob("*") if file.is_file())
            shutil.rmtree(entry, ignore_errors=True)
            total -= size
            removed += 1
        return removed
