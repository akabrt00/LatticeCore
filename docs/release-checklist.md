# Release checklist

Date: 2026-07-30

## Source tree

- PASS - Original uncommitted worktree was not reset, cleaned, restored, committed or pushed.
- PASS - Branch, HEAD, status and untracked file inventory were recorded.
- PASS - Clean-room source manifest uses relative paths and SHA-256 hashes.
- PASS - Generated caches, results, environments and user models were excluded.

## Dependencies

- PASS - Clean Node installation used `npm ci`.
- PASS - Python dependencies were installed in a new virtual environment.
- PASS - High advisory `GHSA-r28c-9q8g-f849` was identified and code-path audited.
- PASS - Scoped patch remediation was applied without a force or major upgrade.
- PASS - Post-remediation `npm audit --json` reports zero vulnerabilities.
- ACCEPTED RISK - Requirements use compatible ranges rather than a fully hashed Python lockfile.

## Tests

- PASS - All 123 Python tests passed in the clean environment.
- PASS - All original 13 server tests passed.
- PASS - UTF-8 worker tests passed.
- PASS - Public-output sanitization covers health, worker, SSE, metadata, CSV, JSON, ZIP names and errors.

## Build

- PASS - Production Vite build passed.
- PASS - Local browser smoke rendered the heading, status and Three.js canvas without page overflow.
- ACCEPTED RISK - The production browser chunk remains larger than 500 kB.

## Worker

- PASS - Clean worker reached ready and reported its library versions.
- PASS - Cancellation smoke passed.
- PASS - Physical crash recovery returned to ready with a new worker process.
- PASS - Memory working-set metrics were available.

## Clean-room

- PASS - A physical copy outside the source repository was tested.
- PASS - The initial copy had no forbidden artifacts or manifest hash errors.
- PASS - Health response was path-free.
- PASS - Direct, imported, conformal, density single and density batch jobs completed.

## Security

- PASS - Dependency path and runtime/development classification are documented.
- PASS - STL/OBJ, SSE, ZIP and filesystem reachability were reviewed.
- PASS - Public API and generated export metadata were checked for absolute paths.
- PASS - CycloneDX SBOM and third-party license summary exist.
- ACCEPTED RISK - Vite development server is still the normal local runtime; it binds only to localhost.

## Geometry regression

- PASS - All smoke meshes were watertight and edge-manifold with positive signed volume.
- PASS - Geometry baseline remained inside the recorded tolerances.
- PASS - No geometry algorithm or tolerance changed during this audit.

## Documentation

- PASS - Security, clean-room, licenses, checklist and checkpoint reports are updated.
- PASS - Commit grouping is based on the current diff.

## Commit preparation

- PASS - Generated and local-only artifacts are excluded from proposed commits.
- NOT VERIFIED - Commit-by-commit test execution; no commits were created by design.

## Distribution

- NOT VERIFIED - Packaged desktop installer or standalone runtime.
- NOT VERIFIED - Static production API server without Vite HMR.
- NOT VERIFIED - License-notice bundle inside a distributable artifact.

Overall checkpoint status: **PASS for an uncommitted local release checkpoint**. Packaged
distribution remains a separate, explicitly unverified stage.
