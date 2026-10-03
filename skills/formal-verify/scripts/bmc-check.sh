#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Usage: bmc-check.sh <crate-dir> [<fully-qualified-harness> ...]
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
[ "$#" -ge 1 ] || { echo "usage: bmc-check.sh <crate-dir> [<harness> ...]"; exit 2; }
# shellcheck source=skills/formal-verify/scripts/bmc-tools.sh
source "$HERE/bmc-tools.sh"
kani_run --check "$@"
