# TUL Voronoi method notes

Zdroj: Boualleg, Cirkl, Weeger, *Computational design of 3D printed flexible
Voronoi lattices*, Progress in Additive Manufacturing, 2025.

## Co je pro LatticeCore dulezite

Tento postup potvrzuje, ze nas puvodni pristup byl spatny: spravna lattice
geometrie se nema kreslit jako nahodne valce na existujici STL. Nejdriv se musi
vytvorit 3D Voronoi rozdeleni objemu a az z jeho hran se maji generovat struts.

## Workflow z clanku

1. Vytvorit zakladni objem.
   - V clanku pouzivaji hexahedralni objem 30 x 30 x 24 mm.
   - Pro nas to v prvni fazi znamena kostka/kvadr jako testovaci tvar.

2. Vygenerovat nahodne seed body `(x, y, z)`.
   - Hustota se ridi poctem seedu.
   - V clanku uvadi napr. 122 bunek pro vyssi hustotu a 80 bunek pro nizsi
     hustotu.

3. Rozdelit objem pomoci 3D Voronoi tessellation.
   - V MATLABu pouzili 3D Voronoi funkci.
   - Hranice sousedicich bunek jsou plochy stejne vzdalenosti od seedu.
   - Hrany techto polyedrickych bunek se stanou zakladem pro lattice struts.

4. Kontrolovat hustotu.
   - Jestli neni dosazena pozadovana hustota, zmeni se pocet seedu.
   - To je dulezite: hustota neni jen vizualni slider, ale realny parametr
     geometrie.

5. Odstranit kratke struts.
   - V clanku odstranili struts kratsi nez 2 mm.
   - Kratke struts vytvari prekryvy, prilis tuhe oblasti a problemy pro FEA.
   - Pri odstraneni kratke hrany spojili koncove vrcholy do noveho bodu ve
     stredu.

6. Vytvorit 3D pevnou geometrii.
   - Hrany se premeni na valcove struts s definovanym prumerem.
   - Prumer struts je dalsi rizeny parametr hustoty.
   - V clanku pouzili napr. 0.7 mm, 1.0 mm a 1.3 mm.

7. Sjednotit struts a opravit spoje.
   - Pri importu do FEA byly struts nejdrive disjointed.
   - Pouzili Unite Solids.
   - Do uzlu pridali sfery, aby se odstranily mezery a vznikl hladky prechod
     mezi propojenymi struts.

8. Export a tisk.
   - Az po validni objemove reprezentaci exportovali STL.
   - V clanku nasledovalo slicovani a tisk na MSLA/SLA.

## Co z toho plyne pro nas

### Nedelat

- nedeformovat puvodni STL vrcholy jako nahradu za Voronoi,
- negenerovat hrany nahodne podle bounding boxu,
- nepovolovat export, dokud nemame spojitou validni geometrii,
- netvarit se, ze line segments nebo samostatne valce jsou hotovy model.

### Delat

- zacit izolovanym experimentem nad kvadrem,
- implementovat skutecne 3D Voronoi cells,
- extrahovat hrany bunek,
- odstranit kratke struts,
- vytvorit valce + sfericke uzly,
- az potom resit STL export.

## Navrh etap podle clanku

### Experiment A: Voronoi volume in box

Cil:

- vstup: box 30 x 30 x 24 mm,
- seed count: 80 nebo 122,
- vystup: pouze cary Voronoi hran v nahledu,
- bez STL exportu.

### Experiment B: Strut filtering

Cil:

- spocitat delky hran,
- vykreslit histogram delky struts,
- odstranit hrany kratsi nez nastavena mez,
- spojit kratke vrcholy do midpointu.

### Experiment C: Solid struts

Cil:

- vytvorit valce podle hran,
- pridat sfery v uzlech,
- sloucit nebo alespon korektne exportovat jako jeden objekt,
- testovat nejdriv pouze kostku.

### Experiment D: Relative density control

Cil:

- pocitat relativni hustotu `rho* = V_lattice / V_total`,
- menit pocet seedu a prumer struts,
- porovnat varianty napr. 80 bunek / 122 bunek a prumery 0.7, 1.0, 1.3 mm.

### Experiment E: Shape clipping

Cil:

- az po validaci kvadru zacit s obecným STL,
- generovat Voronoi uvnitr bounding volume,
- orezat strukturu skutecnym tvarem modelu,
- validovat jen na jednoduchych tvarech: valec, koule, jednoduchy kvadr.

## Dopad na LatticeCore

LatticeCore by se mel docasne chovat jako:

- STL viewer,
- parametricke UI,
- experiment launcher,
- dokumentacni a testovaci prostredi.

Samotny generativni algoritmus ma vznikat v izolovanych experimentech, ne
primo v hlavnim UI, dokud neni geometricky validni.
