# LatticeCore Python MVP

Minimal Python prototype for generating a 3D Voronoi tube lattice inside an
implicit body with a Voronoi-like surface casing. The default body is a box,
because it matches the printed cube reference.

This is intentionally small: no GUI controls, no STL/OBJ import, no booleans.
The goal is to verify the core algorithm first.

## Install Dependencies

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python python_app\voronoi_sphere_lines_mvp.py --debug
```

Default STL output:

```text
exports\voronoi_lattice_with_surface.stl
```

## Parameters

```powershell
python python_app\voronoi_sphere_lines_mvp.py --shape box --points 120 --tube-radius 0.02 --random-seed 10
python python_app\voronoi_sphere_lines_mvp.py --shape sphere
```

Surface casing controls:

```powershell
python python_app\voronoi_sphere_lines_mvp.py --surface-points 80 --surface-tube-radius 0.025
python python_app\voronoi_sphere_lines_mvp.py --no-shell
```

Inner/surface connection controls:

```powershell
python python_app\voronoi_sphere_lines_mvp.py --connector-band 0.35 --connector-max-length 0.55
```

Joint/node controls:

```powershell
python python_app\voronoi_sphere_lines_mvp.py --node-radius-scale 1.0
python python_app\voronoi_sphere_lines_mvp.py --no-nodes
```

## What It Does

- creates an implicit box or sphere centered at `[0, 0, 0]`;
- generates random seed points inside the selected body;
- computes a 3D Voronoi diagram with `scipy.spatial.Voronoi`;
- skips infinite ridges containing `-1`;
- keeps only edges whose endpoints are inside the selected body;
- converts edges to PyVista tube meshes;
- creates a Voronoi-like casing from tubes on the body surface;
- connects near-boundary inner lattice endpoints to nearby surface nodes;
- adds small endpoint spheres at strut joints to reduce gaps in printed/exported geometry;
- exports the combined inner tubes + surface casing mesh to STL;
- optionally shows seed points and original line edges with `--debug`.

The sphere casing uses `scipy.spatial.SphericalVoronoi`. The box casing builds
2D Voronoi cells on each face, clips those cells to the square face boundary,
and adds a cube frame as outer struts. This is closer to a printed Voronoi cube:
each face is a clipped Voronoi network rather than a solid wall. It is not yet
boolean-unioned with the inner struts into a perfect industrial manifold.

For box bodies, connector struts are added between inner Voronoi endpoints near
the boundary and nearby nodes on the same surface face. Increase
`--connector-band` to catch more inner endpoints, or decrease
`--connector-max-length` to avoid long diagonal connections.

Endpoint spheres are enabled by default. Their radius is the local strut radius
multiplied by `--node-radius-scale`, so the default sphere diameter matches the
strut diameter.
