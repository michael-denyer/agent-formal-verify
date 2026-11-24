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

// The Bash 3.2 job's lines from its tarball download through its checksum check.
function download() {
  const workflow = readFileSync(join(root, ".github/workflows/ci.yml"), "utf8").split("\n");
  const step = workflow.findIndex((line) => line.includes("name: Build GNU Bash 3.2.57"));
  const first = workflow.findIndex((line, i) => i > step && /^\s*curl /.test(line));
  const last = workflow.findIndex((line, i) => i > step && line.includes("sha256sum -c"));
  assert.ok(step >= 0 && first > step && last > first, "the Bash 3.2 job has no download and checksum lines");
  return workflow.slice(first, last + 1).map((line) => line.trim()).join("\n");
}

// Run the download with a curl that times out for each unreachable URL and a sha256sum that needs the file.
function fetch(unreachable) {
  const dir = fixture();
  command(dir, "curl", `printf '%s\\n' "$*" >> "${dir}/curl.log"
for url; do :; done
case " ${unreachable.join(" ")} " in *" $url "*) exit 28;; esac
printf tarball > "\${url##*/}"`);
  command(dir, "sha256sum", `read -r line
printf '%s\\n' "$line" > "${dir}/sha256sum.log"
[ -f "\${line##* }" ]`);
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

test("the Bash 3.2 job falls back to ftp.gnu.org when ftpmirror.gnu.org is unreachable and checks the tarball either way", () => {
  const urls = (calls) => calls.map((call) => call.split(" ").at(-1));
  const checksum = /^[0-9a-f]{64} {2}bash-3\.2\.57\.tar\.gz$/;
  const fallback = fetch([mirror]);
  assert.equal(fallback.status, 0, fallback.stderr);
  assert.deepEqual(urls(fallback.calls), [mirror, origin]);
  for (const call of fallback.calls) assert.match(call, /--connect-timeout 30 /);
  assert.match(fallback.checked[0], checksum);
  const direct = fetch([]);
  assert.equal(direct.status, 0, direct.stderr);
  assert.deepEqual(urls(direct.calls), [mirror]);
  assert.match(direct.checked[0], checksum);
  const neither = fetch([mirror, origin]);
  assert.notEqual(neither.status, 0);
  assert.deepEqual(urls(neither.calls), [mirror, origin]);
});
