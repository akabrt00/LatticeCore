# LatticeCore

Lokální prototyp aplikace pro bakalářskou práci zaměřený na procedurální
úpravy STL modelů pro 3D tisk.

## Cíl

LatticeCore má umožnit nahrát STL model, zobrazit ho v lokálním 3D náhledu,
aplikovat povrchové struktury a exportovat upravené STL. Objemové struktury
jsou zatím vedené jako experimentální část, která se bude rozšiřovat postupně.

## Aktuální funkce

- import STL souboru,
- ukázková testovací kostka,
- 3D náhled přes Three.js,
- povrchové vzory Voronoi, hexagon, gyroid a organický noise,
- nastavení velikosti buněk, hloubky, tloušťky hran, hustoty a vyhlazení,
- export aktuálně upraveného STL,
- experimentální objemový lattice náhled z válcových trubek,
- export povrchového i objemového náhledu do STL.

## Stav objemového režimu

Objemový režim teď vytváří trubičkovou prostorovou kostru v hranicích modelu.
U ukázkové kostky se tím blíží fyzickému Voronoi/lattice vzorku. Pro obecné
STL modely je to zatím bounding-box prototyp; další krok bude ořezání lattice
struktury podle skutečného tvaru modelu pomocí robustních boolean operací.

## Spuštění

V kořenové složce projektu:

```powershell
npm install
npm run dev
```

Potom otevřít:

```text
http://127.0.0.1:5173/
```

Projekt používá Vite a lokální závislost `three`, takže aplikace už není
závislá na CDN importech v prohlížeči.

## Build

```powershell
npm run build
```
