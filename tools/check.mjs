// Copyright (c) 2026 Michael Denyer
// SPDX-License-Identifier: GPL-3.0-only
import assert from "node:assert/strict";
import { readFileSync, readdirSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const read = (file) => readFileSync(join(root, file), "utf8");
const json = (file) => JSON.parse(read(file));
const version = json(".claude-plugin/plugin.json").version;
assert.match(version, /^\d+\.\d+\.\d+$/);
assert.ok(read("CHANGES.md").split("\n").some((line) => line.startsWith(`## ${version} - `)), "missing release entry");
for (const runtime of [".claude-plugin", ".codex-plugin"]) {
  const manifest = json(`${runtime}/plugin.json`);
  assert.equal(manifest.name, "agent-formal-verify");
  assert.equal(manifest.version, version);
  assert.equal(manifest.license, "GPL-3.0-only");
}
const claude = json(".claude-plugin/marketplace.json");
const codex = json(".agents/plugins/marketplace.json");
for (const marketplace of [claude, codex]) {
  assert.equal(marketplace.name, "agent-formal-verify");
  assert.equal(marketplace.plugins.length, 1);
  assert.equal(marketplace.plugins[0].name, "agent-formal-verify");
}
assert.equal(claude.plugins[0].source, "./");
assert.equal(claude.plugins[0].version, version);
assert.equal(codex.plugins[0].source.path, "./");
assert.equal(json(".codex-plugin/plugin.json").skills, "./skills/");

const skills = realpathSync(join(root, "skills"));
function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = join(dir, entry.name);
    return entry.isDirectory() ? walk(file) : [file];
  });
}
for (const file of walk(skills).filter((path) => path.endsWith(".md"))) {
  const text = readFileSync(file, "utf8");
  if (file.endsWith("/SKILL.md")) {
    assert.match(text, new RegExp(`^---\\nname: ${dirname(file).split(sep).at(-1)}\\n`));
    assert.match(text, /^description: .+/m);
  }
  for (const [, target] of text.matchAll(/\]\(([^)\s]+)\)/g)) {
    if (/^[a-z][a-z0-9+.-]*:|^#/i.test(target)) continue;
    const path = decodeURIComponent(target.split(/[?#]/)[0]);
    const resolved = realpathSync(resolve(dirname(file), path));
    const rel = relative(skills, resolved);
    assert.ok(!isAbsolute(path) && rel !== ".." && !rel.startsWith(`..${sep}`), `${file}: reference escapes skills tree: ${target}`);
  }
}
console.log(`ok: agent-formal-verify ${version}, manifests and portable skill references`);
