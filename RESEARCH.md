# Rešerše: lokální STL aplikace pro bakalářku

## Směr projektu

Cíl pro první verzi je lokální aplikace na PC: nahrát STL, zobrazit model,
aplikovat procedurální povrchový vzor, exportovat STL a připravit půdu pro
experimentální objemové struktury.

## Užitečné GitHub projekty a knihovny

### CNCKitchen/stlTexturizer

- GitHub: <https://github.com/CNCKitchen/stlTexturizer>
- Webová ukázka: <https://bumpmesh.com/>
- Hodí se jako referenční projekt pro povrchovou texturizaci STL.
- Pozor na licenci AGPL-3.0. Pro osobní a školní experiment je to menší
  problém, ale pro uzavřený komerční nástroj by bylo lepší psát vlastní kód.

### three.js

- GitHub: <https://github.com/mrdoob/three.js>
- Základ pro lokální 3D náhled, STLLoader, STLExporter a orbit ovládání.
- Výhoda pro bakalářku: dobře se vysvětluje, výsledek je vizuálně názorný.

### gkjohnson/three-mesh-bvh a three-bvh-csg

- three-mesh-bvh: <https://github.com/gkjohnson/three-mesh-bvh>
- three-bvh-csg: <https://github.com/gkjohnson/three-bvh-csg>
- Kandidát pro pozdější boolean operace nad mesh geometrií.
- Užitečné, až budeme chtít z povrchu nebo vnitřních buněk dělat skutečnou
  tisknutelnou geometrii.

### elalish/manifold

- GitHub: <https://github.com/elalish/manifold>
- Robustní geometrické boolean operace a mesh zpracování.
- Velmi zajímavé pro objemový režim, protože výstup musí být vodotěsný STL.

### trimesh

- GitHub: <https://github.com/mikedh/trimesh>
- Python knihovna pro načítání, analýzu a export meshů.
- Dobrá pro školní ověřování: kontrola watertight, počty ploch, objem,
  opravy jednoduchých mesh problémů.

### OpenJSCAD

- GitHub: <https://github.com/jscad/OpenJSCAD.org>
- Parametrické modelování v JavaScriptu.
- Může být užitečné pro generování testovacích primitiv a jednoduchých
  lattice struktur, ale pro import libovolného STL bych ho nebral jako hlavní
  základ.

## Doporučená architektura

1. `Three.js` pro lokální UI, náhled, import a export STL.
2. Samostatná povrchová Voronoi/lattice síť nad povrchem modelu, bez
   destruktivní deformace původního STL.
3. Experimentální objemový náhled jako kombinace povrchové sítě a vnitřní
   trubičkové lattice výplně.
4. Později přidat `manifold` nebo `trimesh` pro skutečný objemový export.

## Navržené fáze

1. Plošný režim:
   - Voronoi, hexagon, gyroid, noise.
   - Deformace podél normál.
   - Export STL.

2. Ověření:
   - otevřít export ve sliceru,
   - porovnat trojúhelníky a rozměry,
   - popsat limity deformace.

3. Objemový režim:
   - nejdřív trubičková síť pro kostku a kvádr,
   - pak generování trubiček/lattice pro kvádr,
   - nakonec boolean průnik s nahraným STL.

## Rizika

- STL model nemusí být vodotěsný.
- Povrchová deformace může vytvořit samo-průniky u ostrých hran.
- Skutečné objemové Voronoi pro libovolné STL je výrazně těžší než vizuální
  náhled.
- Export použitelný pro tisk musí být vždy ověřen ve sliceru.
