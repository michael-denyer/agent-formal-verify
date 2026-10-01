#!/usr/bin/env python3
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
"""Reduce the error trace in a TLC log to what each step changed.

Reads a TLC log (a file argument or stdin), finds the behaviour TLC prints
for an invariant violation, a deadlock or a temporal counter-example, and
prints one block per state: its number and action, then only the variables
whose value differs from the previous state. The first state prints every
variable. A "Back to state" line (a liveness lasso) is printed as is.
Exits 1 when the log holds no trace.

Usage: tlc-trace.py [tlc.log]
"""
import re
import sys
from contextlib import nullcontext

START = ("The behavior up to this point is", "constitutes a counter-example")
STATE = re.compile(r"^State (\d+): <?(.*?)>?$")
LOCATION = re.compile(r" line \d+, col \d+ to line \d+, col \d+ of module \w+$")
# TLC omits the leading conjunction when the spec has one variable.
VAR = re.compile(r"^(?:/\\ )?(\w+) = (.*)$")


def states(lines):
    """Yield (title, {var: value}) per state of the first error trace."""
    lines = (line.rstrip("\n") for line in lines)
    # any() stops on the marker line, so the loop below resumes just after it.
    if not any(marker in line for line in lines for marker in START):
        return
    title, values, var = None, {}, None
    for line in lines:
        if m := STATE.match(line):
            title, values, var = f"state {m[1]}: {LOCATION.sub('', m[2])}", {}, None
        elif line.startswith("Back to state"):
            yield line, {}
        elif title and (m := VAR.match(line)):
            var = m[1]
            values[var] = m[2]
        elif title and var and line.startswith(" "):
            values[var] += "\n" + line
        elif title:
            yield title, values
            title = None
    if title:
        yield title, values


def main():
    with (open(sys.argv[1], encoding="utf-8") if len(sys.argv) > 1 else nullcontext(sys.stdin)) as src:
        prev, found = {}, False
        for title, values in states(src):
            found = True
            print(f"--- {title}")
            for var, value in values.items():
                if prev.get(var) != value:
                    print(f"    {var} = {value}")
            prev = values or prev
    sys.exit(0 if found else 1)


if __name__ == "__main__":
    main()
