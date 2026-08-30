"""CLI orchestration for single and batch target-relative-density generation."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from time import perf_counter

from density_batch import (
    EvaluationRegistry,
    final_quality_correction,
    parse_batch_targets,
    target_filename_token,
    warm_start_bracket,
)
from density_solver import DensityEvaluation, canonical_scale, mass_estimate, solve_target_relative_density
from voronoi_sphere_lines_mvp import main as run_generator
from worker_runtime import WorkerRuntime


ITERATION_FIELDS = [
    "phase", "iteration", "globalRadiusScale", "interiorStrutDiameterMm", "surfaceStrutDiameterMm",
    "connectorDiameterMm", "latticeVolumeMm3", "relativeDensity", "relativeDensityPercent",
    "errorPercentPoints", "meshVertexCount", "meshTriangleCount", "generationTimeSeconds", "cacheHit",
]

SUMMARY_FIELDS = [
    "targetDensityPercent", "converged", "finalDensityPercent", "errorPercentPoints", "porosityPercent",
    "globalRadiusScale", "interiorStrutDiameterMm", "surfaceStrutDiameterMm", "connectorDiameterMm",
    "latticeVolumeMm3", "estimatedMassG", "meshVertexCount", "meshTriangleCount", "totalIterations",
    "finalCorrectionIterations", "generationTimeSeconds", "cacheHits", "cacheMisses", "terminationReason",
    "stlFileName",
]


def option_value(arguments: list[str], name: str, default: str = "") -> str:
    try:
        return arguments[arguments.index(name) + 1]
    except (ValueError, IndexError):
        return default


def replace_option(arguments: list[str], name: str, value: object) -> list[str]:
    result = list(arguments)
    try:
        index = result.index(name)
        result[index + 1] = str(value)
    except ValueError:
        result.extend([name, str(value)])
    return result


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="LatticeCore target relative density runner")
    parser.add_argument("--target-relative-density", type=float)
    parser.add_argument("--density-batch-targets-percent", default="")
    parser.add_argument("--batch-failure-policy", choices=["continue", "stop-on-error"], default="continue")
    parser.add_argument("--batch-output-directory", default="")
    parser.add_argument("--batch-summary-json", default="")
    parser.add_argument("--batch-summary-csv", default="")
    parser.add_argument("--batch-zip", default="")
    parser.add_argument("--density-tolerance-percent-points", type=float, default=0.5)
    parser.add_argument("--density-minimum-scale", type=float, default=0.25)
    parser.add_argument("--density-maximum-scale", type=float, default=3.0)
    parser.add_argument("--density-maximum-iterations", type=int, default=12)
    parser.add_argument("--density-scale-tolerance", type=float, default=0.001)
    parser.add_argument("--maximum-final-correction-iterations", type=int, default=4)
    parser.add_argument("--final-scale-tolerance", type=float, default=0.0005)
    parser.add_argument("--density-scaling-policy", choices=["all-active-radii", "interior-only"], default="all-active-radii")
    parser.add_argument("--density-solver-quality", choices=["preview", "standard", "final-quality"], default="standard")
    parser.add_argument("--verify-at-final-quality", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--minimum-printable-strut-diameter-mm", type=float, default=0.4)
    parser.add_argument("--maximum-allowed-strut-diameter-mm", type=float, default=20.0)
    parser.add_argument("--density-csv", default="")
    return parser.parse_known_args(argv)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def safe_source_stem(name: str) -> str:
    source = Path(name or "lattice").stem
    safe = "".join(character if character.isalnum() or character in "-_" else "_" for character in source)
    return safe.strip("._") or "lattice"


def main(
    argv: list[str] | None = None,
    runtime_context: WorkerRuntime | None = None,
) -> dict:
    options, generator_args = parse_args(argv)
    cancellation_token = runtime_context.cancellation_token if runtime_context is not None else None

    def checkpoint() -> None:
        if cancellation_token is not None:
            cancellation_token.check()

    def report(phase: str, message: str, fraction: float | None = None, **metrics) -> None:
        if runtime_context is not None:
            runtime_context.report(phase, message, fraction, **metrics)

    is_batch = bool(options.density_batch_targets_percent)
    if not is_batch and options.target_relative_density is None:
        raise ValueError("TARGET_DENSITY_REQUIRED")
    output_path = Path(option_value(generator_args, "--export-stl"))
    metadata_path = Path(option_value(generator_args, "--metadata-json"))
    if not str(output_path) or not str(metadata_path):
        raise ValueError("Density runner requires --export-stl and --metadata-json.")

    base_radius = float(option_value(generator_args, "--tube-radius", "0.5"))
    base_surface_diameter = float(option_value(generator_args, "--surface-strut-diameter-mm", str(base_radius * 2)))
    base_connector_diameter = float(option_value(generator_args, "--surface-connector-diameter-mm", str(base_radius * 2)))
    base_interior_diameter = base_radius * 2.0
    generator_args = replace_option(generator_args, "--surface-topology-weld-reference-mm", base_surface_diameter)
    maximum_base_diameter = max(
        base_interior_diameter,
        base_surface_diameter if options.density_scaling_policy == "all-active-radii" else 0,
        base_connector_diameter if options.density_scaling_policy == "all-active-radii" else 0,
    )
    maximum_scale = min(options.density_maximum_scale, options.maximum_allowed_strut_diameter_mm / maximum_base_diameter)
    if maximum_scale <= options.density_minimum_scale:
        raise ValueError("FINAL_DIAMETER_LIMIT_REACHED")
    original_quality = option_value(generator_args, "--quality-preset", "standard")
    original_voxel = option_value(generator_args, "--voxel-size-mm", "0")

    def fixed_voxel_size(quality: str) -> float:
        if quality == "preview":
            return base_interior_diameter / 4.0
        if quality == "standard":
            return base_interior_diameter / 6.0
        if original_quality == "custom":
            return float(original_voxel)
        divisor = {"preview": 4.0, "standard": 6.0, "high": 10.0}.get(original_quality, 6.0)
        return base_interior_diameter / divisor

    voxel_sizes = {quality: fixed_voxel_size(quality) for quality in ("preview", "standard", "final-quality")}
    material_density = float(option_value(generator_args, "--material-density-g-per-cm3", "0"))

    with tempfile.TemporaryDirectory(prefix="latticecore-density-") as directory:
        temporary = Path(directory)
        artifacts: dict[str, tuple[Path, Path, dict]] = {}
        generation_counter = 0

        def generate(scale: float, quality: str) -> tuple[DensityEvaluation, str]:
            nonlocal generation_counter
            checkpoint()
            generation_counter += 1
            reference = EvaluationRegistry.key(scale, quality)
            candidate_stl = temporary / f"candidate-{generation_counter}.stl"
            candidate_json = temporary / f"candidate-{generation_counter}.json"
            arguments = replace_option(generator_args, "--export-stl", candidate_stl)
            arguments = replace_option(arguments, "--metadata-json", candidate_json)
            arguments = replace_option(arguments, "--tube-radius", base_radius * scale)
            if options.density_scaling_policy == "all-active-radii":
                arguments = replace_option(arguments, "--surface-strut-diameter-mm", base_surface_diameter * scale)
                arguments = replace_option(arguments, "--surface-connector-diameter-mm", base_connector_diameter * scale)
            arguments = replace_option(arguments, "--quality-preset", "custom")
            arguments = replace_option(arguments, "--voxel-size-mm", voxel_sizes[quality])
            report(
                "iteration-start",
                f"Vyhodnocuji scale {scale:.6g}.",
                None,
                iteration=generation_counter,
                scale=scale,
                quality=quality,
            )
            started = perf_counter()
            run_generator(list(map(str, arguments)), runtime_context=runtime_context)
            elapsed = perf_counter() - started
            metadata = json.loads(candidate_json.read_text(encoding="utf-8"))
            validation = metadata["meshValidationAfterCleanup"]
            if not validation["isWatertight"] or not validation["isEdgeManifold"]:
                raise ValueError("DENSITY_CANDIDATE_MESH_INVALID")
            volume = metadata["volumeStatistics"]
            cache = metadata.get("cache", {})
            evaluation = DensityEvaluation(scale, volume["relativeDensity"], volume["latticeVolumeMm3"], {
                "generationTimeSeconds": elapsed,
                "cacheHit": cache.get("missCount", 0) == 0,
                "cacheHits": cache.get("hitCount", 0),
                "cacheMisses": cache.get("missCount", 0),
                "meshVertexCount": metadata["statistics"]["meshVertexCount"],
                "meshTriangleCount": metadata["statistics"]["meshTriangleCount"],
                "meshValidation": validation,
                "interiorStrutDiameterMm": base_interior_diameter * scale,
                "surfaceStrutDiameterMm": base_surface_diameter * (scale if options.density_scaling_policy == "all-active-radii" else 1),
                "connectorDiameterMm": base_connector_diameter * (scale if options.density_scaling_policy == "all-active-radii" else 1),
            })
            artifacts[reference] = (candidate_stl, candidate_json, metadata)
            report(
                "iteration-result",
                f"Scale {scale:.6g}: hustota {volume['relativeDensityPercent']:.3f} %.",
                None,
                iteration=generation_counter,
                scale=scale,
                quality=quality,
                achievedDensityPercent=volume["relativeDensityPercent"],
                cacheHit=evaluation.metadata["cacheHit"],
            )
            return evaluation, reference

        registry = EvaluationRegistry(generate, voxel_sizes)
        job_started = perf_counter()
        current_target_count = 1

        def solve_one(target: float, target_percent: float, batch_index: int | None = None) -> dict:
            checkpoint()
            report(
                "target-start",
                f"Řeším cílovou hustotu {target_percent:g} %.",
                None,
                targetIndex=(batch_index + 1) if batch_index is not None else 1,
                targetCount=current_target_count,
                targetDensityPercent=target_percent,
            )
            report("preparing-density-solver", "Připravuji řešič cílové hustoty.")
            primary_curve = registry.curve(options.density_solver_quality)
            solve_minimum, solve_maximum = warm_start_bracket(
                primary_curve, target, options.density_minimum_scale, maximum_scale,
            )
            primary = solve_target_relative_density(
                lambda scale: registry.evaluate(scale, options.density_solver_quality),
                target,
                options.density_tolerance_percent_points / 100.0,
                solve_minimum,
                solve_maximum,
                max(1, options.density_maximum_iterations),
                max(options.density_scale_tolerance, 1e-9),
            )
            if primary["terminationReason"] == "TARGET_DENSITY_NOT_BRACKETED" and (
                solve_minimum != options.density_minimum_scale or solve_maximum != maximum_scale
            ):
                primary = solve_target_relative_density(
                    lambda scale: registry.evaluate(scale, options.density_solver_quality),
                    target,
                    options.density_tolerance_percent_points / 100.0,
                    options.density_minimum_scale,
                    maximum_scale,
                    max(1, options.density_maximum_iterations),
                    max(options.density_scale_tolerance, 1e-9),
                )
            selected_scale = primary["selectedGlobalRadiusScale"]
            primary_iterations = [{**item, "phase": "primary"} for item in primary["iterations"]]

            if options.verify_at_final_quality:
                report("final-verification", "Ověřuji výsledek ve finální kvalitě.")
                final = final_quality_correction(
                    registry,
                    selected_scale,
                    target,
                    options.density_tolerance_percent_points / 100.0,
                    options.density_minimum_scale,
                    maximum_scale,
                    max(0, options.maximum_final_correction_iterations),
                    max(options.final_scale_tolerance, 1e-12),
                )
                final["maximumCorrectionIterations"] = options.maximum_final_correction_iterations
                if (
                    final["terminationReason"] == "FINAL_TARGET_NOT_BRACKETED"
                    and maximum_scale < options.density_maximum_scale
                    and final.get("selectedFinalDensity") is not None
                    and final["selectedFinalDensity"] < target
                ):
                    final["terminationReason"] = "FINAL_DIAMETER_LIMIT_REACHED"
                selected_scale = final["selectedFinalScale"]
                if selected_scale is None:
                    raise ValueError("FINAL_MESH_INVALID")
                selected_quality = "final-quality"
            else:
                selected_quality = options.density_solver_quality
                final = {
                    "enabled": False,
                    "initialVerifiedScale": None,
                    "initialVerifiedDensity": None,
                    "initialErrorPercentPoints": None,
                    "initialVerification": None,
                    "correctionWasRequired": False,
                    "maximumCorrectionIterations": 0,
                    "correctionIterations": [],
                    "selectedFinalScale": selected_scale,
                    "selectedFinalDensity": primary["solveQualityDensity"],
                    "finalErrorPercentPoints": primary["finalErrorPercentPoints"],
                    "converged": primary["converged"],
                    "terminationReason": primary["terminationReason"],
                    "selectedMeshIsFinalQuality": options.density_solver_quality == "final-quality",
                }

            reference = EvaluationRegistry.key(selected_scale, selected_quality)
            selected_stl, _, source_metadata = artifacts[reference]
            selected_metadata = json.loads(json.dumps(source_metadata))
            selected_evaluation = registry.record(selected_scale, selected_quality).evaluation
            verification_iterations = [final["initialVerification"]] if final.get("initialVerification") else []
            all_iterations = primary_iterations + verification_iterations + final["correctionIterations"]
            density_control = {
                "mode": "target-relative-density",
                "targetRelativeDensity": target,
                "targetRelativeDensityPercent": target_percent,
                "tolerancePercentPoints": options.density_tolerance_percent_points,
                "scalingPolicy": options.density_scaling_policy,
                "minimumScale": options.density_minimum_scale,
                "maximumScale": maximum_scale,
                "maximumIterations": options.density_maximum_iterations,
                "maximumFinalCorrectionIterations": options.maximum_final_correction_iterations,
                "finalScaleTolerance": options.final_scale_tolerance,
                "solverQuality": options.density_solver_quality,
                "verifyAtFinalQuality": options.verify_at_final_quality,
                "primarySolve": {
                    "quality": options.density_solver_quality,
                    "selectedScale": primary["selectedGlobalRadiusScale"],
                    "density": primary["solveQualityDensity"],
                    "errorPercentPoints": primary["finalErrorPercentPoints"],
                    "iterations": primary_iterations,
                },
                "finalVerification": final,
                "converged": final["converged"],
                "terminationReason": final["terminationReason"],
                "selectedGlobalRadiusScale": selected_scale,
                "solveQualityDensity": primary["solveQualityDensity"],
                "finalVerifiedDensity": final["selectedFinalDensity"],
                "finalErrorPercentPoints": final["finalErrorPercentPoints"],
                "iterations": all_iterations,
                "iterationCount": len(all_iterations),
                "solverTimeSeconds": primary["solverTimeSeconds"],
            }
            selected_metadata["densityControl"] = density_control
            selected_metadata["massEstimate"] = mass_estimate(
                selected_metadata["volumeStatistics"], material_density if material_density > 0 else None,
            )
            final_diameter = base_interior_diameter * selected_scale
            selected_metadata["printabilityWarning"] = (
                f"Interior strut diameter {final_diameter:.3f} mm is below the configured printable minimum."
                if final_diameter < options.minimum_printable_strut_diameter_mm else None
            )
            return {
                "target": target,
                "targetPercent": target_percent,
                "batchIndex": batch_index,
                "stl": selected_stl,
                "metadata": selected_metadata,
                "evaluation": selected_evaluation,
                "densityControl": density_control,
                "iterations": all_iterations,
            }

        if not is_batch:
            solved = solve_one(options.target_relative_density, options.target_relative_density * 100.0)
            checkpoint()
            report("exporting-files", "Exportuji výsledek cílové hustoty.", 0.96)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(solved["stl"], output_path)
            metadata_path.write_text(json.dumps(solved["metadata"], indent=2, sort_keys=True), encoding="utf-8")
            if options.density_csv:
                write_csv(Path(options.density_csv), ITERATION_FIELDS, solved["iterations"])
            return {
                "mode": "single",
                "outputPath": str(output_path),
                "metadataPath": str(metadata_path),
                "metadata": solved["metadata"],
            }

        original_targets, targets, duplicates = parse_batch_targets(options.density_batch_targets_percent)
        current_target_count = len(targets)
        source_stem = safe_source_stem(option_value(generator_args, "--source-original-name", output_path.stem))
        batch_directory = Path(options.batch_output_directory or output_path.parent / f"{source_stem}_density_batch")
        batch_directory.mkdir(parents=True, exist_ok=True)
        produced_files: list[Path] = []
        results: list[dict] = []
        summary_rows: list[dict] = []
        for index, target_percent in enumerate(targets):
            checkpoint()
            target_started = perf_counter()
            try:
                solved = solve_one(target_percent / 100.0, target_percent, index)
                token = target_filename_token(target_percent)
                stl_name = f"{source_stem}_density_{token}.stl"
                metadata_name = f"{source_stem}_density_{token}_metadata.json"
                iterations_name = f"{source_stem}_density_{token}_iterations.csv"
                stl_target = batch_directory / stl_name
                metadata_target = batch_directory / metadata_name
                iterations_target = batch_directory / iterations_name
                shutil.copyfile(solved["stl"], stl_target)
                metadata_target.write_text(json.dumps(solved["metadata"], indent=2, sort_keys=True), encoding="utf-8")
                write_csv(iterations_target, ITERATION_FIELDS, solved["iterations"])
                produced_files.extend([stl_target, metadata_target, iterations_target])
                control = solved["densityControl"]
                evaluation = solved["evaluation"]
                volume = solved["metadata"]["volumeStatistics"]
                estimate = solved["metadata"]["massEstimate"]
                row = {
                    "targetDensityPercent": target_percent,
                    "converged": control["converged"],
                    "finalDensityPercent": control["finalVerifiedDensity"] * 100.0,
                    "errorPercentPoints": control["finalErrorPercentPoints"],
                    "porosityPercent": volume["porosityPercent"],
                    "globalRadiusScale": control["selectedGlobalRadiusScale"],
                    "interiorStrutDiameterMm": evaluation.metadata["interiorStrutDiameterMm"],
                    "surfaceStrutDiameterMm": evaluation.metadata["surfaceStrutDiameterMm"],
                    "connectorDiameterMm": evaluation.metadata["connectorDiameterMm"],
                    "latticeVolumeMm3": volume["latticeVolumeMm3"],
                    "estimatedMassG": estimate["estimatedMassG"],
                    "meshVertexCount": evaluation.metadata["meshVertexCount"],
                    "meshTriangleCount": evaluation.metadata["meshTriangleCount"],
                    "totalIterations": control["iterationCount"],
                    "finalCorrectionIterations": len(control["finalVerification"]["correctionIterations"]),
                    "generationTimeSeconds": perf_counter() - target_started,
                    "cacheHits": sum(item.get("cacheHits", 0) for item in control["iterations"]),
                    "cacheMisses": sum(item.get("cacheMisses", 0) for item in control["iterations"]),
                    "terminationReason": control["terminationReason"],
                    "stlFileName": stl_name,
                    "metadataFileName": metadata_name,
                    "iterationsFileName": iterations_name,
                    "meshValidation": evaluation.metadata["meshValidation"],
                }
                results.append(row)
                summary_rows.append(row)
            except (ValueError, RuntimeError) as error:
                failed = {
                    "targetDensityPercent": target_percent,
                    "converged": False,
                    "terminationReason": str(error),
                    "generationTimeSeconds": perf_counter() - target_started,
                }
                results.append(failed)
                summary_rows.append(failed)
                if options.batch_failure_policy == "stop-on-error":
                    break

        records = registry.records()
        statistics = {
            "targetCount": len(targets),
            "completedTargetCount": sum(bool(item.get("converged")) for item in results),
            "failedTargetCount": sum(not bool(item.get("converged")) for item in results),
            "uniqueScaleEvaluationCount": len(records),
            "reusedEvaluationCount": registry.reused_evaluation_count,
            "primaryQualityEvaluationCount": sum(item["quality"] == options.density_solver_quality for item in records),
            "finalQualityEvaluationCount": sum(item["quality"] == "final-quality" for item in records),
            "totalCacheHits": sum(record["reusedCount"] + int(record["cacheHit"]) for record in records),
            "totalCacheMisses": sum(not record["cacheHit"] for record in records),
            "totalGenerationTimeSeconds": sum(record["generationTimeSeconds"] for record in records),
            "estimatedTimeSavedSeconds": sum(record["generationTimeSeconds"] * record["reusedCount"] for record in records),
        }
        summary = {
            "mode": "density-batch",
            "originalTargetsPercent": original_targets,
            "sortedUniqueTargetsPercent": targets,
            "duplicateTargetsRemoved": duplicates,
            "failurePolicy": options.batch_failure_policy,
            "results": results,
            "batchEvaluationStatistics": statistics,
            "evaluationRegistry": records,
            "totalJobTimeSeconds": perf_counter() - job_started,
            "executionMode": "persistent-worker" if runtime_context is not None else "standalone-cli",
            "worker": {
                "sameProcessForAllEvaluations": runtime_context is not None,
                "domainReused": bool(runtime_context and runtime_context.domain_reused),
                "locatorReused": bool(runtime_context and runtime_context.locator_reused),
                "topologySessionHit": bool(runtime_context and runtime_context.session_hit),
            },
        }
        checkpoint()
        report("exporting-files", "Exportuji soubory série.", 0.94)
        summary_json = Path(options.batch_summary_json or batch_directory / f"{source_stem}_density_batch_summary.json")
        summary_csv = Path(options.batch_summary_csv or batch_directory / f"{source_stem}_density_batch_summary.csv")
        summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        write_csv(summary_csv, SUMMARY_FIELDS, summary_rows)
        produced_files.extend([summary_json, summary_csv])
        zip_path = Path(options.batch_zip or batch_directory / f"{source_stem}_density_series.zip")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        report("creating-zip", "Vytvářím ZIP archiv.", 0.98)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for produced in produced_files:
                checkpoint()
                archive.write(produced, arcname=produced.name)
        report("result-ready", "Série hustot je připravena.", 1.0)
        return {
            "mode": "batch",
            "batchDirectory": str(batch_directory),
            "summaryPath": str(summary_json),
            "summaryCsvPath": str(summary_csv),
            "zipPath": str(zip_path),
            "summary": summary,
        }


if __name__ == "__main__":
    main()
