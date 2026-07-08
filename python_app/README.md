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

## What It Does

- creates an implicit sphere centered at `[0, 0, 0]` with radius `1`;
- generates random seed points inside the sphere;
- computes a 3D Voronoi diagram with `scipy.spatial.Voronoi`;
- skips infinite ridges containing `-1`;
- keeps only edges whose endpoints are inside the sphere;
- converts edges to PyVista tube meshes;
- exports the tube mesh to STL;
- optionally shows seed points and original line edges with `--debug`.
