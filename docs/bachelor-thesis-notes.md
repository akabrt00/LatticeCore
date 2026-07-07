# Poznámky k bakalárské práci

## Pracovní název

LatticeCore: lokální aplikace pro procedurální tvorbu povrchových a objemových
struktur v STL modelech pro 3D tisk.

## Hlavní cíl

Cílem je navrhnout a implementovat lokální aplikaci, která umozní nacíst STL
model, aplikovat na nej povrchovou nebo objemovou procedurální strukturu a
vyexportovat upravený model pro dalsí zpracování ve sliceru.

## Minimální obhajitelný výstup

- Funkcní lokální aplikace.
- Import a export STL.
- Povrchové struktury s nastavitelnými parametry.
- Objemová lattice struktura pro jednoduché tvary.
- Testy exportu ve sliceru.
- Popis algoritmu, omezení a mozností dalsího vývoje.

## Výzkumná cást

Nejnárocnejsí cástí je objemová struktura uvnitr obecného STL modelu. Pro
bakalárskou práci je rozumné ji rozdelit na:

- prototyp na kostce a kvádru,
- detekci hran uvnitr modelu,
- orez podle povrchu STL,
- validaci tisknutelnosti.

## Dulezitá omezení

- STL modely nemusí být vodotesné.
- Povrchová deformace muze u ostrých hran vytvorit samo-pruniky.
- Skutecný Voronoi/lattice uvnitr libovolného STL vyzaduje robustní geometrické
  operace.
- Výstup je nutné kontrolovat ve sliceru, ne jen v náhledu aplikace.
