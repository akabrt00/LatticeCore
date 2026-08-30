# Architecture

The browser sends a canonical job request to Vite middleware. `LatticeWorkerManager` owns a single
FIFO slot, job retention, result exposure and SSE history. It communicates with one Python process
through NDJSON.

The Python worker keeps imported domains, locators and topology arrays in a bounded LRU session
cache. Geometry functions remain callable as standalone CLI functions. The worker only adds
progress, cancellation, memory checks and reuse.

## Lifecycle

1. Vite creates private input/output paths and a public job ID.
2. The manager queues the canonical argument list.
3. The worker emits `job-start`, progress, `result-ready`, and a terminal event.
4. A result becomes public only after `result-ready`.
5. Job metadata and result files expire independently.
6. Unexpected worker exit marks only the active job `worker-lost`; queued jobs wait for a new
   `worker-ready` handshake.

## Memory

`processWorkingSetBytes` is operating-system process memory. `pythonTracked*` is only the Python
allocator view from `tracemalloc`. NumPy, voxel and session values are explicit estimates. A voxel
preflight combines current working set, estimated fields and temporary FlyingEdges overhead.

Defaults are a 4096 MiB soft limit, a 6144 MiB hard limit, three RAM sessions and 30 minutes idle
session retention. Values are configurable through `LATTICE_*` environment variables.
