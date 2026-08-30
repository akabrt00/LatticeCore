# Persistent Python worker MVP

## Release hardening update

The manager records exit code/signal, preserves queued jobs, marks interrupted work
`worker-lost`, and restarts with a bounded 1/2/5 second policy. Heartbeats include phase and
separated process/Python/estimated memory values. Voxel allocation has a configurable hard
preflight. Jobs, public results and inactive RAM sessions have independent retention.

Operational endpoints:

- `GET /api/health`
- `GET /api/lattice-worker/status`
- `GET /api/lattice-worker/memory-sessions`
- `POST /api/lattice-worker/status?scope=unused|all`
- `POST /api/lattice-jobs/:id/retry`

Datum mereni: 2026-07-30

## Architektura

Vite pri startu vytvori jedinou instanci `LatticeWorkerManager`. Manager spusti
`python_app/lattice_worker.py`, pocka na `worker-ready` handshake a teprve potom
odesila ulohy. Komunikace je NDJSON pres stdin/stdout, jeden JSON objekt na radek.
Bezna diagnostika Pythonu jde pouze na stderr.

Podporovane prikazy protokolu verze 1 jsou `ping`, `run-job`, `cancel-job`,
`clear-memory-cache`, `get-status` a `shutdown`. Podporovane job typy jsou
`generate-direct`, `solve-density-single` a `solve-density-batch`.

Handshake obsahuje verzi workeru, PID, capabilities, cas startu a cas importu
knihoven. Pri neocekavanem padu manager provede nejvyse jeden automaticky restart.
Pri vypnuti Vite odesle `shutdown`.

## Fronta a SSE

Manager drzi FIFO frontu a spousti nejvyse jednu tezkou ulohu. Stav jobu je
`queued`, `running`, `cancelling`, `cancelled`, `completed`, `failed` nebo
`worker-lost`. Poslednich 500 udalosti zustava v pameti.

`GET /api/lattice-jobs/:jobId/events` posle aktualni stav, historii a nove udalosti.
Keepalive se odesila po 12 sekundach. Po terminalnim stavu se stream uzavre.
Interni souborove cesty se pred SSE a JSON odpovedi nahrazuji verejnymi asset URL.

## RAM topology session

Session drzi kompatibilni `TriangleMeshDomain`, jeho `vtkStaticCellLocator` a
topologicka pole nactena nebo vytvorena pres jednotlive cache levels. Diskova
NPZ/JSON cache zustava druhou urovni cache.

Session key obsahuje hash vstupu, import a component mode, seed parametry,
boundary offset, clipping, conformal/open-volume rezim a surface sampling,
placement a smoothing. Neobsahuje prumer prutu, node radius, voxel size,
cilovou hustotu ani hustotu materialu.

LRU ma vychozi limit 3 session a idle limit 30 minut. Aktivni session se
nevyrazuje. `clear-memory-cache` uvolni reference pouze neaktivnich session.

## Cancellation a progress

`CancellationToken` se kontroluje mezi hlavnimi fazemi, density evaluacemi,
batch cili, pri rejection samplingu, po blocich segment clippingu, po blocich
SDF a pred exporty. Zruseni vyvola rizeny `JobCancelledError`; rozpracovane
vystupy se odstrani a nevznikne vysledek.

SDF progress je skutecny pomer `completedBlocks / totalBlocks` a je omezen
priblizne na 8 udalosti za sekundu. VTK contour/flying-edges a nektere PyVista
filtry nelze prerusit uvnitr volani. V takovem pripade job zustane
`cancelling` a token se zkontroluje ihned po navratu z VTK.

## Overeni

- Python: 116 testu, vsechny prosly.
- Node worker manager: 6 testu, vsechny prosly.
- `npm.cmd run build`: proslo.
- NDJSON smoke: ready, ping, invalid JSON, unknown command a shutdown prosly.
- Dva worker joby bezely ve stejnem PID.
- Queued i running cancellation prosly; opakovane cancel je idempotentni.
- SSE vratilo aktualni stav i finalni event a neobsahovalo lokalni cestu.
- Batch 8/10/12 % bezel jako jeden job, 3 unikatni scale evaluace, 64 eventu.
- Batch ZIP mel 2 460 531 B.
- Density runner odmita vysledky, ktere nejsou watertight a edge-manifold.
- Importni test: prvni job `domainReused=false`, druhy job
  `domainReused=true`, `locatorReused=true`, `topologyReused=true`.

Pri dvou kompatibilnich importnich jobech vznikl `TriangleMeshDomain` jednou a
`vtkStaticCellLocator` jednou. Druhy job pouzil oba objekty z RAM. Obe importni
geometrie byly watertight a edge-manifold.

## Vykon

Maly box, 12 seedu, tri scale evaluace, preview voxel 0.15 mm:

| Rezim | Wall time |
| --- | ---: |
| Tri samostatne Python procesy | 10.380 s |
| Prvni persistentni batch | 6.409 s |
| Opakovany persistentni batch | 6.654 s |

Cas uvnitr workeru byl 5.310 s a 5.542 s. PID obou batch jobu byl 3704.
Opakovany maly batch neni rychlejsi, protoze v nem prevazuje finalni implicitni
meshing, validace a export. RAM reuse je zretelnejsi u importovaneho meshe:

| Importovany uzavreny mesh | Cas |
| --- | ---: |
| Prvni job | 4.736 s |
| Kompatibilni RAM-cached job | 2.067 s |

Samostatny import NumPy/SciPy/PyVista/VTK trval 13.719 s pri studenem prvnim
startu a 1.732/1.707 s pri dalsich startech. Worker knihovny importoval jednou
za 1.173 s. Jednotlive samostatne scale procesy trvaly 2.251 s, 3.820 s a
4.286 s.

Worker handshake meri start/import oddelene. Generator metadata dale meri
domain build, cache read/write, SDF field, marching cubes, validaci a export.

## Znama omezeni

- Joby a jejich SSE historie jsou pouze v pameti Vite a po restartu se neobnovi.
- Je pouze jeden worker a jedna FIFO fronta bez priorit.
- Neocekavany pad aktivni job neobnovi; job skonci jako `worker-lost`.
- VTK operace jsou kooperativne zrusitelne az po navratu z konkretniho volani.
- RAM session zrychluje topologii a domenu, ne finalni meshing pro novy prumer.
- Stare synchronni endpointy zustaly kompatibilni a mohou stale spoustet
  samostatny proces; nove UI pouziva vyhradne job API.
