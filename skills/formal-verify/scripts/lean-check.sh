#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Builds a Lean 4 model with Lake and reports errors or uses of sorry with
# their file and line. A build with neither prints PASS.
#
# Usage: lean-check.sh <lake-project-dir>
set -uo pipefail
dir=${1:?usage: lean-check.sh <lake-project-dir>}
HERE=$(cd "$(dirname "$0")" && pwd)
[ -f "$dir/lakefile.toml" ] || [ -f "$dir/lakefile.lean" ] || { echo "FAIL $dir has no lakefile"; exit 1; }
command -v elan > /dev/null || { echo "FAIL elan is not on PATH (install elan: https://github.com/leanprover/elan)"; exit 1; }
[ -f "$dir/lean-toolchain" ] || { echo "FAIL $dir has no lean-toolchain pin"; exit 1; }
toolchain=$(tr -d '\r\n' < "$dir/lean-toolchain")
elan run "$toolchain" lake --version > /dev/null 2>&1 \
  || { echo "FAIL $toolchain is not ready; run bash $HERE/setup.sh lean $dir"; exit 1; }

log=$(mktemp)
trap 'rm -f "$log"' EXIT
elan run "$toolchain" lake --dir "$dir" build > "$log" 2>&1
status=$?
errors=$(grep -c "error:" "$log")
# Lean quotes sorry with backticks or straight quotes depending on the version.
sorries=$(grep -c "declaration uses .sorry." "$log")
if [ "$status" -ne 0 ] || [ "$errors" -ne 0 ] || [ "$sorries" -ne 0 ]; then
  echo "FAIL $dir: $errors errors, $sorries sorries, lake exit $status"
  grep -E "error:|declaration uses .sorry." "$log"
  [ "$status" -eq 0 ] || grep -v "^\s*$" "$log" | tail -30
  exit 1
fi
# #eval output (a bounded search's counter-example list) arrives as info lines.
grep "^info:" "$log"
echo "PASS $dir: no errors, no sorry"
