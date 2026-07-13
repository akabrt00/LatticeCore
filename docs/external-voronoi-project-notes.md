# External Voronoi project notes

Poznamky z rychleho pruzkumu projektu:

- Rolphs/Voronoi-Maker
- jsc723/voronoi-remesh
- jimmyland/voro

Cil nebyl kopirovat kod, ale najit principy, ktere muzou posunout
LatticeCore bez rozbiti aktualniho generatoru.

## Shrnutí

Aktualni smer LatticeCore je dobry: samostatna povrchova sit, vnitrni lattice,
prechodove connector pruty a nasledna topologicka optimalizace kratkych prutu.
Po testu na Benchy uz to zacina odpovidat cilovemu vzhledu.

Nejvetsi dalsi zlepseni neni pridat dalsi nahodne spojky, ale zlepsit:

- rozmisteni seed bodu,
- umisteni sloucenych uzlu,
- kontrolu shell / transition vrstvy,
- pozdeji realne 3D Voronoi bunky.

## Rolphs/Voronoi-Maker

Repo: https://github.com/Rolphs/Voronoi-Maker

Projekt je spis koncept a skeleton nez hotovy robustni generator. Dulezite pro
nas jsou hlavne pojmy:

- `surface` rezim,
- `radial` rezim,
- `multicenter` rezim,
- `shell thickness`.

### Co se hodi pro LatticeCore

Nejuzitecnejsi je zavest jasny parametr "tloustka plastove / prechodove
vrstvy". Ted mame povrchovou sit a vnitrek propojeny heuristikou. Pro
bakalarskou praci bude lepsi popsat to jako:

1. povrchova Voronoi vrstva,
2. vnitrni objemova lattice sit,
3. prechodova vrstva mezi povrchem a objemem.

To je srozumitelnejsi nez tvrdit, ze jde o jeden dokonaly matematicky Voronoi
objem.

## jsc723/voronoi-remesh

Repo: https://github.com/jsc723/voronoi-remesh

Tohle neni lattice generator. Je to remeshing pres clustery trojuhelniku a
Discrete Voronoi Diagram myslenku. Pro nas je ale velmi cenny princip:

- nebrat reprezentativni bod clusteru jako obycejny prumer,
- vybirat ho podle geometricke chyby,
- pouzit Quadric Error Metric, pokud je dostupna informace o okolnich plochach.

### Co se hodi pro LatticeCore

Nase soucasne slucovani kratkych prutu dava novy uzel do medianu. To je lepsi
nez mazani, ale porad je to hruba heuristika.

Dalsi bezpecny krok:

- pri slouceni uzlu brat v uvahu okolni pruty,
- preferovat pozici, ktera minimalne meni smer sousednich prutu,
- u povrchovych uzlu promítnout vysledek zpet k povrchu nebo do shell vrstvy,
- u vnitnich uzlu drzet vysledek uvnitr STL.

Pracovni nazev: `smart node merge`.

## jimmyland/voro

Repo: https://github.com/jimmyland/voro

Tohle je nejvetsi budouci skok. Projekt pouziva Voro++ pres Emscripten a pracuje
se skutecnymi 3D Voronoi bunkami. Nejde jen o aproximovane spojovani bodu.

### Co se hodi pro LatticeCore

Dlouhodobe by to byl lepsi zaklad pro "opravdovou" objemovou Voronoi strukturu:

- seed body uvnitr objemu,
- skutecne 3D Voronoi bunky,
- extrakce hran/stěn bunek,
- mazani nebo upravy bunek,
- moznost casem generovat nejen pruty, ale i bunecne steny.

### Proc to nedelat hned

Integrace Voro++/WASM nebo Python wrapperu by byla velka zmena. Ted uz mame
generator, ktery zacina fungovat na Benchy. Je lepsi aktualni pipeline stabilizovat
a Voro++ nechat jako samostatnou experimentální etapu.

## Doporučený postup pro další práci

### Kratkodobe

1. Zachovat soucasnou Python pipeline.
2. Doladit `smart node merge`.
3. Pridat parametr pro agresivitu slucovani kratkych prutu.
4. Pridat lepsi rozmisteni seed bodu, idealne Poisson disk / farthest point
   sampling misto ciste nahodnych bodu.
5. Logovat metriky:
   - pocet vnitrnich hran,
   - pocet povrchovych hran,
   - pocet connector hran,
   - pocet sloucenych kratkych hran,
   - pocet odstraněnych odpojenych ostrovu.

### Strednedobe

1. Udelat explicitni `shell thickness` / `transition thickness` parametr.
2. Rozdelit generator na jasne faze:
   - sample,
   - volume graph,
   - surface graph,
   - transition graph,
   - cleanup,
   - mesh export.
3. Pridat automaticky test na Benchy a kostku, ktery kontroluje zakladni metriky.

### Dlouhodobe

1. Samostatne otestovat Voro++ / VoroPy / pyvoro podobny pristup.
2. Porovnat vysledky se soucasnou aproximaci.
3. Pokud bude vysledek vyrazne lepsi, udelat novy backend `true-voronoi`.

## Prakticky závěr

Ted jsme na dobre ceste. Nejcennejsi pristi krok neni prepsat vse na Voro++,
ale udelat chytrejsi optimalizaci uzlu a seed bodu. To primo resi aktualni
vizualni problemy bez rizika, ze rozbijeme fungujici Benchy.
