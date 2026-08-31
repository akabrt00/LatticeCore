const PHASE_LABELS = {
  queued: "Čekání ve frontě",
  "job-start": "Spuštění úlohy",
  "reading-input": "Kontrola vstupního modelu",
  "building-domain": "Příprava prostorové domény",
  "loading-disk-cache": "Načítání výpočetní cache",
  "generating-seeds": "Generování seed bodů",
  "computing-voronoi": "Výpočet 3D Voronoi",
  "clipping-interior": "Ořez vnitřní sítě",
  "creating-conformal-surface": "Povrchová Voronoi síť",
  "memory-preflight": "Kontrola paměti",
  "generating-final-mesh": "Skládání finálního meshe",
  "extracting-surface": "Extrakce povrchu",
  "validating-final-mesh": "Kontrola finální geometrie",
  "repairing-final-mesh": "Oprava exportního meshe",
  "validating-export": "Závěrečná validace",
  "preparing-density-solver": "Příprava cílové hustoty",
  "final-verification": "Finální kontrola hustoty",
  "exporting-files": "Export souborů",
  "creating-zip": "Vytváření ZIP archivu",
  "result-ready": "Výsledek připraven",
  "job-complete": "Dokončeno",
  "job-cancelled": "Zrušeno",
  "job-failed": "Chyba",
};

export function describeJobPhase(phase) {
  if (!phase) return "-";
  return PHASE_LABELS[phase] ?? phase.replaceAll("-", " ");
}

export function formatJobElapsed(seconds) {
  const safeSeconds = Math.max(0, Number(seconds) || 0);
  if (safeSeconds < 60) return `${safeSeconds.toFixed(1)} s`;
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = Math.floor(safeSeconds % 60);
  return `${minutes} min ${String(remainder).padStart(2, "0")} s`;
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

export function buildGenerationFingerprint(configuration) {
  return JSON.stringify(canonicalize(configuration));
}
