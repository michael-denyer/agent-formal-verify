#!/bin/bash
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
# Shared tool pin and prerequisite checks; nothing here downloads.
TLA_VERSION=v1.7.4
TLA_SHA256=936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88
TLA_RELEASE=https://github.com/tlaplus/tlaplus/releases/tag/$TLA_VERSION
JAVA=${JAVA:-java}
TLC_CACHE=${TLC_CACHE:-$HOME/.cache/tla}
TLC_JAR_SUPPLIED=${TLC_JAR:+yes}
TLC_JAR=${TLC_JAR:-$TLC_CACHE/tla2tools-$TLA_VERSION.jar}

require_tlc_runtime() {
  if ! "$JAVA" -version > /dev/null 2>&1; then
    echo "FAIL $JAVA has no runtime; install a JDK and set JAVA to its java binary"
    return 1
  fi
  command -v python3 > /dev/null || { echo "FAIL python3 is not on PATH; install Python 3"; return 1; }
}

check_tlc_jar() {
  local jar=$1 got
  [ -f "$jar" ] || { echo "FAIL $jar is missing; save tla2tools.jar from $TLA_RELEASE there, or set TLC_JAR"; return 1; }
  if command -v sha256sum > /dev/null; then
    got=$(sha256sum "$jar") || return 1
  elif command -v shasum > /dev/null; then
    got=$(shasum -a 256 "$jar") || return 1
  else
    echo "FAIL install sha256sum or shasum to verify TLC"
    return 1
  fi
  got=${got%% *}
  [ "$got" = "$TLA_SHA256" ] || { echo "FAIL $jar has sha256 $got, want $TLA_SHA256"; return 1; }
}

# A JAR the user supplies is trusted; the cached one must match the pin.
tlc_jar_ready() {
  if [ -n "$TLC_JAR_SUPPLIED" ]; then
    [ -f "$TLC_JAR" ] || { echo "FAIL supplied TLC_JAR $TLC_JAR does not exist"; return 1; }
  else
    check_tlc_jar "$TLC_JAR"
  fi
}
