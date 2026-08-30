# Troubleshooting

## Worker does not start

Check `/api/health`, then run the Python import probe from `scripts/start-dev.ps1`. Set
`LATTICECORE_PYTHON` to the project venv if another Python is selected.

## VTK is missing

Activate `.venv`, run `pip install -r requirements.txt`, then confirm with
`python -c "import vtk, pyvista"`.

## Worker keeps restarting

The manager allows three restarts in 60 seconds with 1, 2 and 5 second backoff. After that it stays
`failed`. Inspect the server terminal, fix the cause, and restart Vite.

## Job remains cancelling

VTK FlyingEdges is a native call and cannot be interrupted mid-call. Cancellation completes at the
next safe phase boundary.

## Insufficient RAM

`MEMORY_LIMIT_EXCEEDED` is raised before voxel allocation. Increase `voxelSizeMm`, use preview
quality, reduce geometry size, or raise the configured limit only when the machine has enough RAM.

## Invalid or open STL

Repair boundary and non-manifold edges. Imported volume generation requires a closed watertight
volume.

## Corrupted cache

Use the cache controls in the app. RAM eviction never removes an active session. Disk cache cleanup
does not touch job/result storage.

## Port 5173 is occupied

Stop the old Vite process or run `npx vite --host 127.0.0.1 --port 5174`.

## SSE disconnected

The job continues on the server. Its status remains queryable during retention. A worker crash
changes the active job to `worker-lost`; use the retry endpoint.
