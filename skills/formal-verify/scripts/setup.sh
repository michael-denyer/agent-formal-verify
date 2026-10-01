#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Ensures one tool is ready; system runtimes must already be installed.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
case ${1:-} in
  tla)
    supplied_jar=${TLC_JAR:-}
    # shellcheck source=skills/formal-verify/scripts/tlc-tools.sh
    source "$HERE/tlc-tools.sh"
    require_tlc_runtime
    if [ -n "$supplied_jar" ]; then
      [ -f "$TLC_JAR" ] || { echo "FAIL supplied TLC_JAR $TLC_JAR does not exist"; exit 1; }
    elif [ -f "$TLC_JAR" ]; then
      check_tlc_jar "$TLC_JAR"
    else
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
    command -v elan > /dev/null || { echo "FAIL elan is not on PATH; install elan from https://github.com/leanprover/elan"; exit 1; }
    [ -f "$dir/lean-toolchain" ] || { echo "FAIL $dir has no lean-toolchain pin"; exit 1; }
    toolchain=$(tr -d '\r\n' < "$dir/lean-toolchain")
    if ! elan run "$toolchain" lake --version > /dev/null 2>&1; then
      elan toolchain install "$toolchain"
      elan run "$toolchain" lake --version > /dev/null
    fi
    echo "READY Lean $toolchain"
    ;;
  *) echo "usage: setup.sh tla | setup.sh lean <lake-project-dir>"; exit 2 ;;
esac
