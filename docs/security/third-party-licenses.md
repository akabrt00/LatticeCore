# Third-party license summary

Generated for the 2026-07-30 release checkpoint. This is an inventory aid, not legal advice.
Exact transitive versions and detected license identifiers are in `latticecore-sbom.json`.

| Dependency | Tested version | License | Project use | Distribution status |
|---|---:|---|---|---|
| Three.js | 0.166.1 | MIT | Browser 3D preview | Included in the production browser bundle |
| Vite | 8.1.3 | MIT | Development server and production build | Development/build only |
| PostCSS | 8.5.25 | MIT | Transitive Vite CSS processing | Development/build only |
| NumPy | 2.5.1 | BSD-3-Clause plus bundled component licenses | Numerical arrays and geometry data | Python runtime |
| SciPy | 1.18.0 | BSD-3-Clause plus bundled component licenses | Voronoi and spatial algorithms | Python runtime |
| PyVista | 0.48.4 | MIT | Mesh construction, validation and export | Python runtime |
| VTK | 9.6.2 | BSD-3-Clause | Native meshing and geometry filters | Python runtime |
| psutil | Not installed | N/A | Optional memory metrics fallback | Not distributed by this checkpoint |

Python runtime requirements are direct dependencies. Their supporting packages, including
Matplotlib, Pillow, Pooch, Requests, Cyclopts and Rich, are transitive runtime dependencies and
are listed individually in the SBOM.

Full license texts remain available in installed package metadata and license files:

- Node: each package directory under `node_modules` and its registry source.
- Python: each distribution's `.dist-info` metadata and license files in the virtual environment.

Before distributing a packaged desktop build, regenerate the SBOM in the exact packaging
environment and include all license notices required by bundled binary wheels, especially VTK,
NumPy and SciPy.
