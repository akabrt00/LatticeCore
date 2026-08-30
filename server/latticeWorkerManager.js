import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import fsSync from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import readline from "node:readline";
import { randomUUID } from "node:crypto";

const TERMINAL = new Set(["completed", "failed", "cancelled", "worker-lost"]);
const JOB_TYPES = new Set(["generate-direct", "solve-density-single", "solve-density-batch"]);
const OUTPUT_OPTIONS = new Set([
  "--export-stl", "--metadata-json", "--density-csv", "--batch-output-directory",
  "--batch-summary-json", "--batch-summary-csv", "--batch-zip",
  "--debug-manifest-json", "--debug-buffer-bin",
]);
const PRIVATE_KEYS = new Set([
  "outputPath", "metadataPath", "batchDirectory", "zipPath", "summaryPath",
  "summaryCsvPath", "temporaryPaths", "payload", "internalResult",
]);

function nowIso() {
  return new Date().toISOString();
}

function sanitizePublic(value) {
  if (Array.isArray(value)) return value.map(sanitizePublic);
  if (!value || typeof value !== "object") return value;
  const result = {};
  for (const [key, item] of Object.entries(value)) {
    if (PRIVATE_KEYS.has(key) || /(?:^|_)(?:path|directory|executable)$/i.test(key)) continue;
    result[key] = sanitizePublic(item);
  }
  return result;
}

function clonePayload(payload) {
  return JSON.parse(JSON.stringify(payload));
}

export class LatticeWorkerManager {
  constructor({
    rootDir,
    pythonExecutable,
    maximumEvents = 500,
    maximumRestarts = 3,
    restartWindowMs = 60_000,
    restartBackoffMs = [1_000, 2_000, 5_000],
    jobRetentionMinutes = Number(process.env.LATTICE_JOB_RETENTION_MINUTES ?? 60),
    failedJobRetentionMinutes = Number(process.env.LATTICE_FAILED_JOB_RETENTION_MINUTES ?? 30),
    resultRetentionMinutes = Number(process.env.LATTICE_RESULT_RETENTION_MINUTES ?? 60),
    spawnWorker = spawn,
  }) {
    this.rootDir = rootDir;
    this.pythonExecutable = pythonExecutable;
    this.maximumEvents = maximumEvents;
    this.maximumRestarts = maximumRestarts;
    this.restartWindowMs = restartWindowMs;
    this.restartBackoffMs = restartBackoffMs;
    this.jobRetentionMs = Math.max(1, jobRetentionMinutes) * 60_000;
    this.failedJobRetentionMs = Math.max(1, failedJobRetentionMinutes) * 60_000;
    this.resultRetentionMs = Math.max(1, resultRetentionMinutes) * 60_000;
    this.spawnWorker = spawnWorker;
    this.status = "stopped";
    this.startedAt = null;
    this.restartCount = 0;
    this.restartHistory = [];
    this.lastExit = null;
    this.process = null;
    this.readyInfo = null;
    this.activeJobId = null;
    this.queue = [];
    this.jobs = new Map();
    this.results = new Map();
    this.resultByJobId = new Map();
    this.pendingRequests = new Map();
    this.stderrTail = [];
    this.intentionalStop = false;
    this.events = new EventEmitter();
    this.readyPromise = null;
    this.restartTimer = null;
    this.lastHeartbeatAt = null;
    this.lastProgressAt = null;
    this.cleanupTimer = setInterval(() => this.cleanupExpired().catch(() => {}), 60_000);
    this.cleanupTimer.unref?.();
  }

  start() {
    if (this.process) return this.readyPromise;
    if (this.status === "failed" && this.restartHistory.length >= this.maximumRestarts) {
      return Promise.reject(new Error("Worker restart limit was reached."));
    }
    this.intentionalStop = false;
    this.status = this.restartCount ? "restarting" : "starting";
    this.startedAt = nowIso();
    this.readyPromise = new Promise((resolve, reject) => {
      const args = this.pythonExecutable === "py"
        ? ["-3", path.join("python_app", "lattice_worker.py")]
        : [path.join("python_app", "lattice_worker.py")];
      let child;
      try {
        child = this.spawnWorker(this.pythonExecutable, args, {
          cwd: this.rootDir,
          stdio: ["pipe", "pipe", "pipe"],
          windowsHide: true,
          env: {
            ...process.env,
            PYTHONUNBUFFERED: "1",
            PYTHONIOENCODING: "utf-8",
            PYTHONUTF8: "1",
          },
        });
      } catch (error) {
        this.status = "failed";
        reject(error);
        return;
      }
      this.process = child;
      readline.createInterface({ input: child.stdout }).on("line", (line) => {
        try {
          this.handleMessage(JSON.parse(line));
          if (this.status === "ready" || this.status === "busy") resolve(this.readyInfo);
        } catch (error) {
          this.status = "failed";
          reject(new Error(`Worker emitted invalid NDJSON: ${error.message}`));
        }
      });
      readline.createInterface({ input: child.stderr }).on("line", (line) => {
        this.stderrTail.push(line);
        if (this.stderrTail.length > 100) this.stderrTail.shift();
        console.error(`[lattice-worker] ${line}`);
      });
      child.once("error", (error) => {
        if (this.process === child) this.status = "failed";
        reject(error);
      });
      child.once("exit", (code, signal) => this.handleExit(code, signal, child));
    });
    return this.readyPromise;
  }

  handleMessage(message) {
    if (message.protocolVersion !== 1) return;
    if (message.type === "heartbeat") {
      this.lastHeartbeatAt = message.timestamp ?? nowIso();
      this.readyInfo = { ...this.readyInfo, memory: message.memory, phase: message.phase };
      return;
    }
    if (message.type === "worker-ready") {
      this.readyInfo = message;
      this.lastHeartbeatAt = nowIso();
      this.status = "ready";
      this.dispatch();
      return;
    }
    if (message.requestId && this.pendingRequests.has(message.requestId)) {
      this.pendingRequests.get(message.requestId).resolve(sanitizePublic(message));
      this.pendingRequests.delete(message.requestId);
    }
    if (!message.jobId) {
      if (message.type === "worker-status") {
        this.readyInfo = { ...this.readyInfo, ...message };
        this.status = message.status;
      }
      return;
    }
    const job = this.jobs.get(message.jobId);
    if (!job) return;
    let publicMessage = sanitizePublic(message);
    if (message.type === "progress") this.lastProgressAt = nowIso();
    if (message.type === "result-ready") {
      job.internalResult = message.result;
      job.result = this.registerResult(job, message.result);
      job.resultId = job.result?.resultId ?? null;
      publicMessage = { ...publicMessage, result: job.result };
    }
    this.appendEvent(job, publicMessage);
    if (message.type === "job-start") {
      job.status = "running";
      job.startedAt = nowIso();
      this.status = "busy";
    } else if (message.type === "job-complete") {
      job.status = "completed";
      this.completeJob(job);
    } else if (message.type === "job-failed") {
      job.status = "failed";
      job.error = {
        code: message.errorCode ?? "GENERATION_FAILED",
        message: this.sanitizeError(message.message),
      };
      this.completeJob(job);
    } else if (message.type === "job-cancelled") {
      job.status = "cancelled";
      this.completeJob(job);
    }
  }

  sanitizeError(message) {
    const text = String(message ?? "Výpočet selhal.");
    return text
      .replace(/[A-Za-z]:\\[^\r\n"']+/g, "[local path]")
      .replace(/\/(?:home|tmp|Users)\/[^\r\n"']+/g, "[local path]");
  }

  appendEvent(job, event) {
    job.events.push(sanitizePublic(event));
    if (job.events.length > this.maximumEvents) job.events.shift();
    job.latestEvent = job.events.at(-1);
    this.events.emit(job.id, job.latestEvent);
  }

  createJob(jobType, payload, { retryOfJobId = null } = {}) {
    if (!JOB_TYPES.has(jobType)) {
      throw Object.assign(new Error("Unsupported job type."), { statusCode: 400 });
    }
    const id = randomUUID();
    const job = {
      id,
      jobType,
      payload: clonePayload(payload),
      retryOfJobId,
      status: "queued",
      createdAt: nowIso(),
      startedAt: null,
      completedAt: null,
      expiresAt: null,
      events: [],
      latestEvent: null,
      result: null,
      resultId: null,
      internalResult: null,
      assets: new Map(),
      temporaryPaths: this.collectTemporaryPaths(payload),
      error: null,
    };
    this.jobs.set(id, job);
    this.queue.push(id);
    this.appendEvent(job, {
      protocolVersion: 1,
      jobId: id,
      sequence: 0,
      type: "job-queued",
      phase: "queued",
      message: "Úloha čeká ve frontě.",
      fraction: 0,
    });
    this.start().then(() => this.dispatch()).catch((error) => {
      job.status = "failed";
      job.error = { code: "WORKER_START_FAILED", message: this.sanitizeError(error.message) };
      this.completeJob(job);
    });
    return this.serializeJob(job);
  }

  retryJob(id) {
    const original = this.jobs.get(id);
    if (!original || !TERMINAL.has(original.status)) return null;
    return this.createJob(original.jobType, original.payload, { retryOfJobId: original.id });
  }

  dispatch() {
    if (this.activeJobId || this.status !== "ready" || !this.process) return;
    while (this.queue.length) {
      const id = this.queue.shift();
      const job = this.jobs.get(id);
      if (!job || job.status !== "queued") continue;
      this.activeJobId = id;
      this.status = "busy";
      this.send({
        protocolVersion: 1,
        command: "run-job",
        jobId: id,
        jobType: job.jobType,
        payload: job.payload,
      });
      return;
    }
  }

  completeJob(job) {
    job.completedAt = nowIso();
    const retention = job.status === "completed" ? this.jobRetentionMs : this.failedJobRetentionMs;
    job.expiresAt = new Date(Date.now() + retention).toISOString();
    if (this.activeJobId === job.id) this.activeJobId = null;
    this.status = this.process ? "ready" : this.status;
    if (job.status !== "worker-lost") this.cleanupInput(job);
    this.events.emit(job.id, { type: "terminal", status: job.status });
    this.dispatch();
  }

  cancelJob(id) {
    const job = this.jobs.get(id);
    if (!job) return null;
    if (TERMINAL.has(job.status)) return this.serializeJob(job);
    if (job.status === "queued") {
      job.status = "cancelled";
      this.appendEvent(job, {
        protocolVersion: 1,
        jobId: id,
        sequence: job.events.length,
        type: "job-cancelled",
        phase: "job-cancelled",
        message: "Čekající úloha byla zrušena.",
      });
      this.completeJob(job);
    } else {
      job.status = "cancelling";
      this.send({ protocolVersion: 1, command: "cancel-job", jobId: id, requestId: randomUUID() });
    }
    return this.serializeJob(job);
  }

  async clearMemoryCache(scope = "unused") {
    if (!["unused", "all"].includes(scope)) {
      throw Object.assign(new Error("Unsupported RAM cache scope."), { statusCode: 400 });
    }
    await this.start();
    return this.request("clear-memory-cache", { scope });
  }

  async memorySessions() {
    await this.start();
    return this.request("get-memory-sessions");
  }

  request(command, values = {}) {
    const requestId = randomUUID();
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(requestId);
        reject(new Error(`Worker command timed out: ${command}`));
      }, 10_000);
      this.pendingRequests.set(requestId, {
        resolve: (value) => {
          clearTimeout(timeout);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timeout);
          reject(error);
        },
      });
      this.send({ protocolVersion: 1, command, requestId, ...values });
    });
  }

  send(message) {
    if (!this.process?.stdin.writable) throw new Error("Lattice worker is not writable.");
    this.process.stdin.write(`${JSON.stringify(message)}\n`);
  }

  async stop() {
    this.intentionalStop = true;
    clearTimeout(this.restartTimer);
    clearInterval(this.cleanupTimer);
    await this.cleanupIncompleteResults();
    if (!this.process) {
      this.status = "stopped";
      return;
    }
    const child = this.process;
    try {
      this.send({ protocolVersion: 1, command: "shutdown", requestId: randomUUID() });
    } catch {}
    await new Promise((resolve) => {
      const timer = setTimeout(() => {
        child.kill();
        resolve();
      }, 5_000);
      child.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
    });
    this.status = "stopped";
  }

  handleExit(code, signal, child = this.process) {
    if (child && this.process && child !== this.process) return;
    this.process = null;
    this.readyPromise = null;
    this.lastExit = { code: code ?? null, signal: signal ?? null, at: nowIso() };
    for (const pending of this.pendingRequests.values()) {
      pending.reject(new Error("Worker process exited."));
    }
    this.pendingRequests.clear();
    if (this.activeJobId) {
      const job = this.jobs.get(this.activeJobId);
      if (job && !TERMINAL.has(job.status)) {
        job.status = "worker-lost";
        job.error = { code: "WORKER_LOST", message: "Python worker neočekávaně skončil." };
        this.appendEvent(job, {
          protocolVersion: 1,
          jobId: job.id,
          type: "worker-lost",
          phase: "worker-lost",
          message: job.error.message,
        });
        this.completeJob(job);
        this.cleanupIncompleteOutputs(job);
      }
      this.activeJobId = null;
    }
    if (this.intentionalStop) {
      this.status = "stopped";
      return;
    }
    const now = Date.now();
    this.restartHistory = this.restartHistory.filter((value) => now - value < this.restartWindowMs);
    if (this.restartHistory.length >= this.maximumRestarts) {
      this.status = "failed";
      return;
    }
    const attempt = this.restartHistory.length;
    const delay = this.restartBackoffMs[Math.min(attempt, this.restartBackoffMs.length - 1)];
    this.restartHistory.push(now);
    this.restartCount += 1;
    this.status = "restarting";
    this.restartTimer = setTimeout(() => {
      this.start().catch(() => {
        if (!this.intentionalStop) this.handleExit(null, "start-failed", null);
      });
    }, delay);
    this.restartTimer.unref?.();
  }

  registerResult(job, result) {
    if (!result) return null;
    const resultId = randomUUID();
    const assets = new Map();
    const addAsset = (name, filePath) => {
      if (!filePath || !fsSync.existsSync(filePath)) return null;
      assets.set(name, path.resolve(filePath));
      return `/api/lattice-jobs/${job.id}/assets/${encodeURIComponent(name)}`;
    };
    let publicResult;
    if (result.mode === "batch") {
      const files = fsSync.existsSync(result.batchDirectory) ? fsSync.readdirSync(result.batchDirectory) : [];
      const publicAssets = {};
      for (const name of files) publicAssets[name] = addAsset(name, path.join(result.batchDirectory, name));
      publicAssets.zip = addAsset("zip", result.zipPath);
      publicAssets["summary-json"] = addAsset("summary-json", result.summaryPath);
      publicAssets["summary-csv"] = addAsset("summary-csv", result.summaryCsvPath);
      publicResult = { resultId, mode: "batch", summary: sanitizePublic(result.summary), assets: publicAssets, zipUrl: publicAssets.zip };
    } else {
      publicResult = {
        resultId,
        mode: result.mode,
        metadata: sanitizePublic(result.metadata),
        stlUrl: addAsset("result.stl", result.outputPath),
        metadataUrl: addAsset("metadata.json", result.metadataPath),
      };
    }
    const record = {
      id: resultId,
      jobId: job.id,
      assets,
      completed: true,
      createdAt: nowIso(),
      expiresAt: new Date(Date.now() + this.resultRetentionMs).toISOString(),
    };
    this.results.set(resultId, record);
    this.resultByJobId.set(job.id, resultId);
    job.assets = assets;
    return publicResult;
  }

  collectTemporaryPaths(payload) {
    const args = payload?.arguments;
    if (!Array.isArray(args)) return [];
    const paths = [];
    for (let index = 0; index < args.length - 1; index += 1) {
      if (OUTPUT_OPTIONS.has(args[index])) paths.push(path.resolve(String(args[index + 1])));
    }
    return paths;
  }

  cleanupInput(job) {
    const args = job?.payload?.arguments;
    const index = Array.isArray(args) ? args.indexOf("--input-mesh") : -1;
    if (index < 0 || index + 1 >= args.length) return;
    this.safeRemove(args[index + 1], false);
  }

  cleanupIncompleteOutputs(job) {
    const completedAssets = new Set(job.assets?.values?.() ?? []);
    for (const candidate of job.temporaryPaths ?? []) {
      if (!completedAssets.has(path.resolve(candidate))) this.safeRemove(candidate, true);
    }
  }

  safeRemove(candidate, recursive) {
    const resolved = path.resolve(String(candidate));
    const exportsRoot = path.resolve(this.rootDir, "exports");
    if (resolved === exportsRoot || !resolved.startsWith(`${exportsRoot}${path.sep}`)) {
      return Promise.resolve(false);
    }
    return fs.rm(resolved, { recursive, force: true }).then(() => true).catch(() => false);
  }

  async readAsset(jobId, assetName) {
    const resultId = this.resultByJobId.get(jobId);
    const result = resultId ? this.results.get(resultId) : null;
    const filePath = result?.completed ? result.assets.get(assetName) : null;
    if (!filePath || Date.parse(result.expiresAt) <= Date.now()) return null;
    const resolved = path.resolve(filePath);
    const exportsRoot = path.resolve(this.rootDir, "exports");
    if (resolved !== exportsRoot && !resolved.startsWith(`${exportsRoot}${path.sep}`)) return null;
    return { path: resolved, data: await fs.readFile(resolved) };
  }

  async cleanupExpired(now = Date.now()) {
    for (const [id, job] of this.jobs) {
      if (!TERMINAL.has(job.status) || !job.expiresAt || Date.parse(job.expiresAt) > now) continue;
      this.events.emit(id, { type: "terminal", status: "expired" });
      this.cleanupIncompleteOutputs(job);
      this.jobs.delete(id);
    }
    for (const [id, result] of this.results) {
      if (Date.parse(result.expiresAt) > now) continue;
      await Promise.all([...new Set(result.assets.values())].map((filePath) => this.safeRemove(filePath, true)));
      this.results.delete(id);
      this.resultByJobId.delete(result.jobId);
    }
  }

  async cleanupIncompleteResults() {
    for (const job of this.jobs.values()) {
      if (!TERMINAL.has(job.status)) this.cleanupIncompleteOutputs(job);
    }
  }

  serializeJob(job) {
    if (!job) return null;
    return {
      jobId: job.id,
      jobType: job.jobType,
      retryOfJobId: job.retryOfJobId,
      status: job.status,
      createdAt: job.createdAt,
      startedAt: job.startedAt,
      completedAt: job.completedAt,
      expiresAt: job.expiresAt,
      resultId: job.resultId,
      latestEvent: sanitizePublic(job.latestEvent),
      result: sanitizePublic(job.result),
      error: sanitizePublic(job.error),
      queuedPosition: job.status === "queued" ? this.queue.indexOf(job.id) + 1 : 0,
      eventCount: job.events.length,
    };
  }

  workerStatus() {
    const heartbeatAgeMs = this.lastHeartbeatAt ? Date.now() - Date.parse(this.lastHeartbeatAt) : null;
    let responsiveness = this.process ? "responsive" : "process-exited";
    if (this.process && heartbeatAgeMs !== null && heartbeatAgeMs > 15_000) {
      responsiveness = this.status === "busy" ? "busy-native-operation" : "heartbeat-delayed";
    }
    return sanitizePublic({
      status: this.status,
      responsiveness,
      startedAt: this.startedAt,
      restartCount: this.restartCount,
      restartLimit: this.maximumRestarts,
      restartWindowSeconds: this.restartWindowMs / 1000,
      lastExit: this.lastExit,
      lastHeartbeatAt: this.lastHeartbeatAt,
      lastProgressAt: this.lastProgressAt,
      activeJobId: this.activeJobId,
      queuedJobCount: this.queue.filter((id) => this.jobs.get(id)?.status === "queued").length,
      memorySessionCount: this.readyInfo?.memorySessionCount ?? 0,
      memory: this.readyInfo?.memory ?? null,
      workerPid: this.readyInfo?.workerPid ?? null,
      workerVersion: this.readyInfo?.workerVersion ?? null,
      protocolVersion: this.readyInfo?.protocolVersion ?? 1,
      versions: this.readyInfo?.versions ?? null,
      workerStartTimeSeconds: this.readyInfo?.workerStartTimeSeconds ?? null,
      libraryImportTimeSeconds: this.readyInfo?.libraryImportTimeSeconds ?? null,
      stderrTail: this.status === "failed" ? this.stderrTail.slice(-10).map((line) => this.sanitizeError(line)) : undefined,
    });
  }
}

export const terminalJobStatuses = TERMINAL;
export { sanitizePublic };
