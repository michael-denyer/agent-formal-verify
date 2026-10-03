#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Usage: kani-check.sh <crate-dir> [<fully-qualified-harness> ...]
set -euo pipefail
[ "$#" -ge 1 ] || { echo "usage: kani-check.sh <crate-dir> [<harness> ...]"; exit 2; }
command -v python3 > /dev/null || { echo "UNAVAILABLE python3 is required; install Python 3"; exit 3; }
exec python3 "$(dirname "$0")/kani.py" check -- "$@"
