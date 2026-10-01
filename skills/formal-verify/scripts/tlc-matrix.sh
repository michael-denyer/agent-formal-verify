#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Model-checks TLA+ specs with TLC over a matrix of constants read from a
# matrix file, and prints one PASS or FAIL line per run with its distinct
# state count. A failing run prints TLC's error and its error trace
# reduced to the variables each step changed (tlc-trace.py).
#
# Matrix file, one directive per line (# starts a comment):
#   spec <path.tla>             the spec for the runs below, relative to the file;
#                               TLC checks the formula it names Spec
#   check <cfg line>            an INVARIANTS or PROPERTIES line, kept until the next spec
#   run <label> | <Name=Value ...>   one TLC run with those CONSTANTS
#
# Usage: tlc-matrix.sh <matrix-file> [label-substring]
#   TLC_JAR=<path>     use this existing tla2tools.jar
#   TLC_CACHE=<dir>    where setup placed the jar (default ~/.cache/tla)
#   JAVA=<path>        the java binary (default: java on PATH)
#   TLC_WORKERS=<n>    TLC worker threads (default auto)
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=skills/formal-verify/scripts/tlc-tools.sh
source "$HERE/tlc-tools.sh"
TLC_WORKERS=${TLC_WORKERS:-auto}

matrix=${1:?usage: tlc-matrix.sh <matrix-file> [label-substring]}
only=${2:-}
MATRIX_DIR=$(cd "$(dirname "$matrix")" && pwd)

require_tlc_runtime || exit 1
tlc_jar_ready || exit 1

OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
fail=0
run=0
spec=""
checks=""

check_run() {
  local label=$1 consts=$2 name dir pairs c
  [ -n "$spec" ] || { echo "FAIL run '$label' before any spec line"; fail=1; return; }
  case $label in *"$only"*) ;; *) return ;; esac
  run=$((run + 1))
  name=$(basename "$spec" .tla)
  [ -f "$MATRIX_DIR/$spec" ] || { echo "FAIL $name $label: spec $spec not found"; fail=1; return; }
  # A directory per run, so a run sees only the modules beside its own spec.
  dir=$(mktemp -d "$OUT/run.XXXXXX")
  cp "$MATRIX_DIR/$(dirname "$spec")"/*.tla "$dir/"
  read -ra pairs <<< "$consts"
  {
    echo "CONSTANTS"
    # bash 3.2 treats an empty array as unset under set -u.
    for c in ${pairs[@]+"${pairs[@]}"}; do echo "  ${c%%=*} = ${c#*=}"; done
    echo "SPECIFICATION Spec"
    printf '%s\n' "$checks"
  } > "$dir/MC.cfg"
  if "$JAVA" -XX:+UseParallelGC -cp "$TLC_JAR" tlc2.TLC -workers "$TLC_WORKERS" -cleanup -metadir "$dir/states" \
      -config "$dir/MC.cfg" "$dir/$name.tla" > "$dir/tlc.log" 2>&1 \
      && grep -q "No error has been found" "$dir/tlc.log"; then
    echo "PASS $name $label $(grep -o '[0-9,]* distinct states found' "$dir/tlc.log" | head -1)"
  else
    echo "FAIL $name $label: $(grep -m1 "^Error:" "$dir/tlc.log")"
    grep "^Error:" "$dir/tlc.log" | sed -n '2,5p'
    python3 "$HERE/tlc-trace.py" "$dir/tlc.log" || grep -v '^[[:space:]]*$' "$dir/tlc.log" | tail -40
    fail=1
  fi
}

while IFS= read -r line || [ -n "$line" ]; do
  line=${line%%#*}
  [[ $line =~ [^[:space:]] ]] || continue
  read -r kw rest <<< "$line"
  case $kw in
    spec) spec=$rest; checks="" ;;
    check) checks="$checks${checks:+$'\n'}$rest" ;;
    run) label=${rest%%|*}; check_run "${label% }" "${rest#*|}" ;;
    *) echo "FAIL unknown directive: $line"; fail=1 ;;
  esac
done < "$matrix"

[ "$run" -gt 0 ] || { echo "FAIL no run ${only:+matching '$only' }in $matrix"; fail=1; }
exit $fail
