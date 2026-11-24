// Copyright (c) 2026 Michael Denyer
// SPDX-License-Identifier: GPL-3.0-only
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, test } from "node:test";
import { command, fixture, removeFixtures, root } from "./helpers.mjs";

afterEach(removeFixtures);

const mirror = "https://192.0.2.1/bash/bash-3.2.57.tar.gz";
const origin = "https://ftp.gnu.org/gnu/bash/bash-3.2.57.tar.gz";

// The Bash 3.2 job's lines that download its tarball and check its checksum.
function download() {
  const workflow = readFileSync(join(root, ".github/workflows/ci.yml"), "utf8").split("\n");
  const step = workflow.findIndex((line) => line.includes("name: Build GNU Bash 3.2.57"));
  const first = workflow.findIndex((line, i) => i > step && /^\s*fetch\(\) \{/.test(line));
  const last = workflow.findIndex((line, i) => i > step && /^\s*fetch https:/.test(line));
  assert.ok(step >= 0 && first > step && last > first, "the Bash 3.2 job has no fetch function and call");
  return workflow.slice(first, last + 1).map((line) => line.trim()).join("\n");
}

// Run the download with a curl that times out for each unreachable URL and serves other bytes for each junk URL,
// and a sha256sum that accepts only the bytes curl serves for the other URLs.
function fetch(unreachable, junk = []) {
  const dir = fixture();
  command(dir, "curl", `printf '%s\\n' "$*" >> "${dir}/curl.log"
prev=
for arg; do [ "$prev" = -o ] && out=$arg; prev=$arg; done
case " ${unreachable.join(" ")} " in *" $arg "*) exit 28;; esac
case " ${junk.join(" ")} " in *" $arg "*) printf junk > "$out"; exit 0;; esac
printf tarball > "$out"`);
  command(dir, "sha256sum", `read -r line
printf '%s\\n' "$line" >> "${dir}/sha256sum.log"
[ "$(cat "\${line##* }")" = tarball ]`);
  const result = spawnSync("bash", ["-e", "-c", download()], { cwd: dir, encoding: "utf8", env: { ...process.env, PATH: `${join(dir, "bin")}:${process.env.PATH}` } });
  const log = (name) => {
    try {
      return readFileSync(join(dir, name), "utf8").split("\n").filter(Boolean);
    } catch {
      return [];
    }
  };
  return { status: result.status, stderr: result.stderr, calls: log("curl.log"), checked: log("sha256sum.log") };
}

test("the Bash 3.2 job falls back to ftp.gnu.org when ftpmirror.gnu.org is unreachable or serves other bytes, and checks the tarball", () => {
  const urls = (calls) => calls.map((call) => call.split(" ").at(-1));
  const checksum = /^[0-9a-f]{64} {2}bash-3\.2\.57\.tar\.gz$/;
  const fallback = fetch([mirror]);
  assert.equal(fallback.status, 0, fallback.stderr);
  assert.deepEqual(urls(fallback.calls), [mirror, origin]);
  for (const call of fallback.calls) assert.match(call, /^-fL .*--connect-timeout 30 --retry 3 /);
  assert.match(fallback.checked[0], checksum);
  const corrupt = fetch([], [mirror]);
  assert.equal(corrupt.status, 0, corrupt.stderr);
  assert.deepEqual(urls(corrupt.calls), [mirror, origin]);
  assert.equal(corrupt.checked.length, 2);
  const direct = fetch([]);
  assert.equal(direct.status, 0, direct.stderr);
  assert.deepEqual(urls(direct.calls), [mirror]);
  assert.match(direct.checked[0], checksum);
  const neither = fetch([mirror, origin]);
  assert.notEqual(neither.status, 0);
  assert.deepEqual(urls(neither.calls), [mirror, origin]);
});
