# Release checkpoint report

Date: 2026-07-30

## Outcome

The release-hardening stage is implemented without changing Voronoi mathematics, geometry
algorithms or meshing tolerances. A physical clean-room validation and dependency security audit
were completed. No git commit or push was created.

The audit began on branch `master` at
`f9b8724263ae6cfe44bb238861164b9142c0d1ef`. The tree already contained modified tracked files and
the untracked geometry, worker, tests, scripts, benchmark and documentation files now grouped in
`release-checkpoint-plan.md`. The original tree was never cleaned, reset, restored or checked out.

## Worker recovery and memory

- Unexpected exit records code, signal and timestamp.
- The active job becomes `worker-lost`; queued jobs remain FIFO.
- Retry creates a new job ID with the canonical payload.
- Restart policy is at most three attempts per 60 seconds with 1, 2 and 5 second backoff.
- A clean-room physical crash changed worker process and recovered to `ready` with restart count 1.
- Windows working set and peak use native process metrics; psutil remains optional.
- Defaults are 4096 MiB soft and 6144 MiB hard limits.
- Hard preflight rejects an unsafe voxel grid before allocation.

## Retention and privacy

- Completed jobs default to 60 minutes; failed terminal jobs default to 30 minutes.
- Results have independent 60-minute retention and appear only after completion.
- API, SSE and public error serialization remove private paths and internal payloads.
- Physical clean-room checks found no path in health, worker status, SSE, job/result metadata,
  JSON, CSV, ZIP names/content or error responses.
- The STL/OBJ allowlist and 100 MiB upload limit remain active.

## Clean-room

- A deterministic source-only copy was created outside the repository with a relative SHA-256
  manifest.
- Initial source count: 64; forbidden artifacts: 0; manifest hash errors: 0.
- Node.js 24.15.0 and npm 11.12.1.
- Final `npm ci`: 16 packages in 6 s, no warnings; PostCSS 8.5.25.
- Python 3.13.0; NumPy 2.5.1, SciPy 1.18.0, PyVista 0.48.4, VTK 9.6.2.
- pip 24.2; venv creation 18.05 s; Python dependency installation 127.13 s.
- Python tests: 123 passed in 204.868 s.
- Server suite: 16 passed, comprising the original 13 and three sanitization tests.
- Production build: passed in 0.636 s.
- Health: `ok`; worker: `ready`, responsive, protocol 1.
- Browser smoke: heading, local badge and Three.js canvas rendered without horizontal overflow.

## Geometry smoke

| Scenario | Time (s) | Triangles | Boundary | Non-manifold | Result |
|---|---:|---:|---:|---:|---|
| Parametric direct box | 8.25 | 12,856 | 0 | 0 | PASS |
| Imported open-volume cube | 4.82 | 5,064 | 0 | 0 | PASS |
| Imported conformal cube | 8.71 | 8,776 | 0 | 0 | PASS |
| Density single | 11.30 | 10,900 | 0 | 0 | PASS |

Every mesh was watertight and edge-manifold with positive signed volume. A two-target density
batch, cancellation and physical worker recovery also passed.

## Dependency security

Before remediation, `npm audit --json` reported high advisory `GHSA-r28c-9q8g-f849` in
`latticecore -> vite@8.1.3 -> postcss@8.5.16`. PostCSS is a transitive development/build
dependency. Its vulnerable untrusted-CSS source-map path is not fed by LatticeCore's STL/OBJ,
SSE, ZIP or geometry data and is not shipped as browser runtime code.

The compatible patch update resolved PostCSS to 8.5.25 and nanoid to 3.3.16. No major upgrade,
override or force audit fix was used. Post-remediation audit reports zero vulnerabilities.
Details are in `security/security-audit-report.md`.

## Benchmark

| Scenario | First (s) | RAM repeat (s) | Peak MiB |
|---|---:|---:|---:|
| Parametric box direct | 7.874 | 7.370 | 197.8 |
| Imported open-volume | 5.305 | 3.034 | 197.8 |
| Imported conformal | 9.898 | 5.349 | 201.8 |
| Density single | 14.816 | 14.394 | 207.0 |
| Density batch | 15.038 | 15.016 | 208.4 |

The existing benchmark meshes remain watertight and edge-manifold.

## Known limitations

- VTK FlyingEdges remains non-interruptible during its native call.
- VTK/PyVista emit forward-looking deprecation warnings with NumPy 2.5.
- The legacy synchronous Vite endpoint remains beside the hardened job API.
- The browser production chunk remains larger than 500 kB.
- Vite development server is still the normal localhost runtime; a packaged static API runtime
  remains unverified.
- Python requirements are bounded but not fully hash-locked.
