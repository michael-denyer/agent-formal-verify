#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Model-checks TLA+ specs with TLC over a matrix of constants read from a
# matrix file, and prints one PASS or FAIL line per run with its distinct
# state count, then a SUMMARY line with the totals. A failing run prints TLC's
# error and its error trace reduced to the variables each step changed
# (tlc-trace.py).
#
# Matrix file, one directive per line (# starts a comment):
#   spec <path.tla>             the spec for the runs below, relative to the file;
#                               TLC checks the formula it names Spec
#   check <cfg line>            an INVARIANTS or PROPERTIES line, kept until the next spec
#   reach <Operator> | <label-substring>   a witness in the first matching run
#   run <label> | <Name=Value ...>   one TLC run with those CONSTANTS
#
# Usage: tlc-matrix.sh <matrix-file> [label-substring]
#   TLC_JAR=<path>     use this existing tla2tools.jar
#   TLC_CACHE=<dir>    where the pinned jar lives (default ~/.cache/tla)
#   JAVA=<path>        the java binary (default: java on PATH)
#   TLC_WORKERS=<n>    TLC worker threads (default auto)
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=skills/formal-verify/scripts/tlc-tools.sh
source "$HERE/tlc-tools.sh"
TLC_WORKERS=${TLC_WORKERS:-auto}

[ "$#" -ge 1 ] && [ "$#" -le 2 ] || { echo "usage: tlc-matrix.sh <matrix-file> [label-substring]"; exit 2; }
matrix=$1
[ -f "$matrix" ] || { echo "FAIL $matrix does not exist"; exit 1; }
only=${2:-}
MATRIX_DIR=$(cd "$(dirname "$matrix")" && pwd)

require_tlc_runtime || exit $?
tlc_jar_ready || exit $?

OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
fail=0
run=0
passed=0
total=0
spec=""
checks=""
reaches=()
runs=()
reach_count=0
reach_passed=0

check_run() {
  local label=$1 consts=$2 operator=${3:-} name dir pairs c states wrapper invariant status trace
  local workers=$TLC_WORKERS extra=()
  [ -n "$spec" ] || { echo "FAIL run '$label' before any spec line"; fail=1; return; }
  case $label in *"$only"*) ;; *) return ;; esac
  if [ -n "$operator" ]; then reach_count=$((reach_count + 1)); else run=$((run + 1)); fi
  name=$(basename "$spec" .tla)
  [ -f "$MATRIX_DIR/$spec" ] || { echo "FAIL $name $label: spec $spec not found"; fail=1; return; }
  # A directory per run, so a run sees only the modules beside its own spec.
  dir=$(mktemp -d "$OUT/run.XXXXXX")
  cp "$MATRIX_DIR/$(dirname "$spec")"/*.tla "$dir/"
  wrapper=$name
  if [ -n "$operator" ]; then
    # Neither generated identifier may shadow an imported declaration or module.
    while :; do
      wrapper=Reach$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
      invariant=${wrapper}Negated
      grep -Ewq "$wrapper|$invariant" "$dir/"*.tla || break
    done
    printf '%s\n' "---- MODULE $wrapper ----" "EXTENDS $name" "$invariant == ~$operator" "====" > "$dir/$wrapper.tla"
    workers=1
    extra=(-deadlock)
  fi
  read -ra pairs <<< "$consts"
  {
    echo "CONSTANTS"
    # bash 3.2 treats an empty array as unset under set -u.
    for c in ${pairs[@]+"${pairs[@]}"}; do echo "  ${c%%=*} = ${c#*=}"; done
    echo "SPECIFICATION Spec"
    if [ -n "$operator" ]; then echo "INVARIANT $invariant"; else printf '%s\n' "$checks"; fi
  } > "$dir/MC.cfg"
  status=0
  "$JAVA" -XX:+UseParallelGC -cp "$TLC_JAR" tlc2.TLC -workers "$workers" ${extra[@]+"${extra[@]}"} -cleanup -metadir "$dir/states" \
      -config "$dir/MC.cfg" "$dir/$wrapper.tla" > "$dir/tlc.log" 2>&1 || status=$?
  if [ -n "$operator" ]; then
    if [ "$status" -eq 12 ] && grep -Fxq "Error: Invariant $invariant is violated by the initial state:" "$dir/tlc.log"; then
      trace=1
    elif [ "$status" -eq 12 ] && grep -Fxq "Error: Invariant $invariant is violated." "$dir/tlc.log"; then
      trace=$(grep -c '^State [0-9][0-9]*:' "$dir/tlc.log")
    else
      trace=0
    fi
    if [ "$trace" -gt 0 ]; then
      echo "PASS $name reach $operator $label: shortest trace $trace states ($((trace - 1)) transitions)"
      reach_passed=$((reach_passed + 1))
    elif [ "$status" -eq 0 ] && grep -q "No error has been found" "$dir/tlc.log"; then
      echo "FAIL $name reach $operator $label: the model never reaches this state"
      fail=1
    else
      echo "FAIL $name reach $operator $label: TLC did not complete the reach check"
      cat "$dir/tlc.log"
      fail=1
    fi
  elif [ "$status" -eq 0 ] && grep -q "No error has been found" "$dir/tlc.log"; then
    # Progress lines carry interim counts; the last match is the final one.
    states=$(grep -o '[0-9,]* distinct states found' "$dir/tlc.log" | tail -1)
    echo "PASS $name $label $states"
    passed=$((passed + 1))
    states=${states%% *}
    states=${states//,/}
    total=$((total + ${states:-0}))
  else
    echo "FAIL $name $label: $(grep -m1 "^Error:" "$dir/tlc.log")"
    grep "^Error:" "$dir/tlc.log" | sed -n '2,5p'
    python3 "$HERE/tlc-trace.py" "$dir/tlc.log" || grep -v '^[[:space:]]*$' "$dir/tlc.log" | tail -40
    fail=1
  fi
}

check_reaches() {
  local reach entry operator match label found
  for reach in ${reaches[@]+"${reaches[@]}"}; do
    operator=${reach%%|*}; match=${reach#*|}; found=0
    for entry in ${runs[@]+"${runs[@]}"}; do
      label=${entry%%|*}
      case $label in
        *"$match"*) check_run "$label" "${entry#*|}" "$operator"; found=1; break ;;
      esac
    done
    if [ "$found" -eq 0 ]; then
      echo "FAIL $(basename "$spec" .tla) reach $operator: no run matching '$match'"
      reach_count=$((reach_count + 1))
      fail=1
    fi
  done
}

while IFS= read -r line || [ -n "$line" ]; do
  line=${line%%#*}
  [[ $line =~ [^[:space:]] ]] || continue
  read -r kw rest <<< "$line"
  case $kw in
    spec) check_reaches; spec=$rest; checks=""; reaches=(); runs=() ;;
    check)
      [ -n "$spec" ] || { echo "FAIL check '$rest' before any spec line"; fail=1; continue; }
      read -r kind names <<< "$rest"
      case $kind in
        INVARIANT|INVARIANTS|PROPERTY|PROPERTIES)
          [ -n "$names" ] || { echo "FAIL malformed check '$rest'"; fail=1; continue; } ;;
        *) echo "FAIL malformed check '$rest'"; fail=1; continue ;;
      esac
      checks="$checks${checks:+$'\n'}$rest" ;;
    reach)
      [ -n "$spec" ] || { echo "FAIL reach '$rest' before any spec line"; fail=1; continue; }
      if [[ $rest =~ ^([a-zA-Z_][a-zA-Z_0-9]*)[[:space:]]*\|[[:space:]]*(.*[^[:space:]])[[:space:]]*$ ]]; then
        reaches+=("${BASH_REMATCH[1]}|${BASH_REMATCH[2]}")
      else
        echo "FAIL malformed reach '$rest': expected reach <Operator> | <label-substring>"
        fail=1
      fi ;;
    run)
      [[ $rest == *"|"* ]] || { echo "FAIL run '$rest' has no | before its constants"; fail=1; continue; }
      label=${rest%%|*}; label=${label% }; runs+=("$label|${rest#*|}"); check_run "$label" "${rest#*|}" ;;
    *) echo "FAIL unknown directive: $line"; fail=1 ;;
  esac
done < "$matrix"
check_reaches

[ "$run" -gt 0 ] || { echo "FAIL no run ${only:+matching '$only' }in $matrix"; exit 1; }
summary="SUMMARY $passed of $run runs passed"
[ "$reach_count" -eq 0 ] || summary="$summary, $reach_passed of $reach_count reach checks passed"
echo "$summary, $total distinct states in total"
exit $fail
