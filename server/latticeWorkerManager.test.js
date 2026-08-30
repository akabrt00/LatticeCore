import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { LatticeWorkerManager } from "./latticeWorkerManager.js";

function managerFixture() {
  const writes = [];
  const manager = new LatticeWorkerManager({
    rootDir: path.resolve("."),
    pythonExecutable: "python",
  });
  manager.process = {
    stdin: {
      writable: true,
      write(value) {
        writes.push(JSON.parse(value));
      },
    },
  };
  manager.readyPromise = Promise.resolve();
  manager.status = "ready";
  manager.events = new EventEmitter();
  return { manager, writes };
}

function terminalManagerFixture(options = {}) {
  const fixture = managerFixture();
  Object.assign(fixture.manager, {
    maximumRestarts: options.maximumRestarts ?? 3,
    restartBackoffMs: [0, 0, 0],
    restartWindowMs: 60_000,
  });
  return fixture;
}

test("job is queued and dispatched through one worker slot", () => {
  const { manager, writes } = managerFixture();
  const first = manager.createJob("generate-direct", { arguments: [] });
  manager.dispatch();
  const second = manager.createJob("generate-direct", { arguments: [] });
  assert.equal(first.status, "queued");
  assert.equal(writes.length, 1);
  assert.equal(writes[0].jobId, first.jobId);
  assert.equal(manager.activeJobId, first.jobId);
  assert.equal(manager.serializeJob(manager.jobs.get(second.jobId)).queuedPosition, 1);
});

test("queued cancellation is immediate and idempotent", () => {
  const { manager } = managerFixture();
  const first = manager.createJob("generate-direct", { arguments: [] });
  const second = manager.createJob("generate-direct", { arguments: [] });
  assert.equal(manager.cancelJob(second.jobId).status, "cancelled");
  assert.equal(manager.cancelJob(second.jobId).status, "cancelled");
  manager.handleMessage({
    protocolVersion: 1,
    jobId: first.jobId,
    type: "job-cancelled",
    sequence: 1,
  });
});

test("running cancellation sends the worker command", () => {
  const { manager, writes } = managerFixture();
  const job = manager.createJob("generate-direct", { arguments: [] });
  manager.handleMessage({
    protocolVersion: 1,
    jobId: job.jobId,
    type: "job-start",
    sequence: 1,
  });
  assert.equal(manager.cancelJob(job.jobId).status, "cancelling");
  assert.equal(writes.at(-1).command, "cancel-job");
});

test("completed and failed jobs retain concrete state", () => {
  const { manager } = managerFixture();
  const complete = manager.createJob("generate-direct", { arguments: [] });
  manager.handleMessage({
    protocolVersion: 1,
    jobId: complete.jobId,
    type: "job-complete",
    sequence: 1,
  });
  assert.equal(manager.serializeJob(manager.jobs.get(complete.jobId)).status, "completed");

  const failed = manager.createJob("generate-direct", { arguments: [] });
  manager.handleMessage({
    protocolVersion: 1,
    jobId: failed.jobId,
    type: "job-failed",
    sequence: 1,
    errorCode: "EXAMPLE",
    message: "concrete error",
  });
  const state = manager.serializeJob(manager.jobs.get(failed.jobId));
  assert.equal(state.status, "failed");
  assert.deepEqual(state.error, { code: "EXAMPLE", message: "concrete error" });
});

test("only the latest 500 events are retained", () => {
  const { manager } = managerFixture();
  manager.status = "busy";
  manager.activeJobId = "occupied";
  const job = manager.createJob("generate-direct", { arguments: [] });
  const internal = manager.jobs.get(job.jobId);
  for (let index = 1; index <= 700; index += 1) {
    manager.appendEvent(internal, { type: "progress", sequence: index });
  }
  assert.equal(internal.events.length, 500);
  assert.equal(internal.events[0].sequence, 201);
});

test("unsupported job type is rejected", () => {
  const { manager } = managerFixture();
  assert.throws(() => manager.createJob("shell-command", {}), /Unsupported job type/);
});

test("unexpected exit marks only active job worker-lost and preserves queue", () => {
  const { manager } = terminalManagerFixture();
  const active = manager.createJob("generate-direct", { arguments: [] });
  manager.dispatch();
  const queued = manager.createJob("generate-direct", { arguments: [] });
  manager.intentionalStop = true;
  manager.handleExit(9, null);
  assert.equal(manager.jobs.get(active.jobId).status, "worker-lost");
  assert.equal(manager.jobs.get(queued.jobId).status, "queued");
  assert.equal(manager.queue.includes(queued.jobId), true);
  assert.deepEqual(manager.lastExit.code, 9);
});

test("retry creates a new job with canonical payload and keeps original state", () => {
  const { manager } = terminalManagerFixture();
  const original = manager.createJob("generate-direct", { arguments: ["--shape", "box"] });
  manager.jobs.get(original.jobId).status = "worker-lost";
  manager.jobs.get(original.jobId).completedAt = new Date().toISOString();
  const retry = manager.retryJob(original.jobId);
  assert.notEqual(retry.jobId, original.jobId);
  assert.equal(retry.retryOfJobId, original.jobId);
  assert.deepEqual(manager.jobs.get(retry.jobId).payload, manager.jobs.get(original.jobId).payload);
  assert.equal(manager.jobs.get(original.jobId).status, "worker-lost");
});

test("restart limiter prevents an infinite restart loop", () => {
  const { manager } = terminalManagerFixture({ maximumRestarts: 3 });
  manager.process = null;
  manager.handleExit(1, null, null);
  clearTimeout(manager.restartTimer);
  manager.process = null;
  manager.handleExit(1, null, null);
  clearTimeout(manager.restartTimer);
  manager.process = null;
  manager.handleExit(1, null, null);
  clearTimeout(manager.restartTimer);
  manager.process = null;
  manager.handleExit(1, null, null);
  assert.equal(manager.status, "failed");
  assert.equal(manager.restartCount, 3);
});

test("expired terminal jobs are removed but active jobs remain", async () => {
  const { manager } = terminalManagerFixture();
  const expired = manager.createJob("generate-direct", { arguments: [] });
  manager.jobs.get(expired.jobId).status = "cancelled";
  manager.jobs.get(expired.jobId).expiresAt = new Date(Date.now() - 1).toISOString();
  const active = manager.createJob("generate-direct", { arguments: [] });
  manager.jobs.get(active.jobId).status = "running";
  await manager.cleanupExpired();
  assert.equal(manager.jobs.has(expired.jobId), false);
  assert.equal(manager.jobs.has(active.jobId), true);
});

test("public state sanitizes local paths and private payloads", () => {
  const { manager } = terminalManagerFixture();
  const created = manager.createJob("generate-direct", {
    arguments: ["--input-mesh", "C:\\Users\\example\\private.stl"],
  });
  const job = manager.jobs.get(created.jobId);
  job.error = { code: "X", message: manager.sanitizeError("failed at C:\\Users\\example\\private.stl") };
  const serialized = JSON.stringify(manager.serializeJob(job));
  assert.equal(serialized.includes("C:\\Users"), false);
  assert.equal(serialized.includes("private.stl"), false);
  assert.equal(serialized.includes("arguments"), false);
});

test("result retention keeps valid assets and removes expired assets idempotently", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "latticecore-result-test-"));
  const exportsDirectory = path.join(root, "exports");
  await fs.mkdir(exportsDirectory);
  const output = path.join(exportsDirectory, "result.stl");
  await fs.writeFile(output, Buffer.from("solid baseline\nendsolid baseline\n"));
  const { manager } = managerFixture();
  manager.rootDir = root;
  const created = manager.createJob("generate-direct", { arguments: [] });
  const job = manager.jobs.get(created.jobId);
  job.result = manager.registerResult(job, { mode: "direct", outputPath: output });
  job.resultId = job.result.resultId;
  assert.ok(await manager.readAsset(job.id, "result.stl"));
  const result = manager.results.get(job.resultId);
  result.expiresAt = new Date(Date.now() - 1).toISOString();
  await manager.cleanupExpired();
  await manager.cleanupExpired();
  assert.equal(await manager.readAsset(job.id, "result.stl"), null);
  await assert.rejects(fs.access(output));
  await fs.rm(root, { recursive: true, force: true });
});

test("incomplete result is never exposed", async () => {
  const { manager } = managerFixture();
  manager.resultByJobId.set("job", "result");
  manager.results.set("result", {
    id: "result",
    jobId: "job",
    assets: new Map([["result.stl", path.join(os.tmpdir(), "missing.stl")]]),
    completed: false,
    expiresAt: new Date(Date.now() + 60_000).toISOString(),
  });
  assert.equal(await manager.readAsset("job", "result.stl"), null);
});
