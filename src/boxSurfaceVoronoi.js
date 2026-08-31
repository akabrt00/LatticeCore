const DEFAULT_EPSILON = 1e-8;

function squaredDistance(left, right) {
  const dx = left[0] - right[0];
  const dy = left[1] - right[1];
  return dx * dx + dy * dy;
}

function clipCellByBisector(polygon, seed, other, epsilon = DEFAULT_EPSILON) {
  if (polygon.length === 0) return [];
  const normalX = 2 * (other[0] - seed[0]);
  const normalY = 2 * (other[1] - seed[1]);
  const limit = squaredDistance(other, [0, 0]) - squaredDistance(seed, [0, 0]);
  const signedDistance = (point) => normalX * point[0] + normalY * point[1] - limit;
  const result = [];

  for (let index = 0; index < polygon.length; index += 1) {
    const start = polygon[index];
    const end = polygon[(index + 1) % polygon.length];
    const startDistance = signedDistance(start);
    const endDistance = signedDistance(end);
    const startInside = startDistance <= epsilon;
    const endInside = endDistance <= epsilon;

    if (startInside) result.push(start);
    if (startInside === endInside) continue;
    const denominator = startDistance - endDistance;
    if (Math.abs(denominator) <= epsilon) continue;
    const ratio = startDistance / denominator;
    result.push([
      start[0] + (end[0] - start[0]) * ratio,
      start[1] + (end[1] - start[1]) * ratio,
    ]);
  }
  return result;
}

function pointKey(point, precision) {
  return `${Math.round(point[0] / precision)},${Math.round(point[1] / precision)}`;
}

export function createClippedVoronoiSegments(seeds, width, height, precision = 1e-5) {
  if (!seeds.length || width <= 0 || height <= 0) return [];
  const halfWidth = width * 0.5;
  const halfHeight = height * 0.5;
  const rectangle = [
    [-halfWidth, -halfHeight],
    [halfWidth, -halfHeight],
    [halfWidth, halfHeight],
    [-halfWidth, halfHeight],
  ];
  const segments = new Map();

  for (let seedIndex = 0; seedIndex < seeds.length; seedIndex += 1) {
    let cell = rectangle.map((point) => [...point]);
    for (let otherIndex = 0; otherIndex < seeds.length && cell.length; otherIndex += 1) {
      if (otherIndex === seedIndex) continue;
      cell = clipCellByBisector(cell, seeds[seedIndex], seeds[otherIndex]);
    }
    for (let index = 0; index < cell.length; index += 1) {
      const start = cell[index];
      const end = cell[(index + 1) % cell.length];
      if (squaredDistance(start, end) <= precision * precision) continue;
      const startKey = pointKey(start, precision);
      const endKey = pointKey(end, precision);
      const key = startKey < endKey ? `${startKey}|${endKey}` : `${endKey}|${startKey}`;
      if (!segments.has(key)) segments.set(key, [start, end]);
    }
  }
  return [...segments.values()];
}

export function generateWellSpacedSeeds(count, width, height, random) {
  const seeds = [];
  const candidateCount = 18;
  for (let index = 0; index < count; index += 1) {
    let best = null;
    let bestDistance = -1;
    for (let candidateIndex = 0; candidateIndex < candidateCount; candidateIndex += 1) {
      const candidate = [(random() - 0.5) * width, (random() - 0.5) * height];
      const nearestDistance = seeds.length
        ? Math.min(...seeds.map((seed) => squaredDistance(seed, candidate)))
        : Infinity;
      if (nearestDistance > bestDistance) {
        best = candidate;
        bestDistance = nearestDistance;
      }
    }
    seeds.push(best);
  }
  return seeds;
}
