#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Ensures one tool is ready; system runtimes must already be installed.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
case ${1:-} in
  tla)
    # shellcheck source=skills/formal-verify/scripts/tlc-tools.sh
    source "$HERE/tlc-tools.sh"
    require_tlc_runtime
    if [ -n "$TLC_JAR_SUPPLIED" ]; then
      tlc_jar_ready
    # A cached JAR that fails the pin is replaced by a fresh download.
    elif ! check_tlc_jar "$TLC_JAR" > /dev/null; then
      command -v curl > /dev/null || { echo "FAIL curl is not on PATH; install curl"; exit 1; }
      mkdir -p "$TLC_CACHE"
      download=$(mktemp "$TLC_CACHE/.tla2tools.XXXXXX")
      trap 'rm -f "$download"' EXIT
      curl --proto '=https' --tlsv1.2 -LSf -o "$download" \
        "https://github.com/tlaplus/tlaplus/releases/download/$TLA_VERSION/tla2tools.jar"
      check_tlc_jar "$download"
      mv -f "$download" "$TLC_JAR"
    fi
    echo "READY TLC $TLC_JAR"
    ;;
  lean)
    dir=${2:?usage: setup.sh lean <lake-project-dir>}
    # shellcheck source=skills/formal-verify/scripts/lean-tools.sh
    source "$HERE/lean-tools.sh"
    # On failure the captured output is the FAIL line.
    toolchain=$(lean_pin "$dir") || { echo "$toolchain"; exit 1; }
    if ! lean_pin_ready "$toolchain"; then
      elan toolchain install "$toolchain"
      lean_pin_ready "$toolchain" || { echo "FAIL $toolchain does not run after installation"; exit 1; }
    fi
    echo "READY Lean $toolchain"
    ;;
  *) echo "usage: setup.sh tla | setup.sh lean <lake-project-dir>"; exit 2 ;;
esac
