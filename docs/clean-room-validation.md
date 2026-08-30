# Clean-room validation

Date: 2026-07-30

## Isolation

A deterministic PowerShell script copied the current tracked and untracked, non-ignored source
files to a new directory in the system temporary area. The copy was made from the uncommitted
worktree, not from HEAD.

The source manifest contains relative names, sizes and SHA-256 hashes. It contains no absolute
path. Initial verification found 64 source files, zero missing or changed hashes, zero forbidden
directories and zero forbidden generated files.

Excluded categories:

- `.git`, `node_modules`, `.venv`, `__pycache__`, `.pytest_cache`;
- `dist`, `build`, cache, jobs, results and exports;
- STL/OBJ user models, NPZ cache data, ZIP results, logs and temporary files.

## Final clean installations

- Node.js 24.15.0, npm 11.12.1.
- `npm ci`: passed; npm reported 16 packages added in 6 s; the complete install/audit/version
  command took 11.95 s.
- Installed PostCSS: 8.5.25; `npm audit --json`: 0 vulnerabilities.
- No package lifecycle script produced output.
- Python 3.13.0 in a newly created `.venv`.
- pip 24.2 inside the final `.venv`.
- Environment creation: 18.05 s; Python dependency installation: 127.13 s.
- Main versions: NumPy 2.5.1, SciPy 1.18.0, PyVista 0.48.4, VTK 9.6.2.
- psutil was not installed and remains optional.

An earlier preliminary copy required an `ensurepip` workaround because of restricted temporary
directory permissions. The final post-remediation copy was recreated from source and used a
standard new venv with its own pip; the workaround is not part of the final validation.

## Tests and build

- Server tests: 16/16 passed, including all original 13 and three public-output tests.
- Python tests: 123/123 passed in 204.868 s.
- Geometry baseline tests passed within their existing tolerances.
- Production build: passed in 0.636 s.
- Remaining warning: the minified browser chunk is larger than 500 kB.
- VTK/PyVista emitted deprecation warnings; no test failed.

## Runtime and health

The final clean-room Vite server used port 5184 and its own Python executable. Port 5183 was
transiently occupied by an earlier test launcher; the original app on 5173 was not stopped.

- Worker ready handshake: passed.
- `/api/health`: HTTP 200 and `status: ok`.
- Worker: `ready`, protocol 1, responsive.
- Disk cache available and RAM cache enabled.
- Health and worker responses contained no absolute local path.
- Browser smoke loaded the LatticeCore heading, local-running badge and one Three.js canvas with
  no horizontal page overflow.
- Physical worker termination recovered to a new PID. Final status was `ready`, responsive,
  restart count 2 and approximately 158 MiB working set.

## Geometry smoke

| Scenario | Status | Time (s) | Triangles | Boundary edges | Non-manifold edges | Watertight |
|---|---|---:|---:|---:|---:|---|
| Parametric direct box | PASS | 8.25 | 12,856 | 0 | 0 | yes |
| Imported closed cube, open volume | PASS | 4.82 | 5,064 | 0 | 0 | yes |
| Imported conformal cube | PASS | 8.71 | 8,776 | 0 | 0 | yes |
| Single density target | PASS | 11.30 | 10,900 | 0 | 0 | yes |

All four results were edge-manifold, had positive signed volume, finite metadata, a result ID,
an STL and metadata. The two-target density batch completed and produced path-free JSON, CSV and
ZIP assets. Cancellation ended as `cancelled`.

API health, worker status, SSE, job/result metadata, error output, CSV, JSON and all eight ZIP
entry names were checked for private path structures. No leak was found.

## Post-remediation conclusion

The second physical copy was created only after the PostCSS patch, sanitization tests and release
documents were present. Its manifest contained 71 source files with zero forbidden artifacts and
zero hash errors. `npm ci`, npm audit, all tests, build, worker start, browser smoke and every API
scenario above were repeated against that final source state.

The browser's initial page load also queued the application's normal 122-point preview. It entered
a long native VTK phase before the deliberately small smoke job. Cooperative cancellation cannot
interrupt that native call, so the clean-room worker was physically restarted; the queued smoke
job then completed. This confirms recovery but preserves the known cancellation limitation.
