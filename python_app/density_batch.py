"""Shared evaluation registry and batch-density helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from density_solver import DensityEvaluation, canonical_scale


def parse_batch_targets(value: str | list[float]) -> tuple[list[float], list[float], list[float]]:
    if isinstance(value, str):
        tokens = [item for item in re.split(r"[,;\s]+", value.strip()) if item]
        if not tokens:
            raise ValueError("DENSITY_BATCH_TARGETS_EMPTY")
        original = [float(item) for item in tokens]
    else:
        original = [float(item) for item in value]
    if len(original) < 2:
        raise ValueError("DENSITY_BATCH_REQUIRES_AT_LEAST_TWO_TARGETS")
    if len(original) > 10:
        raise ValueError("DENSITY_BATCH_MAXIMUM_TEN_TARGETS")
    if any(not 0 < item <= 100 for item in original):
        raise ValueError("DENSITY_BATCH_TARGET_OUT_OF_RANGE")
    unique = sorted(set(original))
    if len(unique) < 2:
        raise ValueError("DENSITY_BATCH_REQUIRES_TWO_UNIQUE_TARGETS")
    duplicates = sorted({item for item in original if original.count(item) > 1})
    return original, unique, duplicates


def target_filename_token(target_percent: float) -> str:
    text = f"{float(target_percent):.6f}".rstrip("0").rstrip(".").replace(".", "p")
    whole = text.split("p", 1)[0]
    return f"{whole.zfill(2)}{('p' + text.split('p', 1)[1]) if 'p' in text else ''}pct"


@dataclass
class RegistryRecord:
    evaluation: DensityEvaluation
    quality: str
    voxel_size_mm: float
    result_reference: str
    reused_count: int = 0

    def as_dict(self) -> dict:
        metadata = self.evaluation.metadata
        return {
            "canonicalScale": canonical_scale(self.evaluation.scale),
            "globalRadiusScale": float(self.evaluation.scale),
            "quality": self.quality,
            "voxelSizeMm": float(self.voxel_size_mm),
            "latticeVolumeMm3": float(self.evaluation.lattice_volume_mm3),
            "relativeDensity": float(self.evaluation.relative_density),
            "meshVertexCount": int(metadata.get("meshVertexCount", 0)),
            "meshTriangleCount": int(metadata.get("meshTriangleCount", 0)),
            "generationTimeSeconds": float(metadata.get("generationTimeSeconds", 0)),
            "cacheHit": bool(metadata.get("cacheHit", False)),
            "meshValidation": metadata.get("meshValidation", {}),
            "resultReference": self.result_reference,
            "reusedCount": self.reused_count,
        }


class EvaluationRegistry:
    def __init__(self, evaluator: Callable[[float, str], tuple[DensityEvaluation, str]], voxel_sizes: dict[str, float]):
        self._evaluator = evaluator
        self._voxel_sizes = voxel_sizes
        self._records: dict[str, RegistryRecord] = {}
        self.reused_evaluation_count = 0

    @staticmethod
    def key(scale: float, quality: str) -> str:
        return f"{quality}:{canonical_scale(scale)}"

    def evaluate(self, scale: float, quality: str) -> DensityEvaluation:
        normalized = float(canonical_scale(scale))
        key = self.key(normalized, quality)
        if key in self._records:
            self._records[key].reused_count += 1
            self.reused_evaluation_count += 1
            return self._records[key].evaluation
        evaluation, result_reference = self._evaluator(normalized, quality)
        self._records[key] = RegistryRecord(
            evaluation=evaluation,
            quality=quality,
            voxel_size_mm=self._voxel_sizes[quality],
            result_reference=result_reference,
        )
        return evaluation

    def record(self, scale: float, quality: str) -> RegistryRecord:
        return self._records[self.key(scale, quality)]

    def curve(self, quality: str) -> list[DensityEvaluation]:
        return sorted(
            (record.evaluation for record in self._records.values() if record.quality == quality),
            key=lambda item: item.scale,
        )

    def records(self) -> list[dict]:
        return [
            record.as_dict()
            for record in sorted(self._records.values(), key=lambda item: (item.quality, item.evaluation.scale))
        ]


def warm_start_bracket(
    curve: list[DensityEvaluation],
    target: float,
    minimum_scale: float,
    maximum_scale: float,
) -> tuple[float, float]:
    lower = [item for item in curve if item.relative_density <= target]
    upper = [item for item in curve if item.relative_density >= target]
    low_scale = max(lower, key=lambda item: item.relative_density).scale if lower else minimum_scale
    high_scale = min(upper, key=lambda item: item.relative_density).scale if upper else maximum_scale
    if low_scale >= high_scale:
        return minimum_scale, maximum_scale
    return max(minimum_scale, low_scale), min(maximum_scale, high_scale)


def final_quality_correction(
    registry: EvaluationRegistry,
    selected_scale: float,
    target: float,
    tolerance: float,
    minimum_scale: float,
    maximum_scale: float,
    maximum_iterations: int = 4,
    scale_tolerance: float = 0.0005,
) -> dict:
    evaluations: list[DensityEvaluation] = []
    invalid: list[dict] = []

    def evaluate(scale: float, phase: str) -> DensityEvaluation | None:
        try:
            stored = registry.evaluate(scale, "final-quality")
            item = DensityEvaluation(
                stored.scale,
                stored.relative_density,
                stored.lattice_volume_mm3,
                {**stored.metadata, "phase": phase},
            )
            if all(canonical_scale(existing.scale) != canonical_scale(item.scale) for existing in evaluations):
                evaluations.append(item)
            return item
        except (ValueError, RuntimeError) as error:
            invalid.append({"globalRadiusScale": float(scale), "error": str(error), "phase": phase})
            return None

    initial = evaluate(selected_scale, "final-verification")
    if initial is None:
        return _final_result(None, evaluations, invalid, target, False, "FINAL_MESH_INVALID", selected_scale)
    if abs(initial.relative_density - target) <= tolerance:
        return _final_result(initial, evaluations, invalid, target, True, "FINAL_TOLERANCE_REACHED", selected_scale)

    required = True
    candidates = [
        max(minimum_scale, selected_scale * 0.9),
        min(maximum_scale, selected_scale * 1.1),
    ]
    correction_count = 0
    for scale in candidates:
        if correction_count >= maximum_iterations:
            break
        if canonical_scale(scale) == canonical_scale(selected_scale):
            continue
        if evaluate(scale, "final-correction") is not None:
            correction_count += 1

    termination = "FINAL_TARGET_NOT_BRACKETED"
    while correction_count < maximum_iterations:
        ordered = sorted(evaluations, key=lambda item: item.scale)
        lower = [item for item in ordered if item.relative_density <= target]
        upper = [item for item in ordered if item.relative_density >= target]
        if lower and upper:
            low = max(lower, key=lambda item: item.relative_density)
            high = min(upper, key=lambda item: item.relative_density)
            if high.scale - low.scale <= scale_tolerance:
                termination = "FINAL_SCALE_TOLERANCE_REACHED"
                break
            midpoint = (low.scale + high.scale) * 0.5
            candidate = evaluate(midpoint, "final-correction")
            correction_count += 1
            if candidate is not None and abs(candidate.relative_density - target) <= tolerance:
                termination = "FINAL_TOLERANCE_REACHED"
                break
            termination = "FINAL_MAXIMUM_ITERATIONS"
            continue

        minimum_evaluated = min(item.scale for item in ordered)
        maximum_evaluated = max(item.scale for item in ordered)
        if not lower:
            expanded = max(minimum_scale, minimum_evaluated * 0.8)
        else:
            expanded = min(maximum_scale, maximum_evaluated * 1.2)
        if canonical_scale(expanded) in {canonical_scale(item.scale) for item in ordered}:
            termination = "FINAL_TARGET_NOT_BRACKETED"
            break
        evaluate(expanded, "final-correction")
        correction_count += 1

    valid = [
        item for item in evaluations
        if item.metadata.get("meshValidation", {}).get("isWatertight", True)
        and item.metadata.get("meshValidation", {}).get("isEdgeManifold", True)
    ]
    best = min(valid, key=lambda item: (abs(item.relative_density - target), abs(item.scale - selected_scale), item.scale)) if valid else None
    converged = best is not None and abs(best.relative_density - target) <= tolerance
    ordered_valid = sorted(valid, key=lambda item: item.scale)
    non_monotonic = any(
        upper.relative_density + tolerance < lower.relative_density
        for lower, upper in zip(ordered_valid, ordered_valid[1:])
    )
    if converged:
        termination = "FINAL_TOLERANCE_REACHED"
    elif not valid:
        termination = "FINAL_MESH_INVALID"
    elif non_monotonic:
        termination = "FINAL_NON_MONOTONIC_RESPONSE"
    return _final_result(best, evaluations, invalid, target, converged, termination, selected_scale, required)


def _final_result(best, evaluations, invalid, target, converged, reason, initial_scale, correction_required=False):
    initial = evaluations[0] if evaluations else None
    correction_items = [item for item in evaluations if item.metadata.get("phase") == "final-correction"]
    return {
        "enabled": True,
        "initialVerifiedScale": float(initial_scale),
        "initialVerifiedDensity": None if initial is None else float(initial.relative_density),
        "initialErrorPercentPoints": None if initial is None else abs(initial.relative_density - target) * 100.0,
        "initialVerification": None if initial is None else {
            "phase": "final-verification",
            "iteration": 1,
            "globalRadiusScale": float(initial.scale),
            "relativeDensity": float(initial.relative_density),
            "relativeDensityPercent": float(initial.relative_density * 100.0),
            "latticeVolumeMm3": float(initial.lattice_volume_mm3),
            "errorPercentPoints": abs(initial.relative_density - target) * 100.0,
            **initial.metadata,
        },
        "correctionWasRequired": bool(correction_required),
        "correctionIterations": [
            {
                "phase": "final-correction",
                "globalRadiusScale": float(item.scale),
                "relativeDensity": float(item.relative_density),
                "relativeDensityPercent": float(item.relative_density * 100.0),
                "latticeVolumeMm3": float(item.lattice_volume_mm3),
                "errorPercentPoints": abs(item.relative_density - target) * 100.0,
                **item.metadata,
            }
            for item in correction_items
        ],
        "invalidEvaluations": invalid,
        "selectedFinalScale": None if best is None else float(best.scale),
        "selectedFinalDensity": None if best is None else float(best.relative_density),
        "finalErrorPercentPoints": None if best is None else abs(best.relative_density - target) * 100.0,
        "converged": bool(converged),
        "terminationReason": reason,
        "selectedMeshIsFinalQuality": best is not None,
    }
