# LatticeCore Python MVP

Minimal Python prototype for generating a 3D Voronoi tube lattice inside an
implicit sphere.

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

## Parameters

```powershell
python python_app\voronoi_sphere_lines_mvp.py --points 120 --tube-radius 0.02 --random-seed 10
```

Shell / casing controls:

```powershell
python python_app\voronoi_sphere_lines_mvp.py --shell-thickness 0.04
python python_app\voronoi_sphere_lines_mvp.py --no-shell
```

## What It Does

- creates an implicit sphere centered at `[0, 0, 0]` with radius `1`;
- generates random seed points inside the sphere;
- computes a 3D Voronoi diagram with `scipy.spatial.Voronoi`;
- skips infinite ridges containing `-1`;
- keeps only edges whose endpoints are inside the sphere;
- converts edges to PyVista tube meshes;
- creates a simple spherical casing/shell around the structure;
- exports the combined tube + shell mesh to STL;
- optionally shows seed points and original line edges with `--debug`.

The shell is currently a simple hollow sphere surface pair merged with the tube
mesh. It is useful as an MVP casing, but it is not yet a boolean-unioned
watertight industrial part.
