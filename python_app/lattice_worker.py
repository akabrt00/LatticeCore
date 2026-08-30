"""Persistent NDJSON worker for LatticeCore geometry jobs."""

from __future__ import annotations

import contextlib
import json
import os
import queue
import sys
import threading
import traceback
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

STARTED = perf_counter()
IMPORT_STARTED = perf_counter()

from density_runner import main as run_density
from voronoi_sphere_lines_mvp import main as run_direct
from worker_runtime import (
    CancellationToken,
    JobCancelledError,
    TopologySessionCache,
    WorkerRuntime,
)
from memory_metrics import memory_snapshot, start_python_tracking

import numpy
import scipy
import pyvista
import vtk

IMPORT_SECONDS = perf_counter() - IMPORT_STARTED
PROTOCOL_VERSION = 1
WORKER_VERSION = "latticecore-worker-1"
JOB_TYPES = {"generate-direct", "solve-density-single", "solve-density-batch"}
PATH_OPTIONS = {
    "--input-mesh", "--input-stl", "--export-stl", "--metadata-json", "--density-csv",
    "--batch-output-directory", "--batch-summary-json", "--batch-summary-csv", "--batch-zip",
    "--debug-manifest-json", "--debug-buffer-bin", "--cache-directory",
}


class Protocol:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequences: dict[str, int] = {}

    def send(self, message: dict[str, Any]) -> None:
        payload = {"protocolVersion": PROTOCOL_VERSION, **message}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            sys.__stdout__.write(encoded + "\n")
            sys.__stdout__.flush()

    def job_event(self, job_id: str, event_type: str, **values: Any) -> None:
        sequence = self._sequences.get(job_id, 0) + 1
        self._sequences[job_id] = sequence
        self.send({"jobId": job_id, "sequence": sequence, "type": event_type, **values})


class LatticeWorker:
    def __init__(self) -> None:
        start_python_tracking()
        self.protocol = Protocol()
        self.sessions = TopologySessionCache(
            maximum_sessions=int(os.environ.get("LATTICE_MEMORY_MAXIMUM_SESSIONS", "3")),
            idle_minutes=float(os.environ.get("LATTICE_MEMORY_IDLE_MINUTES", "30")),
        )
        self.commands: queue.Queue[dict[str, Any]] = queue.Queue()
        self.active_job_id: str | None = None
        self.active_token: CancellationToken | None = None
        self.active_thread: threading.Thread | None = None
        self.shutting_down = False
        self.current_phase = "idle"
        self.last_progress_at = datetime.now(timezone.utc).isoformat()
        self.heartbeat_seconds = max(1.0, float(os.environ.get("LATTICE_HEARTBEAT_SECONDS", "5")))
        self.heartbeat_thread: threading.Thread | None = None
        self.root = Path(__file__).resolve().parents[1]
        self.allowed_root = (self.root / "exports").resolve()

    def status(self) -> dict[str, Any]:
        return {
            "type": "worker-status",
            "status": "busy" if self.active_job_id else "ready",
            "workerPid": os.getpid(),
            "activeJobId": self.active_job_id,
            "phase": self.current_phase,
            "memory": memory_snapshot(
                estimated_session_cache_bytes=self.sessions.estimated_size_bytes()
            ),
            **self.sessions.status(),
        }

    def validate_arguments(self, arguments: Any) -> list[str]:
        if not isinstance(arguments, list) or not all(isinstance(item, (str, int, float)) for item in arguments):
            raise ValueError("INVALID_JOB_ARGUMENTS")
        result = [str(item) for item in arguments]
        for index, option in enumerate(result):
            if option not in PATH_OPTIONS:
                continue
            if index + 1 >= len(result):
                raise ValueError(f"MISSING_PATH_VALUE: {option}")
            candidate = Path(result[index + 1])
            if option == "--cache-directory":
                allowed = (self.root / "cache").resolve()
            else:
                allowed = self.allowed_root
            resolved = candidate.resolve()
            if resolved != allowed and allowed not in resolved.parents:
                raise ValueError(f"PATH_OUTSIDE_SERVER_STORAGE: {option}")
        return result

    def progress(self, job_id: str, **event: Any) -> None:
        self.current_phase = str(event.get("phase") or self.current_phase)
        self.last_progress_at = datetime.now(timezone.utc).isoformat()
        metrics = event.pop("metrics", {})
        estimated_numpy = int(metrics.get("estimatedNumpyBytes", 0) or 0)
        estimated_voxel = int(metrics.get("estimatedVoxelFieldBytes", 0) or 0)
        metrics = {
            **metrics,
            "memory": memory_snapshot(
                estimated_numpy_bytes=estimated_numpy,
                estimated_voxel_field_bytes=estimated_voxel,
                estimated_session_cache_bytes=self.sessions.estimated_size_bytes()
            ),
        }
        self.protocol.job_event(job_id, "progress", **event, metrics=metrics)

    def run_job(self, command: dict[str, Any]) -> None:
        job_id = command["jobId"]
        token = CancellationToken()
        self.active_job_id = job_id
        self.current_phase = "job-start"
        self.active_token = token
        runtime = WorkerRuntime(self.sessions, lambda **event: self.progress(job_id, **event), token)
        started = perf_counter()
        temporary_outputs: list[Path] = []
        try:
            arguments = self.validate_arguments(command.get("payload", {}).get("arguments"))
            for index, option in enumerate(arguments):
                if option in PATH_OPTIONS and option != "--cache-directory" and index + 1 < len(arguments):
                    temporary_outputs.append(Path(arguments[index + 1]))
            self.protocol.job_event(
                job_id,
                "job-start",
                phase="job-start",
                message="Výpočetní úloha byla spuštěna.",
                fraction=0.0,
                workerPid=os.getpid(),
            )
            with contextlib.redirect_stdout(sys.stderr):
                if command["jobType"] == "generate-direct":
                    result = run_direct(arguments, runtime_context=runtime)
                    result_payload = {
                        "mode": "direct",
                        "metadata": result,
                        "outputPath": self._option(arguments, "--export-stl"),
                        "metadataPath": self._option(arguments, "--metadata-json"),
                    }
                else:
                    result_payload = run_density(arguments, runtime_context=runtime)
            token.check()
            self.protocol.job_event(
                job_id,
                "result-ready",
                phase="result-ready",
                message="Výsledky jsou připraveny.",
                fraction=1.0,
                result=result_payload,
                workerPid=os.getpid(),
            )
            self.protocol.job_event(
                job_id,
                "job-complete",
                phase="job-complete",
                message="Výpočetní úloha byla dokončena.",
                fraction=1.0,
                elapsedSeconds=perf_counter() - started,
                workerPid=os.getpid(),
            )
        except JobCancelledError:
            for path in temporary_outputs:
                self._remove_incomplete(path)
            self.protocol.job_event(
                job_id,
                "job-cancelled",
                phase="job-cancelled",
                message="Výpočet byl zrušen.",
                elapsedSeconds=perf_counter() - started,
                workerPid=os.getpid(),
            )
        except Exception as error:
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            self.protocol.job_event(
                job_id,
                "job-failed",
                phase="job-failed",
                message=str(error),
                errorCode=getattr(error, "error_code", "GENERATION_FAILED"),
                elapsedSeconds=perf_counter() - started,
                workerPid=os.getpid(),
            )
        finally:
            runtime.close()
            tracemalloc.reset_peak()
            self.active_job_id = None
            self.current_phase = "idle"
            self.active_token = None
            self.active_thread = None
            self.protocol.send(self.status())

    @staticmethod
    def _option(arguments: list[str], name: str) -> str | None:
        try:
            return arguments[arguments.index(name) + 1]
        except (ValueError, IndexError):
            return None

    def _remove_incomplete(self, path: Path) -> None:
        try:
            if path.is_dir():
                import shutil
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass

    def handle(self, command: dict[str, Any]) -> None:
        request_id = command.get("requestId")
        name = command.get("command")
        if command.get("protocolVersion") != PROTOCOL_VERSION:
            self.protocol.send({"type": "protocol-error", "requestId": request_id, "message": "UNSUPPORTED_PROTOCOL_VERSION"})
            return
        if name == "ping":
            self.protocol.send({"type": "pong", "requestId": request_id, "workerPid": os.getpid()})
        elif name == "get-status":
            self.protocol.send({**self.status(), "requestId": request_id})
        elif name == "clear-memory-cache":
            scope = command.get("scope", "unused")
            removed = self.sessions.clear_details(scope)
            self.protocol.send({
                "type": "memory-cache-cleared",
                "requestId": request_id,
                "scope": scope,
                **removed,
                **self.sessions.status(),
            })
        elif name == "get-memory-sessions":
            self.protocol.send({
                "type": "memory-sessions",
                "requestId": request_id,
                "sessions": self.sessions.session_metrics(),
                "memory": memory_snapshot(
                    estimated_session_cache_bytes=self.sessions.estimated_size_bytes()
                ),
            })
        elif name == "cancel-job":
            job_id = command.get("jobId")
            accepted = bool(job_id and job_id == self.active_job_id and self.active_token)
            if accepted:
                self.active_token.cancel()
            self.protocol.send({"type": "cancel-ack", "requestId": request_id, "jobId": job_id, "accepted": accepted})
        elif name == "run-job":
            job_id = command.get("jobId")
            job_type = command.get("jobType")
            if not isinstance(job_id, str) or not job_id:
                self.protocol.send({"type": "protocol-error", "requestId": request_id, "message": "JOB_ID_REQUIRED"})
            elif job_type not in JOB_TYPES:
                self.protocol.job_event(job_id, "job-failed", phase="job-failed", message="UNSUPPORTED_JOB_TYPE")
            elif self.active_job_id is not None:
                self.protocol.job_event(job_id, "job-failed", phase="job-failed", message="WORKER_BUSY")
            else:
                self.active_thread = threading.Thread(target=self.run_job, args=(command,), daemon=True)
                self.active_thread.start()
        elif name == "shutdown":
            self.shutting_down = True
            if self.active_token is not None:
                self.active_token.cancel()
            self.protocol.send({"type": "shutdown-ack", "requestId": request_id})
        else:
            self.protocol.send({"type": "protocol-error", "requestId": request_id, "message": "UNKNOWN_COMMAND"})

    def heartbeat_loop(self) -> None:
        while not self.shutting_down:
            if threading.Event().wait(self.heartbeat_seconds):
                break
            self.protocol.send({
                "type": "heartbeat",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "activeJobId": self.active_job_id,
                "phase": self.current_phase,
                "lastProgressAt": self.last_progress_at,
                "memory": memory_snapshot(
                    estimated_session_cache_bytes=self.sessions.estimated_size_bytes()
                ),
            })

    def loop(self) -> None:
        self.heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        self.protocol.send({
            "type": "worker-ready",
            "workerVersion": WORKER_VERSION,
            "capabilities": sorted(JOB_TYPES),
            "workerStartTimeSeconds": perf_counter() - STARTED,
            "libraryImportTimeSeconds": IMPORT_SECONDS,
            "workerPid": os.getpid(),
            "versions": {
                "python": sys.version.split()[0],
                "numpy": numpy.__version__,
                "scipy": scipy.__version__,
                "pyvista": pyvista.__version__,
                "vtk": vtk.vtkVersion.GetVTKVersion(),
            },
            **self.sessions.status(),
        })
        while not self.shutting_down:
            try:
                line = sys.stdin.readline()
            except KeyboardInterrupt:
                break
            if line == "":
                break
            try:
                command = json.loads(line)
                if not isinstance(command, dict):
                    raise ValueError("JSON command must be an object.")
            except (json.JSONDecodeError, ValueError) as error:
                self.protocol.send({"type": "protocol-error", "message": f"INVALID_JSON: {error}"})
                continue
            self.handle(command)
        if self.active_thread is not None:
            self.active_thread.join(timeout=10)
        self.sessions.clear_details("all")


def main() -> None:
    for stream in (sys.__stdout__, sys.__stderr__):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    LatticeWorker().loop()


if __name__ == "__main__":
    main()
