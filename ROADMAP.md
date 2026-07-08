# LatticeCore roadmap

Roadmapa je rozdelená tak, aby byl projekt pouzitelný jako bakalárská práce
a soucasne zustal realisticky dokoncitelný.

## Etapa 1: Lokální základ aplikace

Stav: první verze hotová.

- Lokální spustení bez online backendu.
- Import STL.
- 3D náhled modelu.
- Orbit kamera.
- Základní statistiky modelu.
- Export STL.
- Základní README a rešerše.

## Etapa 2: Voronoi povrchová síť

Stav: první prototyp hotový, potrebuje ladit kvalitu výstupu.

- Povrchová Voronoi/lattice síť bez destruktivní deformace původního STL.
- Parametry: počet buněk, odsazení povrchu, průměr prutů, spojování hran,
  náhodnost buněk.
- Export samostatné povrchové lattice geometrie.
- Otestování výstupu ve sliceru.
- Dalsí vzory jako hex/gyroid neřešit, dokud nebude Voronoi režim stabilní.

## Etapa 3: Voronoi objemový lattice pro jednoduché tvary

Stav: prototyp trubickové lattice kostry hotový.

- Kostka a kvádr jako hlavní testovací modely.
- Voronoi-like prostorová struktura ze seed bodů.
- Rychlý tvarový odhad pro válec a kvádr, aby se lattice nevytvářel jen jako
  bounding box.
- Parametry počtu buněk, spojování hran a průměru prutů.
- Export objemové lattice struktury do STL.
- Otestování exportu ve sliceru.
- Zhodnocení tisknutelnosti.

## Etapa 4: Skutečná Voronoi tessellace a ořez podle STL

Stav: plánovaná výzkumná cást.

- Vytvoření Voronoi tessellace v bounding boxu modelu.
- Detekce bodů, hran a strutů uvnitř STL.
- Odstranění částí mimo model.
- Napojení vnitřní lattice na povrchovou Voronoi síť.
- Vyhodnocení robustnosti na jednoduchých i slozitejsích STL.

## Etapa 5: Robustnost a vyhodnocení

Stav: plánováno.

- Testovací sada STL modelu.
- Pocet trojúhelníku pred a po úprave.
- Velikost exportovaných souboru.
- Cas generování.
- Kontrola vodotesnosti a tisknutelnosti.
- Screenshoty z aplikace a sliceru.
- Popis omezení algoritmu.

## Etapa 6: Dokoncení pro bakalárskou práci

Stav: plánováno.

- Offline knihovny místo CDN.
- Stabilizace UI.
- Ukázkové modely.
- Kapitola návrhu aplikace.
- Kapitola implementace algoritmu.
- Kapitola testování.
- Záver, omezení a moznosti rozsírení.

## Nejblizsí praktické kroky

1. Soustredit projekt pouze na Voronoi.
2. Zlepsit povrchovou Voronoi sit podle principu Voronatoru.
3. Vytvorit izolovany experiment 3D Voronoi v kvadru podle TUL workflow.
4. Orezat 3D Voronoi hrany podle jednoducheho tvaru: kostka, valec.
5. Pridat filtr kratkych struts.
6. Teprve potom ladit obecne STL a slicer test.
