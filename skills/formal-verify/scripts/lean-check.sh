#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Builds a Lean 4 model with Lake, then audits every declaration of every built
# module. Fails when the build fails, a declaration uses sorry or rests on an
# axiom beyond propext, Classical.choice and Quot.sound, or no Lake library
# owns a .lean file in the project. Otherwise prints the build output and PASS.
# Needs a pin of Lean 4.20.0 or later, the first whose Lake builds a module by
# its source path.
#
# Usage: lean-check.sh <lake-project-dir>
set -uo pipefail
dir=${1:?usage: lean-check.sh <lake-project-dir>}
HERE=$(cd "$(dirname "$0")" && pwd)
[ -f "$dir/lakefile.toml" ] || [ -f "$dir/lakefile.lean" ] || { echo "FAIL $dir has no lakefile"; exit 1; }
dir=$(cd "$dir" && pwd)
# shellcheck source=skills/formal-verify/scripts/lean-tools.sh
source "$HERE/lean-tools.sh"
# On failure the captured output is the FAIL line.
toolchain=$(lean_pin "$dir") || { echo "$toolchain"; exit 1; }
lean_pin_ready "$toolchain" \
  || { echo "FAIL $toolchain is not ready; run bash $HERE/setup.sh lean $dir"; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
log=$work/build.log
# Lake builds a module named by its source path and rejects a path that no
# library owns, so naming every source leaves no file unchecked. Its query
# command prints the .olean of each, which names the modules to audit without
# picking up a module left in the build directory by a deleted source.
sources=()
while IFS= read -r src; do sources+=("$src"); done \
  < <(find "$dir" -name '*.lean' -not -path "$dir/.lake/*" -not -name lakefile.lean | sort)
[ "${#sources[@]}" -gt 0 ] || { echo "FAIL $dir has no .lean file to check"; exit 1; }
elan run "$toolchain" lake --dir "$dir" query "${sources[@]/%/:olean}" > "$work/oleans" 2> "$log"
status=$?
# Lean quotes sorry with backticks or straight quotes depending on the version.
sorry='^(warning|error): .*: declaration uses .sorry.'
sorries=$(grep -cE "$sorry" "$log")

# The audit imports those modules and collects the axioms under each of their
# declarations, so it needs no #print axioms line in the model. It skips the
# compiler's auxiliary declarations, which older pins store with opaque
# placeholders that would read as axioms.
audit_status=0
: > "$work/audit.out"
if [ "$status" -eq 0 ]; then
  {
    echo "import Lean"
    sed -e 's|^.*/\.lake/build/lib/lean/||' -e 's|\.olean$||' -e 's|/|.|g' -e 's|^|import |' "$work/oleans"
    cat << 'EOF'
open Lean Elab Command in
#eval show CommandElabM Unit from do
  let env ← getEnv
  let modules := (env.imports.map (·.module)).erase `Lean
  let standard : Array Name := #[``propext, ``Classical.choice, ``Quot.sound]
  let names := env.constants.fold (fun acc name info => if info matches .axiomInfo _ then acc else acc.push name) #[]
  let mut audited := 0
  for name in names do
    let some idx := env.getModuleIdxFor? name | continue
    unless modules.contains env.header.moduleNames[idx.toNat]! do continue
    if ((privateToUserName? name).getD name).isInternal then continue
    audited := audited + 1
    let extra := (← collectAxioms name).filter (!standard.contains ·)
    unless extra.isEmpty do IO.println s!"AXIOMS '{name}' depends on axioms: {extra}"
  IO.println s!"AUDITED {audited} declarations"
EOF
  } > "$work/Audit.lean"
  elan run "$toolchain" lake --dir "$dir" env lean "$work/Audit.lean" > "$work/audit.out" 2>&1
  audit_status=$?
  grep -q '^AUDITED [1-9]' "$work/audit.out" || audit_status=1
fi
axioms=$(grep -c '^AXIOMS ' "$work/audit.out")

if [ "$status" -ne 0 ] || [ "$sorries" -ne 0 ] || [ "$axioms" -ne 0 ] || [ "$audit_status" -ne 0 ]; then
  echo "FAIL $dir: $sorries sorries, $axioms declarations on extra axioms, lake exit $status"
  grep -E "$sorry" "$log"
  grep '^AXIOMS ' "$work/audit.out"
  [ "$status" -eq 0 ] || grep -v '^[[:space:]]*$' "$log" | tail -40
  ! grep -q '^error: unknown module source path' "$log" \
    || echo "no library owns that file; import it from a built module or move it out of the project"
  ! grep -qE "^error: (unknown command 'query'|invalid script spec)" "$log" \
    || echo "$toolchain cannot build a module by its source path; pin Lean 4.20.0 or later"
  if [ "$audit_status" -ne 0 ]; then
    echo "the axiom audit did not run or found no declarations:"
    grep -v '^[[:space:]]*$' "$work/audit.out" | tail -40
  fi
  exit 1
fi
# #eval output arrives as info blocks that can span lines.
grep -v '^[[:space:]]*$' "$log"
echo "PASS $dir: no sorry, no extra axioms, $(grep '^AUDITED ' "$work/audit.out" | cut -d' ' -f2) declarations audited"
