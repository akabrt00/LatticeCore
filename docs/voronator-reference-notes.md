# Voronator-style target workflow

Reference: <https://www.voronator.com/>

The target for LatticeCore surface mode is closer to Voronator than to a normal
STL texture displacement:

1. Generate Voronoi seed points.
2. Build a Voronoi-like cell network.
3. Convert selected cell borders/edges into printable struts.
4. Clip or trim the generated network by the STL model.
5. Export the generated lattice mesh, not a destructively deformed original STL.

Important UI lesson from Voronator:

- use clear controls such as number of holes/cells and strut/layer thickness;
- avoid ambiguous sliders such as "depth" when the mode is volumetric;
- distinguish preview geometry from printable manifold geometry;
- warn when a mode is only a plane/surface preview and not a watertight printable mesh.

Current LatticeCore status:

- The preview now uses cell count, strut diameter, edge linking, surface offset
  and randomness as the core controls.
- Surface and volume modes still use a nearest-neighbor Voronoi-like graph, not
  a mathematically exact 3D Voronoi tessellation.
- The next algorithm phase should replace nearest-neighbor edges with a real
  tessellation or a Delaunay/Voronoi library, then clip that result with the STL
  volume.
