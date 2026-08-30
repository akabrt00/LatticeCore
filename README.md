# LatticeCore

Lokální aplikace pro generování povrchových a objemových 3D Voronoi lattice struktur. Projekt
vzniká pro bakalářskou práci zaměřenou na 3D tisk strukturních materiálů a hodnocení jejich
mechanické odezvy.

LatticeCore pracuje offline na jednom počítači. Webové rozhraní zajišťuje Three.js a Vite,
geometrické výpočty běží v persistentním Python workeru nad NumPy, SciPy, PyVista a VTK.

## Co aplikace umí

- import uzavřených STL a OBJ modelů,
- parametrickou kostku a válec pro rychlé experimenty,
- skutečnou 3D Voronoi kostru oříznutou objemem vstupního modelu,
- povrchově konformní Voronoi síť kopírující tvar modelu,
- propojení povrchové a vnitřní sítě pomocí connectorů,
- odstranění krátkých prutů a sloučení blízkých uzlů,
- rychlý pracovní náhled z překrývajících se primitiv,
- finální watertight implicitní mesh pro 3D tisk,
- kontrolu manifoldnosti, hranic, komponent a objemu,
- řízení relativní hustoty a dávkové generování více hustot,
- cache mezivýsledků, frontu úloh, průběh přes SSE a zrušení výpočtu,
- export STL, JSON metadat, CSV průběhu a ZIP dávkových výsledků.

## Rychlý start

Požadavky:

- Node.js 20.19 nebo novější,
- Python 3.11 nebo novější,
- Windows PowerShell pro připravené pomocné skripty.

```powershell
git clone https://github.com/akabrt00/LatticeCore.git
cd LatticeCore
npm install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
npm run dev
```

Aplikace se otevře na [http://127.0.0.1:5173/](http://127.0.0.1:5173/).

Alternativně lze na Windows použít:

```powershell
.\scripts\start-dev.ps1
```

## Doporučený pracovní postup

1. Nahraj uzavřený STL nebo OBJ model.
2. U vícesložkového modelu ponech výchozí volbu `Použít všechny uzavřené`, případně vyber
   `Ponechat největší`.
3. Pro rychlé ladění nech `Rychlý export – samostatné pruty`.
4. Nastav počet seedů, průměr prutů a minimální délku prutu.
5. Pro tisk přepni na `Finální watertight mesh` a nejdřív použij pracovní kvalitu.
6. Zkontroluj panel validace a exportuj STL až po úspěšném dokončení úlohy.

STL ani OBJ spolehlivě neukládají jednotky. LatticeCore interpretuje souřadnice jako milimetry
a nabízí explicitní měřítko importu.

## Režimy geometrie

### Povrchový režim

Vzorkuje povrch vstupního meshe, vytvoří aproximovanou povrchovou Voronoi síť, vyhladí ji a
umístí ji na povrch nebo s odsazením dovnitř. Výstup tvoří pruty a kulové uzly, nikoli plný plášť.

### Objemový režim

Vygeneruje seed body uvnitř objemu, vypočítá 3D Voronoi diagram, ořízne jeho hrany podle domény a
spojí vnitřní kostru s povrchovou sítí. U konkávních modelů může jedna Voronoi hrana vytvořit více
oddělených intervalů uvnitř tělesa.

### Mesh engine

- `legacy-primitives`: rychlý diagnostický výstup z válců a koulí; nemusí být manifold,
- `implicit-union`: kapsle a uzly jsou spojeny do jednoho pole vzdálenosti a oříznuty vstupní
  doménou; výsledný mesh musí projít watertight a edge-manifold validací.

## Testy

Kompletní kontrola serveru, Python geometrie a produkčního buildu:

```powershell
npm run test:all
```

Samostatné části:

```powershell
npm run test:server
npm run test:python
npm run build
npm audit
```

Aktuální release checkpoint zahrnuje 123 Python testů, serverové testy fronty, zotavení workeru,
retence výsledků a sanitizace veřejných výstupů. Podrobnosti jsou v
[docs/release-checkpoint-report.md](docs/release-checkpoint-report.md).

## Dokumentace

- [Architektura](docs/architecture.md)
- [Vývojové prostředí](docs/development-setup.md)
- [Řešení problémů](docs/troubleshooting.md)
- [Persistentní worker](docs/persistent-worker-report.md)
- [Clean-room validace](docs/clean-room-validation.md)
- [Bezpečnostní audit](docs/security/security-audit-report.md)
- [Poznámky k externím Voronoi projektům](docs/external-voronoi-project-notes.md)
- [Roadmapa](ROADMAP.md)

## Známá omezení

- vstupní objem musí být uzavřený a edge-manifold,
- rychlý engine není určen jako finální tiskový mesh,
- VTK FlyingEdges nelze přerušit uprostřed nativního volání,
- finální výpočet složitých modelů může vyžadovat nižší voxelové rozlišení nebo více RAM,
- automatická kontrola tisknutelnosti je experimentální a nenahrazuje kontrolu ve sliceru.

Projekt je aktivní výzkumný prototyp. Před mechanickými zkouškami vždy ověř výsledný STL ve
sliceru a zaznamenej použité parametry z JSON metadat.
