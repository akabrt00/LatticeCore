"""Relative-density metrics and a robust bracketed scale solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Callable

import numpy as np


def canonical_scale(scale: float) -> str:
    return np.format_float_positional(float(scale), precision=9, unique=False, fractional=True, trim="-")


def density_statistics(domain_volume_mm3: float, component_volumes_mm3: list[float]) -> dict:
    domain = float(domain_volume_mm3)
    components = np.abs(np.asarray(component_volumes_mm3, dtype=float))
    if not np.isfinite(domain) or domain <= 0:
        raise ValueError("DOMAIN_VOLUME_INVALID")
    if not np.all(np.isfinite(components)):
        raise ValueError("LATTICE_VOLUME_INVALID")
    lattice = float(np.sum(components))
    relative = lattice / domain
    if not np.isfinite(relative) or relative < 0 or relative > 1.000001:
        raise ValueError("RELATIVE_DENSITY_INVALID")
    return {
        "domainVolumeMm3": domain,
        "latticeVolumeMm3": lattice,
        "relativeDensity": relative,
        "relativeDensityPercent": relative * 100.0,
        "porosity": 1.0 - relative,
        "porosityPercent": (1.0 - relative) * 100.0,
        "meshComponentCount": int(len(components)),
        "componentVolumesMm3": components.tolist(),
    }


def mass_estimate(volume_statistics: dict, material_density_g_per_cm3: float | None) -> dict:
    density = None if material_density_g_per_cm3 is None else float(material_density_g_per_cm3)
    lattice_cm3 = float(volume_statistics["latticeVolumeMm3"]) / 1000.0
    if density is None or not np.isfinite(density) or density <= 0:
        return {
            "materialDensityGPerCm3": None,
            "latticeVolumeCm3": lattice_cm3,
            "estimatedMassG": None,
            "domainSolidMassG": None,
            "massReductionPercent": None,
        }
    solid_mass = float(volume_statistics["domainVolumeMm3"]) / 1000.0 * density
    estimated = lattice_cm3 * density
    return {
        "materialDensityGPerCm3": density,
        "latticeVolumeCm3": lattice_cm3,
        "estimatedMassG": estimated,
        "domainSolidMassG": solid_mass,
        "massReductionPercent": 100.0 * (1.0 - estimated / solid_mass),
    }


@dataclass
class DensityEvaluation:
    scale: float
    relative_density: float
    lattice_volume_mm3: float
    metadata: dict = field(default_factory=dict)


def solve_target_relative_density(
    evaluator: Callable[[float], DensityEvaluation],
    target_relative_density: float,
    tolerance: float = 0.005,
    minimum_scale: float = 0.25,
    maximum_scale: float = 3.0,
    maximum_iterations: int = 12,
    scale_tolerance: float = 0.001,
) -> dict:
    target = float(target_relative_density)
    if not 0 < target <= 1:
        raise ValueError("TARGET_DENSITY_INVALID")
    if not 0 < minimum_scale < maximum_scale:
        raise ValueError("DENSITY_SCALE_RANGE_INVALID")
    started = perf_counter()
    evaluations: dict[str, DensityEvaluation] = {}
    monotonicity_warning = False

    def evaluate(scale: float) -> DensityEvaluation:
        nonlocal monotonicity_warning
        normalized = float(canonical_scale(scale))
        key = canonical_scale(normalized)
        if key in evaluations:
            return evaluations[key]
        result = evaluator(normalized)
        if not np.isfinite(result.relative_density) or not 0 < result.relative_density <= 1.000001:
            raise ValueError("DENSITY_EVALUATION_INVALID")
        evaluations[key] = result
        ordered = sorted(evaluations.values(), key=lambda item: item.scale)
        for lower, upper in zip(ordered, ordered[1:]):
            if upper.relative_density + tolerance < lower.relative_density:
                monotonicity_warning = True
        return result

    lower = evaluate(minimum_scale)
    upper = evaluate(maximum_scale)
    best = min((lower, upper), key=lambda item: abs(item.relative_density - target))
    if target < min(lower.relative_density, upper.relative_density) - tolerance or target > max(lower.relative_density, upper.relative_density) + tolerance:
        return _result(False, "TARGET_DENSITY_NOT_BRACKETED", best, evaluations, target, monotonicity_warning, started)
    if abs(lower.relative_density - target) <= tolerance:
        return _result(True, "tolerance-reached-lower-bound", lower, evaluations, target, monotonicity_warning, started)
    if abs(upper.relative_density - target) <= tolerance:
        return _result(True, "tolerance-reached-upper-bound", upper, evaluations, target, monotonicity_warning, started)

    low_scale, high_scale = minimum_scale, maximum_scale
    for _ in range(maximum_iterations):
        midpoint = (low_scale + high_scale) * 0.5
        if high_scale - low_scale < scale_tolerance:
            break
        candidate = evaluate(midpoint)
        if abs(candidate.relative_density - target) < abs(best.relative_density - target):
            best = candidate
        if abs(candidate.relative_density - target) <= tolerance:
            return _result(True, "tolerance-reached", candidate, evaluations, target, monotonicity_warning, started)
        if candidate.relative_density < target:
            low_scale = midpoint
        else:
            high_scale = midpoint
    reason = "DENSITY_RESPONSE_NOT_MONOTONIC" if monotonicity_warning and abs(best.relative_density - target) > tolerance else "maximum-iterations"
    return _result(abs(best.relative_density - target) <= tolerance, reason, best, evaluations, target, monotonicity_warning, started)


def _result(converged, reason, best, evaluations, target, warning, started) -> dict:
    ordered = sorted(evaluations.values(), key=lambda item: item.metadata.get("iteration", 0))
    return {
        "converged": bool(converged),
        "terminationReason": reason,
        "selectedGlobalRadiusScale": float(best.scale),
        "solveQualityDensity": float(best.relative_density),
        "finalErrorPercentPoints": abs(float(best.relative_density) - target) * 100.0,
        "monotonicityWarning": bool(warning),
        "iterations": [
            {
                "iteration": index + 1,
                "globalRadiusScale": float(item.scale),
                "relativeDensity": float(item.relative_density),
                "relativeDensityPercent": float(item.relative_density * 100.0),
                "latticeVolumeMm3": float(item.lattice_volume_mm3),
                "errorPercentPoints": abs(float(item.relative_density) - target) * 100.0,
                **item.metadata,
            }
            for index, item in enumerate(ordered)
        ],
        "iterationCount": len(evaluations),
        "solverTimeSeconds": float(perf_counter() - started),
    }
