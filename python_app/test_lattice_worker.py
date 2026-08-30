import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "python_app" / "lattice_worker.py")],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.ready = self.read()

    def tearDown(self):
        if self.process.poll() is None:
            self.send({"protocolVersion": 1, "command": "shutdown", "requestId": "tear-down"})
            self.process.wait(timeout=10)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()

    def send(self, command):
        self.process.stdin.write(json.dumps(command) + "\n")
        self.process.stdin.flush()

    def read(self):
        line = self.process.stdout.readline()
        self.assertTrue(line)
        return json.loads(line)

    def test_ready_ping_invalid_command_and_shutdown(self):
        self.assertEqual(self.ready["type"], "worker-ready")
        self.assertIn("generate-direct", self.ready["capabilities"])
        self.send({"protocolVersion": 1, "command": "ping", "requestId": "ping"})
        pong = self.read()
        self.assertEqual(pong["type"], "pong")
        self.assertEqual(pong["workerPid"], self.ready["workerPid"])
        self.send({"protocolVersion": 1, "command": "unknown", "requestId": "unknown"})
        self.assertEqual(self.read()["type"], "protocol-error")
        self.send({"protocolVersion": 1, "command": "shutdown", "requestId": "shutdown"})
        self.assertEqual(self.read()["type"], "shutdown-ack")
        self.process.wait(timeout=10)

    def test_invalid_json_does_not_kill_worker(self):
        self.process.stdin.write("not-json\n")
        self.process.stdin.flush()
        self.assertEqual(self.read()["type"], "protocol-error")
        self.send({"protocolVersion": 1, "command": "ping", "requestId": "after-invalid"})
        self.assertEqual(self.read()["type"], "pong")

    def test_two_jobs_keep_same_pid_and_sequences_increase(self):
        pids = []
        for index in range(2):
            output = ROOT / "exports" / f"worker-test-{index}.stl"
            metadata = ROOT / "exports" / f"worker-test-{index}.json"
            arguments = [
                "--shape", "box", "--box-size-x", "8", "--box-size-y", "8", "--box-size-z", "8",
                "--points", "10", "--tube-radius", "0.35", "--surface-tube-radius", "0.35",
                "--min-strut-length-mm", "0.2", "--mesh-engine", "legacy-primitives",
                "--no-shell", "--no-show", "--export-stl", str(output), "--metadata-json", str(metadata),
                "--cache-directory", str(ROOT / "cache"),
            ]
            job_id = f"job-{index}"
            self.send({
                "protocolVersion": 1,
                "command": "run-job",
                "jobId": job_id,
                "jobType": "generate-direct",
                "payload": {"arguments": arguments},
            })
            sequences = []
            messages = []
            terminal = None
            while terminal is None:
                event = self.read()
                if event.get("jobId") == job_id:
                    sequences.append(event["sequence"])
                    if event.get("message"):
                        messages.append(event["message"])
                    if event["type"] in {"job-complete", "job-failed", "job-cancelled"}:
                        terminal = event
            self.assertEqual(terminal["type"], "job-complete")
            self.assertEqual(sequences, sorted(sequences))
            self.assertTrue(any("Čtu" in message for message in messages))
            self.assertFalse(any("\ufffd" in message for message in messages))
            pids.append(terminal["workerPid"])
            output.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
        self.assertEqual(pids, [self.ready["workerPid"], self.ready["workerPid"]])


if __name__ == "__main__":
    unittest.main()
