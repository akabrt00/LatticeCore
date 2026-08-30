import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const configured = process.env.LATTICECORE_PYTHON;
const venv = path.join(root, ".venv", "Scripts", "python.exe");
const candidates = [
  configured,
  fs.existsSync(venv) ? venv : null,
  "python",
  "py",
].filter(Boolean);

let lastError = null;
for (const executable of candidates) {
  const prefix = executable === "py" ? ["-3"] : [];
  const probe = spawnSync(executable, [...prefix, "-c", "import numpy, scipy, pyvista, vtk"], {
    cwd: root,
    stdio: "ignore",
    windowsHide: true,
  });
  if (probe.status !== 0) {
    lastError = `${executable} nemá potřebné Python závislosti.`;
    continue;
  }
  const result = spawnSync(
    executable,
    [...prefix, "-m", "unittest", "discover", "-s", "python_app", "-p", "test_*.py"],
    { cwd: root, stdio: "inherit", windowsHide: true },
  );
  process.exit(result.status ?? 1);
}

console.error(lastError ?? "Nebyl nalezen použitelný Python.");
process.exit(1);
