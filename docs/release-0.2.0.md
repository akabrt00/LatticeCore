# LatticeCore 0.2.0 release verification

Date: 2026-08-28

## PASS

- 21 server and public-data contract tests.
- 125 Python geometry, worker, cache, density and imported-mesh tests.
- Geometry baseline checks stayed within their stored tolerances.
- Production Vite build completed successfully.
- Browser smoke: parametric model and imported torus rendered without console errors.
- Imported torus switched between volume and surface modes successfully.
- Final imported-torus job completed through the UI in 133.25 s: 92,172 triangles, one
  watertight edge-manifold component, 146 accepted surface-to-interior connectors and no
  boundary or non-manifold edges.
- Direct implicit API smoke completed in 22.21 s with exact 10 x 8 x 6 mm bounds and 47,868
  triangles in one watertight edge-manifold component.
- Five closed input components are preserved by default; strict and largest-only modes remain available.
- Worker health reported ready on the local development server.
- `npm audit --json` reported zero vulnerabilities.
- Installed tree contains PostCSS 8.5.25 and Nano ID 3.3.18.
- GitHub Actions performs a clean Node.js 24 and Python 3.13 verification on push and pull request.

## FAIL

- None in the release test scope.

## ACCEPTED RISK

- The production JavaScript entry chunk is about 582 kB before gzip. This affects startup performance,
  not geometry correctness or export integrity.
- VTK's NumPy adapter emits a deprecation warning with NumPy 2.5. The tested operations pass and the
  warning originates in the supported third-party dependency range.
- Fast export intentionally consists of overlapping primitives and need not be manifold. Printable
  output must use the final implicit watertight engine.
- Open or non-manifold imports cannot define an unambiguous volume. The UI now reports corrective
  guidance instead of silently producing a bounding-box lattice.
