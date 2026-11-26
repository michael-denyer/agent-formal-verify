# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
"""Read Rust source text: blank its comments and string contents, and find where a bracketed span ends."""
import re
from typing import NamedTuple


class RustSource(NamedTuple):
    uncommented: str
    without_comments_or_strings: str
    literals: list


def rust_masks(source):
    text, mask = list(source), list(source)
    literals = []

    def blank(start, end, *, both):
        for i in range(start, end):
            if source[i] != "\n":
                mask[i] = " "
                if both:
                    text[i] = " "

    i = 0
    while i < len(source):
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = len(source) if end < 0 else end
            blank(i, end, both=True)
            i = end
        elif source.startswith("/*", i):
            depth, start = 0, i
            while i < len(source):
                if source.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif source.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                    if not depth:
                        break
                else:
                    i += 1
            blank(start, i, both=True)
        elif raw := re.compile(r'(?<!\w)[bc]?r(#*)"').match(source, i):
            close = source.find('"' + raw[1], raw.end())
            content_end = len(source) if close < 0 else close
            blank(raw.end(), content_end, both=False)
            i = content_end + 1 + len(raw[1])
            literals.append((raw.start(), min(i, len(source))))
        elif source[i] == '"':
            opening = i
            start = i = i + 1
            while i < len(source) and source[i] != '"':
                i += 2 if source[i] == "\\" else 1
            blank(start, min(i, len(source)), both=False)
            i += 1
            literals.append((opening, min(i, len(source))))
        elif char := re.compile(r"'(?:\\.[^']*|[^'\\])'").match(source, i):
            blank(char.start() + 1, char.end() - 1, both=False)
            i = char.end()
            literals.append(char.span())
        else:
            i += 1
    return RustSource("".join(text), "".join(mask), literals)


def after_closing(mask, opener):
    closer = {"(": ")", "[": "]", "{": "}"}[mask[opener]]
    depth = 0
    for i in range(opener, len(mask)):
        depth += (mask[i] == mask[opener]) - (mask[i] == closer)
        if not depth:
            return i + 1
    raise ValueError(f"unbalanced {mask[opener]} at offset {opener}")
