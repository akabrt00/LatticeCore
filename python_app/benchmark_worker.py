"""Repeatable persistent-worker benchmark for the LatticeCore release checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pyvista as pv


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"
TEMP = ROOT / "exports" / "benchmark-temp"
CACHE = ROOT / "cache" / "benchmark"


def base_arguments(output: Path, metadata: Path) -> list[str]:
    return [
        "--shape", "box", "--box-size-x", "6", "--box-size-y", "6", "--box-size-z", "6",
        "--points", "8", "--tube-radius", "0.5", "--surface-tube-radius", "0.5",
        "--min-strut-length-mm", "0.4", "--random-seed", "4242",
        "--mesh-engine", "implicit-union", "--quality-preset", "preview",
        "--no-show", "--export-stl", str(output), "--metadata-json", str(metadata),
        "--cache-directory", str(CACHE),
    ]


def scenarios(cube: Path) -> dict[str, tuple[str, list[str]]]:
    result = {}
    direct_output = TEMP / "parametric-direct.stl"
    direct_metadata = TEMP / "parametric-direct.json"
    result["parametric-box-direct"] = (
        "generate-direct",
        base_arguments(direct_output, direct_metadata),
    )
    for name, structure in [
        ("imported-open-volume", "open-volume"),
        ("imported-conformal", "conformal-surface"),
    ]:
        output = TEMP / f"{name}.stl"
        metadata = TEMP / f"{name}.json"
        args = base_arguments(output, metadata)
        args[0:8] = ["--input-mesh", str(cube), "--source-original-name", "benchmark-cube.stl", "--points", "8"]
        args.extend(["--boundary-structure-mode", structure])
        if structure == "conformal-surface":
            args.extend([
                "--surface-sampling-mode", "custom",
                "--surface-sampling-step-mm", "2.0",
                "--surface-smoothing-iterations", "0",
                "--surface-connector-spacing-mm", "3.0",
                "--surface-connector-maximum-length-mm", "6.0",
                "--maximum-surface-working-triangles", "2000",
            ])
        result[name] = ("generate-direct", args)

    density_output = TEMP / "density-single.stl"
    density_metadata = TEMP / "density-single.json"
    density_args = base_arguments(density_output, density_metadata)
    density_args[0:0] = [
        "--target-relative-density", "0.08",
        "--density-maximum-iterations", "2",
        "--density-solver-quality", "preview",
        "--density-tolerance-percent-points", "5",
        "--no-verify-at-final-quality",
        "--maximum-final-correction-iterations", "0",
        "--density-csv", str(TEMP / "density-single.csv"),
    ]
    result["density-single"] = ("solve-density-single", density_args)

    batch_args = list(density_args)
    batch_args[batch_args.index("--target-relative-density") + 1] = "0.06"
    batch_args[0:0] = [
        "--density-batch-targets-percent", "6,8",
        "--batch-output-directory", str(TEMP / "density-batch"),
        "--batch-summary-json", str(TEMP / "density-batch" / "density_batch_summary.json"),
        "--batch-summary-csv", str(TEMP / "density-batch" / "density_batch_summary.csv"),
        "--batch-zip", str(TEMP / "density-batch" / "density_series.zip"),
    ]
    result["density-batch"] = ("solve-density-batch", batch_args)
    return result


class WorkerClient:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "python_app" / "lattice_worker.py")],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.stderr_tail: deque[str] = deque(maxlen=200)
        self.stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self.stderr_thread.start()
        self.ready = self.read_until(lambda message: message.get("type") == "worker-ready")

    def _drain_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.stderr_tail.append(line.rstrip())

    def send(self, message: dict) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps({"protocolVersion": 1, **message}) + "\n")
        self.process.stdin.flush()

    def read_until(self, predicate):
        assert self.process.stdout is not None
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(
                    "Worker exited during benchmark: " + "\n".join(self.stderr_tail)[-2000:]
                )
            message = json.loads(line)
            if predicate(message):
                return message

    def run(self, job_id: str, job_type: str, arguments: list[str]) -> dict:
        self.send({"command": "get-status", "requestId": f"before-{job_id}"})
        before = self.read_until(lambda item: item.get("requestId") == f"before-{job_id}")
        started = time.perf_counter()
        self.send({
            "command": "run-job",
            "jobId": job_id,
            "jobType": job_type,
            "payload": {"arguments": arguments},
        })
        events = []
        result = None
        while True:
            message = self.read_until(lambda _: True)
            if message.get("jobId") != job_id:
                continue
            events.append(message)
            if message.get("type") == "result-ready":
                result = message.get("result")
            if message.get("type") == "job-failed":
                raise RuntimeError(message.get("message", "Benchmark job failed."))
            if message.get("type") == "job-complete":
                break
        self.send({"command": "get-status", "requestId": f"status-{job_id}"})
        status = self.read_until(lambda item: item.get("requestId") == f"status-{job_id}")
        return {
            "wallTimeSeconds": time.perf_counter() - started,
            "events": events,
            "result": result,
            "status": status,
            "before": before,
        }

    def close(self) -> None:
        if self.process.poll() is None:
            self.send({"command": "shutdown", "requestId": "shutdown"})
            self.process.wait(timeout=15)


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summarize(run: dict, arguments: list[str]) -> dict:
    def option(name: str) -> Path | None:
        try:
            return Path(arguments[arguments.index(name) + 1])
        except (ValueError, IndexError):
            return None

    metadata_path = option("--metadata-json")
    metadata = {}
    if metadata_path and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    output = option("--export-stl")
    progress = [event for event in run["events"] if event.get("type") == "progress"]
    phases = {}
    for event in progress:
        phase = event.get("phase")
        if phase:
            phases[phase] = event.get("metrics", {})
    memory = run["status"].get("memory", {})
    before_memory = run["before"].get("memory", {})
    cache = metadata.get("cache", {})
    statistics = metadata.get("statistics", {})
    validation = metadata.get("meshValidation", {})
    volume = metadata.get("volumeStatistics", {})
    return {
        "totalTimeSeconds": run["wallTimeSeconds"],
        "phaseMetrics": phases,
        "ramSession": metadata.get("memoryCache"),
        "diskCache": cache,
        "processWorkingSetBeforeBytes": before_memory.get("processWorkingSetBytes"),
        "processWorkingSetAfterBytes": memory.get("processWorkingSetBytes"),
        "processPeakWorkingSetBytes": memory.get("processPeakWorkingSetBytes"),
        "meshVertexCount": statistics.get("meshVertexCount"),
        "meshTriangleCount": statistics.get("meshTriangleCount"),
        "volumeMm3": volume.get("latticeVolumeMm3"),
        "watertight": validation.get("isWatertight"),
        "edgeManifold": validation.get("isEdgeManifold"),
        "stlSha256": file_sha256(output) if output else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--quick", action="store_true", help="Run only the parametric smoke scenario.")
    parser.add_argument("--scenario", action="append", help="Run only a named scenario; may be repeated.")
    args = parser.parse_args()
    shutil.rmtree(TEMP, ignore_errors=True)
    shutil.rmtree(CACHE, ignore_errors=True)
    TEMP.mkdir(parents=True, exist_ok=True)
    BENCHMARKS.mkdir(parents=True, exist_ok=True)
    cube = TEMP / "benchmark-cube.stl"
    pv.Cube(bounds=(-3, 3, -3, 3, -3, 3)).triangulate().save(cube)
    selected = scenarios(cube)
    if args.quick:
        selected = {"parametric-box-direct": selected["parametric-box-direct"]}
    if args.scenario:
        unknown = sorted(set(args.scenario) - set(selected))
        if unknown:
            parser.error(f"Unknown scenario: {', '.join(unknown)}")
        selected = {name: selected[name] for name in args.scenario}

    report = {
        "schemaVersion": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "scenarios": {},
    }
    client = WorkerClient()
    try:
        report["worker"] = {
            "pid": client.ready.get("workerPid"),
            "versions": client.ready.get("versions"),
        }
        for name, (job_type, arguments) in selected.items():
            first = client.run(f"{name}-first", job_type, arguments)
            repeat = client.run(f"{name}-repeat", job_type, arguments)
            report["scenarios"][name] = {
                "firstPersistentRun": summarize(first, arguments),
                "repeatedRamSessionRun": summarize(repeat, arguments),
            }
    finally:
        client.close()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = BENCHMARKS / f"worker-benchmark-{stamp}.json"
    md_path = BENCHMARKS / f"worker-benchmark-{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = ["# LatticeCore worker benchmark", "", "| Scenario | First (s) | RAM repeat (s) | Peak MiB |", "|---|---:|---:|---:|"]
    for name, values in report["scenarios"].items():
        first = values["firstPersistentRun"]
        repeat = values["repeatedRamSessionRun"]
        peak = repeat.get("processPeakWorkingSetBytes")
        rows.append(f"| {name} | {first['totalTimeSeconds']:.3f} | {repeat['totalTimeSeconds']:.3f} | {peak / 1024**2:.1f} |" if peak else f"| {name} | {first['totalTimeSeconds']:.3f} | {repeat['totalTimeSeconds']:.3f} | n/a |")
    md_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    if args.overwrite:
        shutil.copy2(json_path, BENCHMARKS / "latest-worker-benchmark.json")
        shutil.copy2(md_path, BENCHMARKS / "latest-worker-benchmark.md")
    print(json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
