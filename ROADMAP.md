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

## Etapa 2: Povrchové struktury

Stav: první prototyp hotový, potrebuje ladit kvalitu výstupu.

- Voronoi povrchový reliéf.
- Povrchová Voronoi/lattice síť bez destruktivní deformace původního STL.
- Hexagonální vzor.
- Gyroid / organický vzor.
- Parametry: velikost bunek, hloubka, tloustka hran, hustota, vyhlazení.
- Export upraveného povrchového STL.
- Otestování výstupu ve sliceru.

## Etapa 3: Objemový lattice pro jednoduché tvary

Stav: prototyp trubickové lattice kostry hotový.

- Kostka a kvádr jako hlavní testovací modely.
- Trubicková prostorová struktura.
- Rychlý tvarový odhad pro válec a kvádr, aby se lattice nevytvářel jen jako
  bounding box.
- Parametry hustoty a prumeru trubek.
- Export objemové lattice struktury do STL.
- Otestování exportu ve sliceru.
- Zhodnocení tisknutelnosti.

## Etapa 4: Orez lattice podle skutecného STL

Stav: plánovaná výzkumná cást.

- Vytvorení lattice ve bounding boxu modelu.
- Nahrazení rychlého tvarového odhadu robustní detekcí bodu a hran uvnitr STL.
- Odstranení cástí mimo model.
- Napojení lattice na povrch modelu.
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

1. Udelat první commit aktuálního prototypu.
2. Vyexportovat lattice kostku.
3. Otevrit export v PrusaSliceru nebo Cura.
4. Podle výsledku upravit tloustku trubek a hustotu.
5. Zacít navrhovat orez lattice podle skutecného tvaru STL.
