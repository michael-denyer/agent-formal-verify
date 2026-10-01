// Copyright (c) 2026 Michael Denyer
// SPDX-License-Identifier: GPL-3.0-only
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const read = (file) => readFileSync(join(root, file), "utf8");
const json = (file) => JSON.parse(read(file));
const manifests = [".claude-plugin", ".codex-plugin"].map((runtime) => json(`${runtime}/plugin.json`));
const claude = json(".claude-plugin/marketplace.json");
const codex = json(".agents/plugins/marketplace.json");

test("the release version agrees across the manifests, the marketplace entry and the changelog", () => {
  const { version } = manifests[0];
  assert.match(version, /^\d+\.\d+\.\d+$/);
  for (const manifest of manifests) assert.equal(manifest.version, version);
  assert.equal(claude.plugins[0].version, version);
  assert.ok(read("CHANGES.md").split("\n").some((line) => line.startsWith(`## ${version} - `)), "missing release entry");
});

test("the manifests and marketplaces describe one plugin", () => {
  for (const manifest of manifests) {
    assert.equal(manifest.name, "agent-formal-verify");
    assert.equal(manifest.license, "GPL-3.0-only");
    assert.equal(manifest.description, manifests[0].description);
  }
  for (const marketplace of [claude, codex]) {
    assert.equal(marketplace.name, "agent-formal-verify");
    assert.equal(marketplace.plugins.length, 1);
    assert.equal(marketplace.plugins[0].name, "agent-formal-verify");
  }
  assert.equal(claude.plugins[0].description, manifests[0].description);
  assert.equal(claude.plugins[0].source, "./");
  assert.equal(codex.plugins[0].source.path, "./");
  assert.equal(manifests[1].skills, "./skills/");
});

const skills = realpathSync(join(root, "skills"));
function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = join(dir, entry.name);
    return entry.isDirectory() ? walk(file) : [file];
  });
}

test("skills declare their names and link only to files inside the skills tree", () => {
  for (const file of walk(skills).filter((path) => path.endsWith(".md"))) {
    const text = readFileSync(file, "utf8");
    if (file.endsWith("/SKILL.md")) {
      assert.match(text, new RegExp(`^---\\nname: ${dirname(file).split(sep).at(-1)}\\n`));
      assert.match(text, /^description: .+/m);
    }
    for (const [, target] of text.matchAll(/\]\(([^)\s]+)\)/g)) {
      if (/^[a-z][a-z0-9+.-]*:|^#/i.test(target)) continue;
      const path = decodeURIComponent(target.split(/[?#]/)[0]);
      const linked = resolve(dirname(file), path);
      assert.ok(existsSync(linked), `${file}: broken reference: ${target}`);
      const rel = relative(skills, realpathSync(linked));
      assert.ok(!isAbsolute(path) && rel !== ".." && !rel.startsWith(`..${sep}`), `${file}: reference escapes skills tree: ${target}`);
    }
  }
});
