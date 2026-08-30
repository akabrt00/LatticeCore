# Changelog

## 0.2.0 - 2026-08-28

### Added

- Persistent Python worker with cancellable jobs, progress events and local cache.
- Imported STL/OBJ domains, conformal surface lattice, volume lattice and connector generation.
- Implicit watertight meshing, density targeting, diagnostics and JSON/CSV export.
- Printability analysis with optional supplemental struts.
- Automated server, geometry baseline, imported-mesh and worker tests.
- GitHub Actions validation for Node.js, Python, build and dependency audit.

### Changed

- Multi-component imports now keep all closed components by default.
- Volume generation now includes the conformal surface boundary by default.
- Imported models can switch between surface and volume modes in the UI.
- Import errors now explain how to resolve open, non-manifold or multi-component input.
- PyVista interior-point queries use the current cell-locator API.

### Security

- Updated PostCSS to 8.5.25 and Nano ID to 3.3.18 without major dependency upgrades.
- Added response, export and archive sanitization tests and release security notes.
