from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith(("#", "-r ")):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)", value)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def short_license(metadata: importlib.metadata.PackageMetadata) -> str:
    expression = metadata.get("License-Expression")
    if expression:
        return expression
    value = (metadata.get("License") or "").strip()
    if value and "\n" not in value and len(value) <= 120:
        return value
    classifiers = metadata.get_all("Classifier") or []
    license_classifiers = [item.removeprefix("License :: ").strip() for item in classifiers if item.startswith("License :: ")]
    return " AND ".join(license_classifiers) if license_classifiers else "NOASSERTION"


def node_components(project_root: Path) -> list[dict]:
    lock = json.loads((project_root / "package-lock.json").read_text(encoding="utf-8"))
    root = lock["packages"][""]
    runtime_direct = set(root.get("dependencies", {}))
    development_direct = set(root.get("devDependencies", {}))
    seen: set[tuple[str, str]] = set()
    components: list[dict] = []
    for package_path, package in sorted(lock.get("packages", {}).items()):
        if not package_path or "node_modules/" not in package_path or not package.get("version"):
            continue
        name = package_path.rsplit("node_modules/", 1)[-1]
        version = str(package["version"])
        key = (name, version)
        if key in seen:
            continue
        seen.add(key)
        direct = name in runtime_direct or name in development_direct
        usage = "runtime" if name in runtime_direct else "development" if name in development_direct or package.get("dev") else "transitive-runtime"
        components.append({
            "type": "library",
            "bom-ref": f"pkg:npm/{name}@{version}",
            "name": name,
            "version": version,
            "purl": f"pkg:npm/{name}@{version}",
            "licenses": [{"license": {"name": package.get("license", "NOASSERTION")}}],
            "properties": [
                {"name": "latticecore:ecosystem", "value": "node"},
                {"name": "latticecore:relationship", "value": "direct" if direct else "transitive"},
                {"name": "latticecore:usage", "value": usage},
            ],
        })
    return components


def python_components(project_root: Path) -> list[dict]:
    direct = requirement_names(project_root / "requirements.txt")
    components: list[dict] = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda item: (item.metadata.get("Name") or "").lower()):
        name = distribution.metadata.get("Name")
        if not name:
            continue
        normalized = name.lower().replace("_", "-")
        if normalized in {"pip", "setuptools", "wheel"}:
            continue
        relationship = "direct" if normalized in direct else "transitive"
        purl_name = normalized.replace(".", "-")
        components.append({
            "type": "library",
            "bom-ref": f"pkg:pypi/{purl_name}@{distribution.version}",
            "name": name,
            "version": distribution.version,
            "purl": f"pkg:pypi/{purl_name}@{distribution.version}",
            "licenses": [{"license": {"name": short_license(distribution.metadata)}}],
            "properties": [
                {"name": "latticecore:ecosystem", "value": "python"},
                {"name": "latticecore:relationship", "value": relationship},
                {"name": "latticecore:usage", "value": "runtime"},
            ],
        })
    return components


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the LatticeCore CycloneDX SBOM.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    application_version = str(package["version"])
    inputs = ["package-lock.json", "requirements.txt", "requirements-dev.txt"]
    components = node_components(root) + python_components(root)
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:5dc2dfc9-5fd2-41cf-9abc-c67052944973",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {
                "type": "application",
                "bom-ref": f"pkg:generic/latticecore@{application_version}",
                "name": "LatticeCore",
                "version": application_version,
            },
            "properties": [
                {"name": f"latticecore:sha256:{name}", "value": sha256(root / name)}
                for name in inputs
            ],
        },
        "components": components,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(components)} components to {args.output.name}")


if __name__ == "__main__":
    main()
