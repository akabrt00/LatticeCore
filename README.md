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

Objemový režim teď kombinuje povrchovou Voronoi/lattice síť a rychlý tvarový
odhad vnitřní výplně. U kostky a válce se tím blíží fyzickému lattice vzorku
bez toho, aby se vše generovalo pouze jako bounding box. Pro obecné STL modely
je další krok robustní detekce hran uvnitř modelu pomocí přesnějších mesh nebo
boolean operací.

## Výkon náhledu

Přepočet lattice struktury je výpočetně náročnější než běžné zobrazení STL.
Slidery proto používají krátkou prodlevu: hodnota se změní okamžitě, ale nový
náhled se přepočítá až po zastavení tahu. To brání zbytečnému zamrzání UI při
rychlém nastavování parametrů.

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
