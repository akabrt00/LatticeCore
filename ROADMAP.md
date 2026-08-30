# LatticeCore roadmap

## Dokončeno

- lokální Three.js aplikace s importem STL a OBJ,
- parametrická kostka a válec,
- 3D Voronoi 1-skeleton a ořez podle boxu i obecného uzavřeného meshe,
- povrchově konformní Voronoi síť,
- connectory mezi povrchem a vnitřkem,
- filtrace krátkých prutů a slučování blízkých uzlů,
- implicitní watertight union a validace výsledného meshe,
- persistentní Python worker, FIFO fronta, SSE, zrušení a zotavení po pádu,
- disková a paměťová cache,
- solver relativní hustoty a dávkové exporty,
- diagnostické vrstvy a experimentální kontrola tisknutelnosti,
- clean-room testy, bezpečnostní audit a dokumentace architektury.

## Aktuální priorita

1. Ověřit tisknutelnost referenční kostky a několika obecných STL ve sliceru.
2. Porovnat geometrické parametry exportu s reálně vytištěnými vzorky.
3. Změřit čas výpočtu, spotřebu paměti, výslednou hustotu a odchylku rozměrů.
4. Stabilizovat automatické doplňování samonosných prutů podle vrstev.
5. Připravit reprodukovatelnou sadu parametrů a vzorků pro bakalářskou práci.

## Následující vývoj

### Geometrická robustnost

- adaptivní hustota seedů podle lokální tloušťky a zakřivení,
- robustnější napojování povrchu na objem u tenkých a konkávních oblastí,
- rychlejší prostorový index pro velké importované modely,
- volitelná oprava drobných děr a non-manifold vstupů s jasným reportem změn.

### 3D tisk

- validace po vrstvách nad finální exportní geometrií,
- lepší hledání kotev podpůrných prutů a iterativní kontrola po opravě,
- profily pro FDM a SLA/MSLA,
- export orientace a parametrů pro dokumentaci experimentu.

### Výzkumné vyhodnocení

- sada referenčních těles a verzovaných baseline,
- automatizované tabulky hustoty, hmotnosti a doby výpočtu,
- porovnání simulované a naměřené mechanické odezvy,
- dokumentované limity Voronoi aproximace na povrchu.

Další typy struktur, například gyroid nebo hexagonální lattice, nejsou prioritou, dokud nebude
Voronoi pipeline spolehlivě ověřena tiskem a mechanickými zkouškami.
