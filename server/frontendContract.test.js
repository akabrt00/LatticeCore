import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root = path.resolve(".");

test("frontend starts in volume mode with conformal multi-component defaults", async () => {
  const html = await fs.readFile(path.join(root, "index.html"), "utf8");
  assert.match(html, /class="active" type="button" data-mode="volume"/);
  assert.match(html, /value="use-all-closed" selected/);
  assert.match(html, /value="conformal-surface" selected/);
  assert.match(html, /src="\.\/src\/latticecore\.js"/);
});

test("uploaded models can enter surface mode and UI has no obsolete roadmap claim", async () => {
  const [html, source] = await Promise.all([
    fs.readFile(path.join(root, "index.html"), "utf8"),
    fs.readFile(path.join(root, "src", "latticecore.js"), "utf8"),
  ]);
  assert.doesNotMatch(source, /button\.dataset\.mode === "surface" && state\.uploadedFile/);
  assert.doesNotMatch(`${html}\n${source}`, /conformal Voronoi síť bude doplněna v další etapě/);
  assert.doesNotMatch(html, /Další etapa doplní conformal Voronoi síť/);
});

test("component validation errors are translated into actionable Czech guidance", async () => {
  const source = await fs.readFile(path.join(root, "src", "latticecore.js"), "utf8");
  assert.match(source, /Model obsahuje \$\{count\} oddělených komponent/);
  assert.match(source, /Některá komponenta modelu není uzavřená nebo manifold/);
});
