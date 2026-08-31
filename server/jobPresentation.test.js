import assert from "node:assert/strict";
import test from "node:test";

import {
  buildGenerationFingerprint,
  describeJobPhase,
  formatJobElapsed,
} from "../src/jobPresentation.js";

test("generation fingerprint is stable across object key order", () => {
  const first = buildGenerationFingerprint({ mode: "volume", controls: { seed: 42, points: 80 } });
  const second = buildGenerationFingerprint({ controls: { points: 80, seed: 42 }, mode: "volume" });
  assert.equal(first, second);
  assert.notEqual(first, buildGenerationFingerprint({ mode: "volume", controls: { seed: 43, points: 80 } }));
});

test("job presentation translates phases and formats long durations", () => {
  assert.equal(describeJobPhase("generating-final-mesh"), "Skládání finálního meshe");
  assert.equal(describeJobPhase("custom-worker-phase"), "custom worker phase");
  assert.equal(formatJobElapsed(9.25), "9.3 s");
  assert.equal(formatJobElapsed(133.25), "2 min 13 s");
});
