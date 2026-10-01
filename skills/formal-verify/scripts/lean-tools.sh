#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Shared Lean pin lookup; sourcing this file installs nothing.

# Prints the toolchain pin of the Lake project in $1.
lean_pin() {
  command -v elan > /dev/null || { echo "FAIL elan is not on PATH; install elan from https://github.com/leanprover/elan"; return 1; }
  [ -f "$1/lean-toolchain" ] || { echo "FAIL $1 has no lean-toolchain pin"; return 1; }
  tr -d '\r\n' < "$1/lean-toolchain"
}

lean_pin_ready() {
  elan run "$1" lake --version > /dev/null 2>&1
}
