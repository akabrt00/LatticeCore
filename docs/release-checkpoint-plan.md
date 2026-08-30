# Release checkpoint commit plan

## Working tree inventory

The checkpoint remains intentionally uncommitted on branch `master` at
`f9b8724263ae6cfe44bb238861164b9142c0d1ef`. The original tree contains modified tracked files
and the new geometry, runtime, test, benchmark, script and documentation files listed by
`git status --short`. The clean-room audit did not modify or clean that source inventory.

Do not commit `.venv`, `node_modules`, `dist`, cache, jobs, results, exports, logs, local STL/OBJ
models or screenshots. No large binary fixture is required by the current automated tests.

Proposed branch: `codex/release-checkpoint-persistent-worker`

## Proposed commits

### 1. `chore(project): define reproducible runtime and dependency checks`

Body: constrain supported Node/Python versions, add test scripts and preserve the scoped PostCSS
security patch in the lockfile.

Files:

- `.gitignore`
- `package.json`
- `package-lock.json`
- `requirements.txt`
- `requirements-dev.txt`
- `scripts/run-python-tests.mjs`
- `scripts/start-dev.ps1`
- `scripts/clean-install-smoke.ps1`
- `scripts/create-clean-room.ps1`

Dependencies: none.

Tests: clean `npm ci`, `npm audit --json`, `npm run build`, Python import smoke.

### 2. `feat(geometry): stabilize implicit Voronoi lattice generation`

Body: add the implicit union engine, mesh validation and deterministic geometry metadata.

Files:

- `python_app/voronoi_sphere_lines_mvp.py`
- `python_app/implicit_meshing.py`
- `python_app/geometry_baselines.json`

Dependencies: commit 1.

Tests: direct-generation, implicit-meshing, metadata and geometry-baseline Python tests.

### 3. `feat(import): add watertight imported and conformal domains`

Body: validate imported STL/OBJ domains and generate open-volume or conformal surface lattices.

Files:

- `python_app/imported_mesh.py`
- `python_app/conformal_surface.py`
- related `python_app/test_imported_*.py` and `test_conformal_*.py`

Dependencies: commits 1-2.

Tests: imported mesh, clipping, conformal surface and closed-mesh smoke tests.

### 4. `feat(density): add target solver and batch exports`

Body: implement single-target and batch density execution with reusable evaluations and reports.

Files:

- `python_app/density_solver.py`
- `python_app/density_runner.py`
- `python_app/density_batch.py`
- density-specific Python tests

Dependencies: commits 1-3.

Tests: density solver, final correction, batch, CSV/ZIP and cancellation tests.

### 5. `feat(runtime): add cache, debug payloads and persistent worker`

Body: add bounded disk/RAM caches, debug export, memory telemetry, retention and crash recovery.

Files:

- `python_app/cache_store.py`
- `python_app/debug_payload.py`
- `python_app/memory_metrics.py`
- `python_app/lattice_worker.py`
- `server/latticeWorkerManager.js`
- `server/latticeJobRequest.js`
- `vite.config.js`
- runtime/cache/worker server and Python tests

Dependencies: commits 1-4.

Tests: all worker protocol, memory, cache, recovery, retention and server tests.

### 6. `feat(ui): connect lattice jobs and runtime controls`

Body: expose generation modes, progress, cancellation, exports and worker/cache diagnostics.

Files:

- `index.html`
- `src/latticecore.js`
- `src/styles.css`

Dependencies: commit 5.

Tests: production build, localhost browser smoke, direct/imported/conformal/density API smoke.

### 7. `test(benchmark): add release geometry and worker evidence`

Body: preserve deterministic baselines, worker benchmark tooling and latest benchmark summaries.

Files:

- `python_app/test_*.py` not already grouped above
- `server/*.test.js`
- `python_app/benchmark_worker.py`
- `benchmarks/latest-worker-benchmark.json`
- `benchmarks/latest-worker-benchmark.md`

Dependencies: commits 2-6.

Tests: `npm run test:all`, benchmark quick preset, UTF-8 worker tests.

### 8. `docs(security): document clean-room release audit`

Body: add architecture/setup documentation, CycloneDX SBOM, license inventory, security analysis,
clean-room evidence and release checklist.

Files:

- `README.md`
- `docs/architecture.md`
- `docs/development-setup.md`
- `docs/troubleshooting.md`
- `docs/persistent-worker-report.md`
- `docs/release-checkpoint-report.md`
- `docs/release-checkpoint-plan.md`
- `docs/clean-room-validation.md`
- `docs/release-checklist.md`
- `docs/security/*`
- `scripts/generate_sbom.py`

Dependencies: commits 1-7, because the generated SBOM hashes `package-lock.json` and requirements.

Tests: regenerate SBOM, scan reports for absolute paths, `git diff --check`.

## Special handling

- `package.json` and `package-lock.json` stay together in commit 1.
- Requirements files stay together in commit 1.
- Benchmark results belong in commit 7, not with runtime source.
- The generated SBOM belongs in commit 8 and must be regenerated after any dependency change.
- Do not add large binary fixtures; generate the small closed cube during smoke tests.
- Stage each group explicitly. Do not use `git add .`.
- Run the listed focused tests after each commit, then `npm run test:all` after the final commit.

No commit or push is part of this audit.
