# LatticeCore Python MVP

Minimal Python prototype for generating a 3D Voronoi tube lattice inside an
implicit sphere with a Voronoi-like surface casing.

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
exports\voronoi_sphere_with_shell.stl
```

## Parameters

```powershell
python python_app\voronoi_sphere_lines_mvp.py --points 120 --tube-radius 0.02 --random-seed 10
```

Surface casing controls:

```powershell
python python_app\voronoi_sphere_lines_mvp.py --surface-points 80 --surface-tube-radius 0.025
python python_app\voronoi_sphere_lines_mvp.py --no-shell
```

## What It Does

- creates an implicit sphere centered at `[0, 0, 0]` with radius `1`;
- generates random seed points inside the sphere;
- computes a 3D Voronoi diagram with `scipy.spatial.Voronoi`;
- skips infinite ridges containing `-1`;
- keeps only edges whose endpoints are inside the sphere;
- converts edges to PyVista tube meshes;
- creates a spherical Voronoi-like casing from tubes on the sphere surface;
- exports the combined inner tubes + surface casing mesh to STL;
- optionally shows seed points and original line edges with `--debug`.

The surface casing uses `scipy.spatial.SphericalVoronoi`. It is visually close
to a Voronoi shell, but it is not yet boolean-unioned with the inner struts into
a perfect industrial manifold.
