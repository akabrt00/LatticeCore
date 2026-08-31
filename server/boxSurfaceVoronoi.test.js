import assert from "node:assert/strict";
import test from "node:test";

import {
  createClippedVoronoiSegments,
  generateWellSpacedSeeds,
} from "../src/boxSurfaceVoronoi.js";

test("one seed covers the complete rectangular boundary", () => {
  const segments = createClippedVoronoiSegments([[0, 0]], 10, 6);
  assert.equal(segments.length, 4);
  const totalLength = segments.reduce((sum, [start, end]) => (
    sum + Math.hypot(end[0] - start[0], end[1] - start[1])
  ), 0);
  assert.ok(Math.abs(totalLength - 32) < 1e-6);
});

test("two seeds create a shared divider and stay inside the face", () => {
  const segments = createClippedVoronoiSegments([[-2, 0], [2, 0]], 10, 6);
  assert.ok(segments.some(([start, end]) => Math.abs(start[0]) < 1e-6 && Math.abs(end[0]) < 1e-6));
  for (const segment of segments) {
    for (const point of segment) {
      assert.ok(Math.abs(point[0]) <= 5 + 1e-6);
      assert.ok(Math.abs(point[1]) <= 3 + 1e-6);
    }
  }
});

test("well-spaced seed generation is deterministic", () => {
  const sequence = [0.1, 0.8, 0.3, 0.6, 0.2, 0.9];
  const makeRandom = () => {
    let index = 0;
    return () => sequence[(index += 1) % sequence.length];
  };
  assert.deepEqual(
    generateWellSpacedSeeds(5, 10, 8, makeRandom()),
    generateWellSpacedSeeds(5, 10, 8, makeRandom()),
  );
});
