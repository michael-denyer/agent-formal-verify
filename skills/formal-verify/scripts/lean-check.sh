#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Builds a Lean 4 model with Lake. Fails when the build fails, a declaration
# uses sorry, or a #print axioms line lists an axiom beyond propext,
# Classical.choice and Quot.sound. Otherwise prints the build output and PASS.
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
# Lean quotes sorry with backticks or straight quotes depending on the version.
sorry='^(warning|error): .*: declaration uses .sorry.'
# A #print axioms line that lists only Lean's three standard axioms.
standard='depends on axioms: \[((propext|Classical\.choice|Quot\.sound)(, )?)+\]$'
sorries=$(grep -cE "$sorry" "$log")
axioms=$(grep "depends on axioms:" "$log" | grep -cvE "$standard")
if [ "$status" -ne 0 ] || [ "$sorries" -ne 0 ] || [ "$axioms" -ne 0 ]; then
  echo "FAIL $dir: $sorries sorries, $axioms theorems on extra axioms, lake exit $status"
  grep -E "$sorry" "$log"
  grep "depends on axioms:" "$log" | grep -vE "$standard"
  [ "$status" -eq 0 ] || grep -v '^[[:space:]]*$' "$log" | tail -40
  exit 1
fi
# #eval and #print axioms output arrives as info blocks that can span lines.
grep -v '^[[:space:]]*$' "$log"
echo "PASS $dir: no sorry, no extra axioms"
