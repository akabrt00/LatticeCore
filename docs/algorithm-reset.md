# Algorithm reset

Soucasny rychly generator byl pozastaveny, protoze nevytvarel korektni
Voronoi/lattice geometrii. Pro bakalarskou praci je lepsi mit poctive popsany
problem nez exportovat STL, ktere vypada jako sit, ale geometricky je spatne.

## Proc byl prototyp spatne

- Plosny rezim deformoval puvodni vrcholy STL, takze mohl rozbit mesh.
- Objemovy rezim byl aproximace podle hranic modelu, ne skutecna vnitrni
  Voronoi struktura.
- Povrchova a vnitrni sit nebyly jeden konzistentni algoritmus.
- Export mohl vytvorit netisknutelnou nebo nesmyslnou geometrii.

## Spravny algoritmicky smer

1. Nacist STL a overit zakladni vlastnosti:
   - bounding box,
   - pocet trojuhelniku,
   - orientace normal,
   - jestli je model pravdepodobne vodotesny.

2. Vytvorit body na povrchu:
   - rovnomerne vzorkovani po plose trojuhelniku,
   - idealne Poisson disk sampling, aby body nebyly shluknute.

3. Vytvorit povrchovou Voronoi sit:
   - nedeformovat puvodni mesh,
   - vytvorit nove hrany/bunky na povrchu,
   - z hran vytvorit trubicky nebo pasy s definovanou tloustkou.

4. Vytvorit body uvnitr modelu:
   - pouze uvnitr skutecneho STL,
   - ne v celem bounding boxu,
   - pouzit robustni point-in-mesh test nebo voxelovou reprezentaci.

5. Vytvorit objemovou sit:
   - propojit vnitrni body do Voronoi/Delaunay/lattice struktury,
   - oriznout vse mimo STL,
   - napojit vnitrni sit na povrchovou sit.

6. Export:
   - sloucit trubicky do jedne geometrie,
   - validovat manifold/watertight stav,
   - otestovat ve sliceru.

## Doporucena technicka cesta

Kratkodobe:

- nechat LatticeCore jako viewer a UI pro parametry,
- generovani resit oddelene v experimentu,
- nejdriv jen kostka a valec,
- export povolit az po slicer testu.

Dlouhodobe:

- zvazit Python modul s `trimesh` pro robustni mesh analyzu,
- nebo WASM/JS knihovnu typu `manifold` pro boolean operace,
- az potom integrovat vysledek zpet do UI.

## Nejblizsi implementacni ukol

Vytvorit izolovany experiment:

```text
experiments/surface-voronoi-cube
```

Cil experimentu:

- vstup: jednoducha kostka,
- vystup: pouze povrchova Voronoi sit,
- zadny import obecneho STL,
- zadny objem,
- zadny export, dokud nahled nebude geometricky davat smysl.

## Aktualizace podle TUL Voronoi workflow

Po prostudovani prace *Computational design of 3D printed flexible Voronoi
lattices* je vhodne zmenit prvni experiment: nez povrchovou sit na libovolnem
STL, je lepsi zacit presne jako v clanku, tedy 3D Voronoi uvnitr jednoducheho
kvadru. Duvod je, ze clanek jasne definuje validni postup:

- vytvorit zakladni objem,
- vygenerovat seed body,
- provest 3D Voronoi tessellation,
- extrahovat hrany bunek,
- odstranit kratke struts,
- vytvorit valce a sfericke uzly,
- az potom exportovat validni objemovou geometrii.

Podrobnejsi rozpad je v `docs/tul-voronoi-method-notes.md`.
