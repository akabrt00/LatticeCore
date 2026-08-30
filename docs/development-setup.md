# Development setup

Requirements: Windows, Node.js 20.19 or newer, Python 3.11-3.13, and Git.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
npm install
npm run test:all
npm run dev
```

Open `http://127.0.0.1:5173/` and verify `http://127.0.0.1:5173/api/health`.

`scripts/start-dev.ps1` checks dependencies. It creates a venv or installs packages only when the
corresponding switch is used and the interactive confirmation is accepted.

Useful environment variables:

```text
LATTICECORE_PYTHON
LATTICE_WORKER_MEMORY_SOFT_LIMIT_MIB
LATTICE_WORKER_MEMORY_HARD_LIMIT_MIB
LATTICE_MEMORY_MAXIMUM_SESSIONS
LATTICE_MEMORY_IDLE_MINUTES
LATTICE_JOB_RETENTION_MINUTES
LATTICE_FAILED_JOB_RETENTION_MINUTES
LATTICE_RESULT_RETENTION_MINUTES
```

Run a timestamped quick benchmark with:

```powershell
.\.venv\Scripts\python.exe python_app\benchmark_worker.py --quick --overwrite
```
