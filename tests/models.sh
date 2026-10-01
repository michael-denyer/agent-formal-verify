#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Runs the real TLC and Lean checkers on the bundled examples, then on copies
# with one guard weakened, a hidden axiom or an unowned file, which the
# checkers must reject. Needs the tools that setup.sh prepares; see
# skills/formal-verify/references/setup.md.
#
# Usage: models.sh
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
scripts=$ROOT/skills/formal-verify/scripts
examples=$ROOT/skills/formal-verify/examples
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Prints the output of a checker that must fail, and stops if it passes.
rejected() {
  local out
  if out=$("$@"); then
    echo "FAIL a weakened guard passed: $*"
    exit 1
  fi
  printf '%s\n' "$out"
}

bash "$scripts/setup.sh" tla
bash "$scripts/setup.sh" lean "$examples/lean-template"

bash "$scripts/tlc-matrix.sh" "$examples/tla-template/checks.matrix"
cp -R "$examples/tla-template" "$work/tla"
sed -i.orig 's|next < consumed + Window|next <= consumed + Window|' "$work/tla/BoundedQueue.tla"
rejected bash "$scripts/tlc-matrix.sh" "$work/tla/checks.matrix" window=1 | tee "$work/tla.out"
grep -q "Invariant InWindow is violated" "$work/tla.out"
grep -q "^--- state 2: Claim$" "$work/tla.out"

mkdir "$work/lean"
cp "$examples/lean-template"/{Model.lean,lakefile.toml,lake-manifest.json,lean-toolchain} "$work/lean/"
bash "$scripts/lean-check.sh" "$work/lean"
sed -i.orig 's|if s.next < s.consumed + w then|if s.next ≤ s.consumed + w then|' "$work/lean/Model.lean"
rejected bash "$scripts/lean-check.sh" "$work/lean" | tee "$work/lean.out"
grep -q "did not evaluate to .true." "$work/lean.out"

# A theorem resting on a declared axiom, with no #print axioms line to show it.
cp "$work/lean/Model.lean.orig" "$work/lean/Model.lean"
printf 'axiom cheat : ∀ n : Nat, n < 3\ntheorem bogus : (10 : Nat) < 3 := cheat 10\n' >> "$work/lean/Model.lean"
rejected bash "$scripts/lean-check.sh" "$work/lean" | tee "$work/lean.out"
grep -qF "AXIOMS 'bogus' depends on axioms: #[cheat]" "$work/lean.out"

# A source touched after its build still passes.
cp "$work/lean/Model.lean.orig" "$work/lean/Model.lean"
bash "$scripts/lean-check.sh" "$work/lean"
touch "$work/lean/Model.lean"
bash "$scripts/lean-check.sh" "$work/lean"

# An unfinished proof in a file that no library owns, named like a built module.
mkdir "$work/lean/Scratch"
echo 'theorem unproved : (10 : Nat) < 3 := sorry' > "$work/lean/Scratch/Model.lean"
rejected bash "$scripts/lean-check.sh" "$work/lean" | tee "$work/lean.out"
grep -q "unknown module source path .*/Scratch/Model.lean" "$work/lean.out"

echo "ok: both examples pass; the weakened guards, a hidden axiom and an unowned file are rejected"
