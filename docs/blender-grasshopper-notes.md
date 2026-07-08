# Blender, Sverchok and Grasshopper notes

These tools are useful references for the LatticeCore bachelor thesis workflow:

- Blender can be used for STL inspection, mesh cleanup, booleans and export checks.
- Sverchok (<https://github.com/nortikin/sverchok>) adds node-based procedural
  geometry to Blender and is relevant for Voronoi and lattice experiments.
- Grasshopper/Rhino is strong for quick algorithm tests: seed points, 3D Voronoi,
  pipe/strut geometry, density tuning and boolean clipping.

LatticeCore should remain a standalone local app for the thesis prototype. Blender,
Sverchok and Grasshopper are best used as comparison and validation tools, not as
mandatory runtime dependencies.
