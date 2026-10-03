#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
kani_run() {
  command -v python3 >/dev/null 2>&1 || { echo "UNAVAILABLE python3 is required; install Python 3"; return 3; }
  python3 "$(dirname "${BASH_SOURCE[0]}")/bmc.py" "$@"
}
