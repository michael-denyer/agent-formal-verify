// Copyright (c) 2026 Michael Denyer
// SPDX-License-Identifier: GPL-3.0-only
import { afterEach, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const scripts = join(root, "skills/formal-verify/scripts");
const fixtures = [];
afterEach(() => {
  for (const dir of fixtures.splice(0)) rmSync(dir, { recursive: true, force: true });
});
function fixture() {
  const dir = mkdtempSync(join(tmpdir(), "formal-tools-"));
  fixtures.push(dir);
  mkdirSync(join(dir, "bin"));
  return dir;
}
function command(dir, name, body) {
  const path = join(dir, "bin", name);
  writeFileSync(path, "#!/bin/bash\n" + body + "\n");
  chmodSync(path, 0o755);
  return path;
}
function run(dir, script, args = [], extra = {}) {
  return spawnSync("bash", [join(scripts, script), ...args], {
    encoding: "utf8",
    env: {
      ...process.env,
      PATH: join(dir, "bin") + ":" + process.env.PATH,
      JAVA: command(dir, "java", "exit 0"),
      TLC_CACHE: join(dir, "cache"),
      TLC_JAR: "",
      TASK_TRACE: join(dir, "calls"),
      ...extra,
    },
  });
}

test("TLC verification reports a missing JAR without downloading or creating its cache", () => {
  const dir = fixture();
  const matrix = join(dir, "empty.matrix");
  writeFileSync(matrix, "");
  command(dir, "curl", 'echo download >> "$TASK_TRACE"; exit 99');
  const result = run(dir, "tlc-matrix.sh", [matrix]);
  expect(result.status).toBe(1);
  expect(result.stdout).toContain("setup.sh tla");
  expect(existsSync(join(dir, "calls"))).toBe(false);
  expect(existsSync(join(dir, "cache"))).toBe(false);
});

test("TLC setup verifies downloads before publishing them and removes failed temporary files", () => {
  const dir = fixture();
  command(dir, "curl", [
    'while [ "$#" -gt 0 ]; do',
    '  if [ "$1" = "-o" ]; then printf corrupt > "$2"; exit 0; fi',
    '  shift',
    'done',
    'exit 99',
  ].join("\n"));
  const result = run(dir, "setup.sh", ["tla"]);
  expect(result.status).toBe(1);
  expect(result.stdout).toContain("has sha256");
  expect(readdirSync(join(dir, "cache"))).toEqual([]);
});

test("TLC setup accepts an explicitly supplied local JAR without contacting a release host", () => {
  const dir = fixture();
  const jar = join(dir, "local tools.jar");
  writeFileSync(jar, "user supplied");
  command(dir, "curl", 'echo download >> "$TASK_TRACE"; exit 99');
  const result = run(dir, "setup.sh", ["tla"], { TLC_JAR: jar });
  expect(result.status).toBe(0);
  expect(result.stdout).toContain("READY TLC " + jar);
  expect(existsSync(join(dir, "calls"))).toBe(false);
  expect(existsSync(join(dir, "cache"))).toBe(false);
});

test("Lean verification refuses an unprepared toolchain without requesting installation", () => {
  const dir = fixture();
  const project = join(dir, "model");
  mkdirSync(project);
  writeFileSync(join(project, "lakefile.toml"), 'name = "model"\n');
  writeFileSync(join(project, "lean-toolchain"), "leanprover/lean4:v4.34.1\n");
  command(dir, "elan", 'printf "%s\\n" "$@" >> "$TASK_TRACE"; exit 1');
  const result = run(dir, "lean-check.sh", [project]);
  expect(result.status).toBe(1);
  expect(result.stdout).toContain("setup.sh lean");
  const args = readFileSync(join(dir, "calls"), "utf8").trim().split("\n");
  expect(args).toEqual(["run", "leanprover/lean4:v4.34.1", "lake", "--version"]);
});

test("Lean preparation reuses ready pins and installs a changed repository pin once", () => {
  const dir = fixture();
  const project = join(dir, "model with spaces");
  const installed = join(dir, "installed");
  const oldPin = "leanprover/lean4:v4.34.0";
  const newPin = "leanprover/lean4:v4.34.1";
  mkdirSync(project);
  writeFileSync(join(project, "lean-toolchain"), oldPin + "\n");
  writeFileSync(installed, oldPin + "\n");
  command(dir, "elan", [
    'printf "%s\\n" "$*" >> "$TASK_TRACE"',
    'case "$1 $2" in',
    '  "toolchain install") printf "%s\\n" "$3" >> "$TASK_INSTALLED" ;;',
    '  *) grep -Fxq "$2" "$TASK_INSTALLED" ;;',
    'esac',
  ].join("\n"));
  const extra = { TASK_INSTALLED: installed };
  expect(run(dir, "setup.sh", ["lean", project], extra).status).toBe(0);
  writeFileSync(join(project, "lean-toolchain"), newPin + "\n");
  const prepared = run(dir, "setup.sh", ["lean", project], extra);
  expect(prepared.status).toBe(0);
  expect(prepared.stdout).toContain("READY Lean " + newPin);
  expect(run(dir, "setup.sh", ["lean", project], extra).status).toBe(0);
  const calls = readFileSync(join(dir, "calls"), "utf8").trim().split("\n");
  expect(calls.filter((line) => line.startsWith("toolchain install"))).toEqual([
    "toolchain install " + newPin,
  ]);
});

test("Lean preparation reports failure when installation does not produce a working toolchain", () => {
  const dir = fixture();
  const project = join(dir, "model");
  mkdirSync(project);
  writeFileSync(join(project, "lean-toolchain"), "leanprover/lean4:v4.34.1\n");
  command(dir, "elan", 'if [ "$1" = "toolchain" ]; then exit 0; fi; exit 1');
  const result = run(dir, "setup.sh", ["lean", project]);
  expect(result.status).toBe(1);
  expect(result.stdout).not.toContain("READY");
});

test("the plugin and portable references validate from an isolated checkout", () => {
  const dir = fixture();
  for (const file of ["CHANGES.md", ".claude-plugin", ".codex-plugin", ".agents", "skills", "tools"]) {
    cpSync(join(root, file), join(dir, file), { recursive: true, filter: (path) => !path.includes("/.lake") });
  }
  const result = spawnSync("node", [join(dir, "tools/check.mjs")], { encoding: "utf8" });
  expect(result.status).toBe(0);
  expect(result.stdout).toContain("portable skill references");
});
