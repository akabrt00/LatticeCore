# LatticeCore

Lokální prototyp aplikace pro bakalářskou práci zaměřený na Voronoi lattice
struktury pro STL modely a 3D tisk.

## Cíl

LatticeCore má umožnit nahrát STL model, zobrazit ho v lokálním 3D náhledu,
vygenerovat Voronoi síť a exportovat vzniklou lattice geometrii. Cílový postup
je nejdřív vytvořit Voronoi tessellaci a potom ji oříznout tvarem STL modelu.

## Aktuální funkce

- import STL souboru,
- ukázková testovací kostka,
- 3D náhled přes Three.js,
- Voronoi-only povrchový lattice náhled,
- experimentální Voronoi-like objemový lattice náhled,
- parametry: počet buněk, odsazení povrchu, průměr prutů, spojování hran a
  náhodnost buněk,
- export aktuálně upraveného STL,
- export povrchového i objemového náhledu do STL.

## Stav objemového režimu

Objemový režim je zatím prototyp. U ukázkové kostky a válce se vnitřní body
ořezávají podle tvaru, ale pro obecné STL je další milník robustní algoritmus:
Voronoi tessellace v prostoru, kontrola bodů/hran uvnitř STL a ořez mimo model.
Další poznámky jsou v [docs/voronator-reference-notes.md](docs/voronator-reference-notes.md).

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
