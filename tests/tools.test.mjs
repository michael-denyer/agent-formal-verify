// Copyright (c) 2026 Michael Denyer
// SPDX-License-Identifier: GPL-3.0-only
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, test } from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const scripts = join(root, "skills/formal-verify/scripts");
const logs = join(root, "tests/fixtures");
const includes = (text, part) => assert.ok(text.includes(part), `${JSON.stringify(text)} lacks ${JSON.stringify(part)}`);
const excludes = (text, part) => assert.ok(!text.includes(part), `${JSON.stringify(text)} has ${JSON.stringify(part)}`);
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
  assert.equal(result.status, 1);
  includes(result.stdout, "setup.sh tla");
  assert.equal(existsSync(join(dir, "calls")), false);
  assert.equal(existsSync(join(dir, "cache")), false);
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
  assert.equal(result.status, 1);
  includes(result.stdout, "has sha256");
  assert.deepEqual(readdirSync(join(dir, "cache")), []);
});

test("TLC setup accepts an explicitly supplied local JAR without contacting a release host", () => {
  const dir = fixture();
  const jar = join(dir, "local tools.jar");
  writeFileSync(jar, "user supplied");
  command(dir, "curl", 'echo download >> "$TASK_TRACE"; exit 99');
  const result = run(dir, "setup.sh", ["tla"], { TLC_JAR: jar });
  assert.equal(result.status, 0);
  includes(result.stdout, "READY TLC " + jar);
  assert.equal(existsSync(join(dir, "calls")), false);
  assert.equal(existsSync(join(dir, "cache")), false);
});

test("Lean verification refuses an unprepared toolchain without requesting installation", () => {
  const dir = fixture();
  const project = join(dir, "model");
  mkdirSync(project);
  writeFileSync(join(project, "lakefile.toml"), 'name = "model"\n');
  writeFileSync(join(project, "lean-toolchain"), "leanprover/lean4:v4.34.1\n");
  command(dir, "elan", 'printf "%s\\n" "$@" >> "$TASK_TRACE"; exit 1');
  const result = run(dir, "lean-check.sh", [project]);
  assert.equal(result.status, 1);
  includes(result.stdout, "setup.sh lean");
  const args = readFileSync(join(dir, "calls"), "utf8").trim().split("\n");
  assert.deepEqual(args, ["run", "leanprover/lean4:v4.34.1", "lake", "--version"]);
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
  assert.equal(run(dir, "setup.sh", ["lean", project], extra).status, 0);
  writeFileSync(join(project, "lean-toolchain"), newPin + "\n");
  const prepared = run(dir, "setup.sh", ["lean", project], extra);
  assert.equal(prepared.status, 0);
  includes(prepared.stdout, "READY Lean " + newPin);
  assert.equal(run(dir, "setup.sh", ["lean", project], extra).status, 0);
  const calls = readFileSync(join(dir, "calls"), "utf8").trim().split("\n");
  assert.deepEqual(calls.filter((line) => line.startsWith("toolchain install")), [
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
  assert.equal(result.status, 1);
  excludes(result.stdout, "READY");
});

function reduce(log) {
  return spawnSync("python3", [join(scripts, "tlc-trace.py"), join(logs, log)], { encoding: "utf8" });
}

test("the trace reducer shows only changed variables for an invariant violation", () => {
  const result = reduce("tlc-invariant.log");
  assert.equal(result.status, 0);
  assert.equal(result.stdout, [
    "--- state 1: Initial predicate",
    "    x = 0",
    "    y = 0",
    "--- state 2: Step",
    "    x = 1",
    "--- state 3: Step",
    "    x = 2",
    "    y = 1",
    "--- state 4: Step",
    "    x = 3",
    "",
  ].join("\n"));
});

test("the trace reducer keeps the lasso of a liveness counter-example", () => {
  const result = reduce("tlc-liveness.log");
  assert.equal(result.status, 0);
  includes(result.stdout, "--- state 3: Step\n    x = 2\n    y = 1\n--- Back to state 1");
});

test("the trace reducer reads a one-variable spec and its multi-line values", () => {
  const result = reduce("tlc-one-variable.log");
  assert.equal(result.status, 0);
  includes(result.stdout, "--- state 1: Initial predicate\n    x = <<>>\n--- state 2: Next\n    x = << [ id |-> 0,");
  includes(result.stdout, "   [ id |-> 1,");
});

test("the trace reducer fails on a log without an error trace", () => {
  const result = reduce("lake-sorry.log");
  assert.equal(result.status, 1);
  assert.equal(result.stdout, "");
});

function matrixFixture(lines, java) {
  const dir = fixture();
  for (const sub of ["a", "b"]) mkdirSync(join(dir, sub));
  writeFileSync(join(dir, "a/One.tla"), "---- MODULE One ----\n====\n");
  writeFileSync(join(dir, "a/Helper.tla"), "---- MODULE Helper ----\n====\n");
  writeFileSync(join(dir, "b/Two.tla"), "---- MODULE Two ----\n====\n");
  writeFileSync(join(dir, "checks.matrix"), lines.join("\n") + "\n");
  writeFileSync(join(dir, "tools.jar"), "user supplied");
  const passing = 'echo "Model checking completed. No error has been found."; echo "4 distinct states found"';
  return {
    dir,
    matrix: (args = []) => run(dir, "tlc-matrix.sh", [join(dir, "checks.matrix"), ...args], {
      JAVA: command(dir, "tlc-java", '[ "$1" = "-version" ] && exit 0\n' + (java ?? passing)),
      TLC_JAR: join(dir, "tools.jar"),
      TLC_LOG: join(logs, "tlc-invariant.log"),
    }),
  };
}

test("the matrix runner reduces the trace of an invariant violation", () => {
  const { matrix } = matrixFixture(["spec a/One.tla", "check INVARIANTS Small", "run n=4 | N=4"], 'cat "$TLC_LOG"; exit 12');
  const result = matrix();
  assert.equal(result.status, 1);
  includes(result.stdout, "FAIL One n=4: Error: Invariant Small is violated.");
  includes(result.stdout, "--- state 4: Step\n    x = 3\n");
  excludes(result.stdout, "/\\ y = 1");
});

test("the matrix runner gives each run only its own spec directory's modules", () => {
  const { dir, matrix } = matrixFixture(
    ["spec a/One.tla", "run first | N=1", "\t", "spec b/Two.tla", "run second |"],
    'for last; do :; done; ls "$(dirname "$last")" | grep tla$ | tr "\\n" " " >> "$TASK_TRACE"; echo >> "$TASK_TRACE"\n' +
      'echo "Model checking completed. No error has been found."',
  );
  const result = matrix();
  excludes(result.stdout, "unknown directive");
  assert.equal(result.status, 0);
  assert.equal(readFileSync(join(dir, "calls"), "utf8"), "Helper.tla One.tla \nTwo.tla \n");
});

test("the matrix runner reports a missing spec in one line without starting TLC", () => {
  const { dir, matrix } = matrixFixture(["spec a/Gone.tla", "run only | N=1"], 'echo started >> "$TASK_TRACE"');
  const result = matrix();
  assert.equal(result.status, 1);
  assert.equal(result.stdout, "FAIL Gone only: spec a/Gone.tla not found\n");
  assert.equal(result.stderr, "");
  assert.equal(existsSync(join(dir, "calls")), false);
});

test("the matrix runner names the matrix when it has no runs and the filter when none match", () => {
  const { dir, matrix } = matrixFixture(["spec a/One.tla"]);
  assert.equal(matrix().stdout, `FAIL no run in ${join(dir, "checks.matrix")}\n`);
  assert.equal(matrix(["absent"]).stdout, `FAIL no run matching 'absent' in ${join(dir, "checks.matrix")}\n`);
});

function leanFixture(log, status = 0) {
  const dir = fixture();
  const project = join(dir, "model");
  mkdirSync(project);
  writeFileSync(join(project, "lakefile.toml"), 'name = "model"\n');
  writeFileSync(join(project, "lean-toolchain"), "leanprover/lean4:v4.34.1\n");
  command(dir, "elan", `[ "$4" = "--version" ] && exit 0\ncat "${join(logs, log)}"; exit ${status}`);
  return run(dir, "lean-check.sh", [project]);
}

test("the Lean checker prints multi-line search output whole and ignores error text in output", () => {
  const result = leanFixture("lake-search.log");
  assert.equal(result.status, 0);
  includes(result.stdout, " ({ next := 3, consumed := 1 }, { next := 4, consumed := 1 })]\n");
  includes(result.stdout, "PASS ");
});

test("the Lean checker fails a build that uses sorry", () => {
  const result = leanFixture("lake-sorry.log");
  assert.equal(result.status, 1);
  includes(result.stdout, "1 sorries");
  includes(result.stdout, "warning: Model.lean:69:8: declaration uses `sorry`");
});

test("the Lean checker fails a theorem that depends on a declared axiom", () => {
  const result = leanFixture("lake-axiom.log");
  assert.equal(result.status, 1);
  includes(result.stdout, "'anything' depends on axioms: [cheat]");
});

test("the Lean checker fails when Lake fails", () => {
  const result = leanFixture("lake-search.log", 1);
  assert.equal(result.status, 1);
  includes(result.stdout, "lake exit 1");
});
