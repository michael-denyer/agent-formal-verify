#!/usr/bin/env python3
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
"""Record what each model specifies before agents edit it, and compare it afterwards.

A model's surface is a mapping from item name to a canonical value. Every tool
uses one rule to compare surfaces: a removed item or a changed value is a
change, and so is an added item whose kind narrows what is checked.

  .statements  Lean. The toolchain, and each declaration's kind, type hash and value hash.
               Added declarations are allowed.
  .matrix      TLA+. Each run's effective checks and each reach check's selected inputs,
               and the normalized definitions of Spec,
               of each operator a check or reach line names, and of the operators those
               reference through local EXTENDS. Local INSTANCE substitutions retain their whole module tree.
  .rs          Kani. Each qualified harness name with the #[cfg(...)] attributes other
               than cfg(kani), and the #[cfg_attr(..., cfg(...))] ones, on it, its enclosing
               items, the file and each out-of-line mod declaration that leads to the file from a crate root, through
               #[path], and each kani::assume, kani::any_where, kani::cover! and
               #[kani::stub] with its owning free function, under inline modules. Unsupported owners fail. Added covers and harnesses are allowed.
               Added assumes and stubs are changes.
               In a Cargo package, also the recorded harnesses that Kani compiles from the file; Kani must give
               each harness it compiles there a module path that a route the record reads gives, and a harness
               that no longer compiles is a change.

Usage:
  baseline.py record <record-file> <model-file>...   record these files, keep the other entries
  baseline.py compare <record-file>                  exit 1 when a recorded file changed
  baseline.py move <record-file> <old> <new> [--module OLD NEW]
                                                     compare old's entry with new from now on

Compare prints UNCHANGED or CHANGED per file, indented lines for each item that
changed, and a SUMMARY line. Move prints MOVED; it reads only the record, never
the new file, and with --module renames the recorded Kani owners under module
OLD to sit under NEW. Exit codes: 0 unchanged, 1 changed or a record or model
file that fails to parse, 2 usage error.
"""
import argparse
import functools
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

sys.dont_write_bytecode = True

import kani
import runner
import storage
import tlc
from lean_records import read_record as read_lean_record
from rust_source import RustSource, after_closing, rust_masks

FORMAT = 2
NARROWING = {"lean": (), "tla": (), "kani": ("assume", "stub")}
KINDS = {".statements": "lean", ".matrix": "tla", ".rs": "kani"}
STRING = re.compile(r'"(?:\\.|[^"\\])*"', re.DOTALL)


def collapse(text, literals=None):
    if literals is None:
        literals = (match.span() for match in STRING.finditer(text))
    parts, end = [], 0
    for start, stop in literals:
        parts.extend((re.sub(r"\s+", " ", text[end:start]), text[start:stop]))
        end = stop
    parts.append(re.sub(r"\s+", " ", text[end:]))
    return "".join(parts).strip()


class Surface(dict):
    def add(self, name, value=""):
        candidate, count = name, 1
        while candidate in self:
            count += 1
            candidate = f"{name} #{count}"
        self[candidate] = value
        return candidate


def lean_surface(path):
    record = read_lean_record(path)
    surface = Surface()
    surface.add("toolchain", record["toolchain"])
    for entry in record["declarations"]:
        surface.add(f"declaration {entry['name']}", f"{entry['kind']} {entry['typeHash']} {entry['valueHash'] or '-'}")
    return surface


def tla_text(text):
    """Columns can group TLA+ conjunctions and disjunctions across lines."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines) if len(lines) > 1 else collapse("".join(lines))


def blank_tla_comments(text):
    out, i = [], 0
    while i < len(text):
        if text[i] == '"':
            string = STRING.match(text, i)
            if string is None:
                raise ValueError("unterminated TLA+ string")
            out.append(string[0])
            i = string.end()
        elif text.startswith("(*", i):
            start, depth = i, 0
            while i < len(text):
                if text.startswith("(*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*)", i):
                    depth -= 1
                    i += 2
                    if not depth:
                        break
                else:
                    i += 1
            # A following token keeps its source column, even after a nested comment.
            out.append(re.sub(r"[^\s]", " ", text[start:i]))
        elif text.startswith("\\*", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            out.append(" ")
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


DEFINITION = re.compile(r"(?:LOCAL\s+)?(\w*[A-Za-z]\w*)\s*(?:\((?:[^()]|\([^()]*\))*\)|\[(?:[^\[\]]|\[[^\[\]]*\])*\])?\s*==")
MODULE_LEVEL = re.compile(r"-{4,}|={4,}|(?:EXTENDS|VARIABLES?|CONSTANTS?|ASSUME|ASSUMPTION|AXIOM|THEOREM|LEMMA|PROPOSITION|COROLLARY|INSTANCE|RECURSIVE|USE|HIDE)\b")
IDENTIFIER = re.compile(r"\w*[A-Za-z]\w*")
SUBSCRIPT = r"_(\w+|<<[^>]*>>)"
SPEC_ACTIONS = re.compile(rf"\[\]\[[^\]]*\]{SUBSCRIPT}|[WS]F{SUBSCRIPT}\s*\([^()]*\)")
# The prefix that joins a subscript, such as vars in WF_vars, [A]_vars or <<A>>_vars, to one token.
SUBSCRIPT_PREFIX = re.compile(r"\b[WS]F_|\]_|>>_")


def begins_in_column_zero(line):
    return line[:1].strip() != ""


DEFINITION_TOKENS = re.compile(r"\b(?:LET|IN)\b|(?<!=)==(?!=)")


def has_unplaced_definition(code):
    """Return whether a definition can lie outside the column-0 headers that tla_definitions splits on.

    An indented `==` inside an open LET defines a LET-local operator. Any other indented `==`, a line
    that starts with `==`, or a column-0 header while a LET is open can define a module operator.
    """
    open_lets = 0
    for line in code.split("\n"):
        indented = not begins_in_column_zero(line)
        if open_lets and not indented and ("==" in line or MODULE_LEVEL.match(line)):
            return True
        for token in DEFINITION_TOKENS.finditer(line):
            if token[0] == "LET":
                open_lets += 1
            elif token[0] == "IN":
                open_lets = max(open_lets - 1, 0)
            elif not open_lets and (indented or token.start() == 0):
                return True
    return False


def tla_definitions(text):
    found, unreadable, name, lines = {}, set(), None, []
    for line in text.split("\n"):
        if begins_in_column_zero(line):
            match = DEFINITION.match(line)
            header = None if match or MODULE_LEVEL.match(line) or "==" not in line else collapse(line.partition("==")[0])
            if match or header or MODULE_LEVEL.match(line):
                if name:
                    found[name] = tla_text("\n".join(lines))
                name, lines = (match[1] if match else header), ([line] if match or header else [])
                if header:
                    unreadable.add(header)
                continue
        if name:
            lines.append(line)
    if name:
        found[name] = tla_text("\n".join(lines))
    return found, unreadable


EXTENDS = re.compile(r"\bEXTENDS\s+(\w+(?:\s*,\s*\w+)*)")
INSTANCE = re.compile(r"\bINSTANCE\s+(\w+)")
INDENTED_DEFINITION = re.compile(r"^[ \t]*" + DEFINITION.pattern, re.MULTILINE)


def tla_module_surface(directory, spec, operators):
    """Resolve operator references in the module that defines them, including sibling imports."""
    root = Path(spec)
    texts, bodies, scopes, exports = {}, {}, {}, {}
    required, visiting = set(), set()
    whole_modules = False

    def load(path):
        nonlocal whole_modules
        if path in exports:
            return exports[path]
        if path in visiting:
            raise ValueError(f"cyclic TLA+ import at {path}")
        visiting.add(path)
        text = blank_tla_comments(tlc.read_raw(directory / path))
        texts[path] = text
        code = STRING.sub('""', text)
        if has_unplaced_definition(code):
            whole_modules = True
        scope = {}
        for group in EXTENDS.findall(code):
            for name in IDENTIFIER.findall(group):
                sibling = path.with_name(f"{name}.tla")
                if (directory / sibling).is_file():
                    scope.update(load(sibling))
        for name in INSTANCE.findall(code):
            sibling = path.with_name(f"{name}.tla")
            if (directory / sibling).is_file():
                whole_modules = True
                load(sibling)
        definitions, unreadable = tla_definitions(text)
        for name, body in definitions.items():
            key = (path, name)
            bodies[key] = body
            scope[name] = key
        required.update((path, name) for name in unreadable)
        scopes[path] = scope
        exports[path] = {name: key for name, key in scope.items() if not re.match(r"LOCAL\s", bodies[key])}
        visiting.remove(path)
        return exports[path]

    load(root)
    surface = {f"imports {spec}": sorted(str(path) for path in texts if path != root)}
    fallback_names = set()
    if whole_modules:
        fallback_names = {match[1] for text in texts.values() for match in INDENTED_DEFINITION.finditer(text)}
    for name in sorted({"Spec", *operators}):
        if name in scopes[root]:
            required.add(scopes[root][name])
        elif name.rpartition("!")[2] not in fallback_names:
            raise ValueError(f"{name} is named in the {spec} section but no definition was found in it or its local imports")
    if whole_modules:
        # Preserve substitutions and dependencies whose operator scope cannot be resolved.
        for path, text in texts.items():
            surface[f"module text {spec} | {path}"] = tla_text(text)
        return surface

    seen = set()
    while required:
        key = required.pop()
        if key in seen:
            continue
        seen.add(key)
        owner, name = key
        surface[f"definition {owner} {name}"] = bodies[key]
        header, _, body = bodies[key].partition("==")
        body = STRING.sub('""', body)
        if key == scopes[root]["Spec"]:
            # Keep the subscript, such as vars: it decides which steps may stutter and what fairness requires.
            body = SPEC_ACTIONS.sub(lambda form: f" {form[1] or form[2]} ", body)
        body = SUBSCRIPT_PREFIX.sub(" ", body)
        if "[" in header:
            # A function definition such as F[x \in S] == ... references S in its header.
            body = f"{header} {body}"
        required.update(scopes[owner][word] for word in IDENTIFIER.findall(body) if word in scopes[owner])
    return surface


def tla_surface(path):
    surface = Surface()
    surface.add("TLA+ layout version", 1)
    specs = {}
    plan = tlc.MatrixPlan(path)
    tasks = plan.checked_tasks()
    for spec in plan.specs:
        surface.add(f"spec {spec}")
        specs.setdefault(spec, set())
    for task in tasks:
        if task.reach:
            surface.add(f"reach {task.spec} {task.reach.operator} | {collapse(task.reach.match)}",
                        {"run": collapse(task.run.label), "constants": collapse(task.run.constants)})
            specs[task.spec].add(task.reach.operator)
        else:
            run = surface.add(f"run {task.spec} {collapse(task.run.label)}", collapse(task.run.constants))
            for check in task.checks:
                for name in check.names:
                    surface.add(f"check {task.spec} {check.kind} {name} | [{run}]")
                specs[task.spec].update(check.names)
    for spec, operators in specs.items():
        source = path.parent / spec
        if not source.is_file():
            raise ValueError(f"{path}: spec {spec} not found")
        surface.update(tla_module_surface(path.parent, spec, operators))
    return surface


class RustFunction(NamedTuple):
    name: str
    start: int
    keyword: int
    body: int
    end: int


RUST_ITEM = re.compile(r"\b(fn|mod)\s+((?:r#)?\w+)\b")
INCLUDE = re.compile(r"\binclude\s*!$")


def rust_functions(mask):
    """Locate free functions, inline modules, out-of-line `mod name;` declarations and `include!(...)` items outside
    function bodies; leave macro and other item bodies opaque.

    A declaration's or an include's body is its `;`.
    """
    functions, modules, opaque, declarations, includes, counts = [], [], [], [], [], {}

    def add_include(boundary, header, stop, in_body):
        if not in_body and (include := INCLUDE.search(header)):
            semicolon = re.compile(r"\s*;").match(mask, stop)
            includes.append(RustFunction("include", boundary, boundary + include.start(), semicolon.end() - 1 if semicolon else stop - 1, stop))

    def walk(start, end, namespace=(), in_function=False, in_body=False):
        i, boundary, item = start, start, None
        while i < end:
            if match := RUST_ITEM.match(mask, i):
                item = (match[1], match[2], match.start())
                i = match.end()
            elif mask[i] in "([":
                stop = after_closing(mask, i)
                header = mask[boundary:i].rstrip()
                if header.endswith("!"):
                    opaque.append((i, stop))
                    add_include(boundary, header, stop, in_body)
                i = stop
            elif mask[i] == "{":
                stop = after_closing(mask, i)
                header = mask[boundary:i].rstrip()
                macro = header.endswith("!") or bool(re.search(r"\bmacro_rules\s*!\s*\w+\s*$", header))
                if item and not macro:
                    kind, name, keyword = item
                    qualified = (*namespace, name)
                    if kind == "fn":
                        owner = "::".join(qualified)
                        counts[owner] = counts.get(owner, 0) + 1
                        suffix = f"[{counts[owner]}]" if counts[owner] > 1 else ""
                        functions.append(RustFunction(owner + suffix, boundary, keyword, i, stop))
                    else:
                        modules.append(RustFunction("::".join(qualified), boundary, keyword, i, stop))
                    walk(i + 1, stop - 1, qualified, kind == "fn", in_body or kind == "fn")
                elif in_function and not macro and not re.search(r"\b(?:impl|trait|struct|enum|union|extern|macro)\b", header):
                    walk(i + 1, stop - 1, namespace, True, True)
                else:
                    opaque.append((i, stop))
                    add_include(boundary, header, stop, in_body)
                i = boundary = stop
                item = None
            else:
                if mask[i] == ";":
                    if item and item[0] == "mod" and not in_body:
                        declarations.append(RustFunction("::".join((*namespace, item[1])), boundary, item[2], i, i + 1))
                    boundary, item = i + 1, None
                i += 1

    walk(0, len(mask))
    return functions, modules, opaque, declarations, includes


KANI_ATTRIBUTE = r"#\s*\[\s*(?:cfg_attr\s*\(\s*kani\s*,\s*)?kani\s*::\s*"
MACROS = (
    ("assume", re.compile(r"\bkani\s*::\s*assume\s*\(")),
    ("assume", re.compile(r"\bkani\s*::\s*any_where\s*(?:::\s*<[^<>]*(?:<[^<>]*>[^<>]*)*>\s*)?\(")),
    ("cover", re.compile(r"\bkani\s*::\s*cover\s*!\s*\(")),
    ("stub", re.compile(KANI_ATTRIBUTE + r"stub\s*\(")),
)
PROOF = re.compile(KANI_ATTRIBUTE + r"proof(?:_for_contract\s*\([^)]*\))?\s*\)?\s*\]")
KANI_TOKEN = re.compile(r"\bkani\s*::\s*(?:assume|any_where|cover|stub|proof)\w*\b")
ATTRIBUTE = re.compile(r"#\s*(!\s*)?\[")
INNER_ATTRIBUTE = re.compile(r"[\s\ufeff]*#\s*!\s*\[")
RENAMING_IMPORT = re.compile(r"\buse\s+[^;]*?(?<![\w:])(?:::\s*)?kani\b[^;]*?(?:\bas\b|\*|\b(?:assume|any_where|cover|stub|proof)\w*\b)|\bextern\s+crate\s+kani\s+as\b")


def applies_cfg(attribute):
    """Return whether a compact `cfg_attr(predicate, attribute, ...)` applies a cfg or a module path in its own
    attribute list."""
    arguments, depth, start = [], 0, len("cfg_attr(")
    for i in range(start, len(attribute) - 1):
        depth += (attribute[i] in "([{") - (attribute[i] in ")]}")
        if attribute[i] == "," and not depth:
            arguments.append(attribute[start:i])
            start = i + 1
    arguments.append(attribute[start:-1])
    return any(argument.startswith(("cfg(", "path=")) or argument.startswith("cfg_attr(") and applies_cfg(argument) for argument in arguments[1:])


def outer_attributes(source, start, keyword):
    """Yield the contents of each top-level outer attribute between start and keyword; skip inner attributes."""
    mask = source.without_comments_or_strings
    while attribute := ATTRIBUTE.search(mask, start, keyword):
        opener = attribute.end() - 1
        start = after_closing(mask, opener)
        if not attribute[1]:
            yield rust_masks(source.uncommented[opener + 1:start - 1])


def cfg_guards(source, items):
    """Return the cfg attributes other than cfg(kani), and the cfg_attr ones whose attribute list applies a cfg or a
    module path, on each (start, keyword, body) item, between its start and its fn or mod keyword, and at the start
    of its body.

    A body of -1 stands for the file, which has only inner attributes, and a body at a `;` for an out-of-line `mod`
    declaration, which has none. An attribute nested inside another attribute's tokens is not read.
    """
    text, mask = source.uncommented, source.without_comments_or_strings
    guards = []

    def read(attribute):
        compact = re.sub(r"\s+", "", attribute.without_comments_or_strings)
        if compact.startswith("cfg(") and compact != "cfg(kani)" or compact.startswith("cfg_attr(") and applies_cfg(compact):
            guards.append(collapse(attribute.uncommented, attribute.literals))

    for start, keyword, body in items:
        if body >= 0:
            for attribute in outer_attributes(source, start, keyword):
                read(attribute)
        if body >= 0 and mask[body] == ";":
            continue
        inner = body + 1
        while attribute := INNER_ATTRIBUTE.match(mask, inner):
            opener = attribute.end() - 1
            inner = after_closing(mask, opener)
            read(rust_masks(text[opener + 1:inner - 1]))
    return " ".join(guards)


PATH_ATTRIBUTE = re.compile(r"\bpath\s*=\s*")


def module_paths(source, item, file):
    """Return the paths that `#[path = "..."]` sets on a module item, and those that a cfg_attr may set."""
    paths, conditional = [], []
    for attribute in outer_attributes(source, item.start, item.keyword):
        compact = re.sub(r"\s+", "", attribute.without_comments_or_strings)
        if not compact.startswith(("path=", "cfg_attr(")):
            continue
        for setting in PATH_ATTRIBUTE.finditer(attribute.without_comments_or_strings):
            value = string_value(next((attribute.uncommented[begin:end] for begin, end in attribute.literals if begin == setting.end()), ""))
            if value is None:
                line = source.without_comments_or_strings.count("\n", 0, item.start) + 1
                raise ValueError(f"{file}:{line}: cannot read the path in '{collapse(attribute.uncommented, attribute.literals)}'; write it as a string without escapes")
            (paths if compact.startswith("path=") else conditional).append(value)
    return paths, conditional


def string_value(literal):
    """Return the value of a Rust string literal without escapes, or None."""
    plain = re.fullmatch(r'r(#*)"(.*)"\1', literal, re.DOTALL) or re.fullmatch(r'"([^"\\]*)"', literal)
    return plain[plain.lastindex] if plain else None


class RustFile(NamedTuple):
    source: RustSource
    modules: list
    declarations: list
    includes: list


def parse_rust(path):
    source = rust_masks(path.read_text(encoding="utf-8"))
    _, modules, _, declarations, includes = rust_functions(source.without_comments_or_strings)
    return RustFile(source, modules, declarations, includes)


def enclosing_modules(parsed, item):
    return sorted((module for module in parsed.modules if module.start <= item.start < module.end), key=lambda module: module.start)


def module_files(file, owner, parsed, declaration):
    """Yield each file that an out-of-line `mod` declaration in file may load, by rustc's rules, and whether that
    file owns its directory, as a crate root, a mod.rs or a `#[path]` file does."""
    states = [(file.parent, file.parent if owner else file.parent / file.stem)]
    for module in enclosing_modules(parsed, declaration):
        paths, conditional = module_paths(parsed.source, module, file)
        name = module.name.rsplit("::", 1)[-1].removeprefix("r#")
        states = [(child, child) for directory, prefix in states for child in ([] if paths else [prefix / name]) + [directory / path for path in paths + conditional]]
    paths, conditional = module_paths(parsed.source, declaration, file)
    name = declaration.name.rsplit("::", 1)[-1].removeprefix("r#")
    for directory, prefix in states:
        if not paths:
            yield prefix / f"{name}.rs", False
            yield prefix / name / "mod.rs", True
        for path in paths + conditional:
            yield directory / path, True


def crate_roots(path):
    """Return the crate roots whose module trees may hold path, and those of them that Cargo names, or None for a
    file in no crate.

    They are the lib.rs and main.rs in the nearest directory above path that holds either and, in the Cargo package
    of the nearest directory above path with a Cargo.toml, Cargo's target files and each `.rs` path that Cargo.toml
    names.
    """
    marker = next((folder for folder in path.parents if (folder / "lib.rs").is_file() or (folder / "main.rs").is_file()), None)
    package = next((folder for folder in path.parents if (folder / "Cargo.toml").is_file()), None)
    if marker is None and package is None:
        return None
    markers = [marker / "lib.rs", marker / "main.rs"] if marker else []
    named = []
    if package:
        named += [package / "src/lib.rs", package / "src/main.rs"]
        for folder in ("src/bin", "tests", "examples", "benches"):
            named += sorted((package / folder).glob("*.rs")) + sorted((package / folder).glob("*/main.rs"))
        manifest = (package / "Cargo.toml").read_text(encoding="utf-8")
        named += [package / file for file in re.findall(r"""\bpath\s*=\s*["']([^"']+\.rs)["']""", manifest)]
    return tuple(dict.fromkeys(root.resolve() for root in markers + named if root.is_file())), {root.resolve() for root in named}


CONCAT = re.compile(r"(?:\w+\s*::\s*)*concat\s*!\s*[(\[{]")
MANIFEST_DIR = re.compile(r'(?:\w+\s*::\s*)*env\s*!\s*[(\[{]\s*"CARGO_MANIFEST_DIR"\s*,?\s*[)\]}]')


def include_path(argument, file, package):
    """Return the file that the argument of an `include!` in file names, or None when the argument is neither a
    string without escapes nor a `concat!` of such strings and `env!("CARGO_MANIFEST_DIR")`, which is package,
    the directory of the Cargo.toml of the crate being compiled.

    Raises:
        ValueError: The argument uses `env!("CARGO_MANIFEST_DIR")` and package is None.
    """
    argument = argument.strip()
    if (value := string_value(argument)) is not None:
        return file.parent / value
    mask = rust_masks(argument).without_comments_or_strings
    if not (concat := CONCAT.match(mask)) or after_closing(mask, concat.end() - 1) != len(mask):
        return None
    parts, start, depth = [], concat.end(), 0
    for i in range(start, len(mask) - 1):
        depth += (mask[i] in "([{") - (mask[i] in ")]}")
        if mask[i] == "," and not depth:
            parts.append(argument[start:i].strip())
            start = i + 1
    parts.append(argument[start:-1].strip())
    pieces = []
    for part in filter(None, parts):
        if (value := string_value(part)) is not None:
            pieces.append(value)
        elif MANIFEST_DIR.fullmatch(part):
            if package is None:
                raise ValueError('no Cargo.toml above the crate root sets env!("CARGO_MANIFEST_DIR"), so the record cannot tell which file it reads')
            pieces.append(str(package))
        else:
            return None
    return file.parent / "".join(pieces)


class Route(NamedTuple):
    """A route to a Kani harness file: its crate root, the guards on its steps, outermost first, and the module path
    that it gives the file's items, "" at a crate root."""
    root: Path
    guards: str
    module: str


class RouteReader:
    """Read the routes that lead to Kani harness files from their crate roots.

    It parses each file and walks each crate's module tree once, so make one per run: it does not see a file that
    changes after it has read it.
    """

    def __init__(self):
        self.parsed, self.trees = {}, {}

    def parse(self, path):
        if path not in self.parsed:
            self.parsed[path] = parse_rust(path)
        return self.parsed[path]

    def module_tree(self, roots):
        """Return the module declarations that lead to each file the crate roots reach, as {file: {(declarer,
        declaration)}}, and the message for each reached file or declaration that could not be read.

        An `include!("...")` item outside function bodies leads to the file it names, relative to the including file,
        which declares modules as a file that owns its directory does, whatever inline modules hold the include.
        """
        if roots not in self.trees:
            edges, broken, seen = {}, [], set()
            work = [(root, True, next((folder for folder in root.parents if (folder / "Cargo.toml").is_file()), None)) for root in roots]
            while work:
                file, owner, package = work.pop()
                if (file, owner, package) in seen:
                    continue
                seen.add((file, owner, package))
                try:
                    parsed = self.parse(file)
                except ValueError as error:
                    broken.append(f"{file}: {error}")
                    continue
                for declaration in parsed.declarations:
                    try:
                        targets = list(module_files(file, owner, parsed, declaration))
                    except ValueError as error:
                        broken.append(str(error))
                        continue
                    for target, owns in targets:
                        if target.is_file():
                            target = target.resolve()
                            edges.setdefault(target, set()).add((file, declaration))
                            work.append((target, owns, package))
                for include in parsed.includes:
                    invocation = rust_masks(parsed.source.uncommented[include.keyword:include.end])
                    line = parsed.source.without_comments_or_strings.count("\n", 0, include.keyword) + 1
                    shown = collapse(invocation.uncommented, invocation.literals)
                    try:
                        target = include_path(invocation.uncommented[invocation.without_comments_or_strings.index("!") + 1:].strip()[1:-1], file, package)
                    except ValueError as error:
                        broken.append(f"{file}:{line}: cannot read the path in '{shown}': {error}")
                        continue
                    if target is None:
                        broken.append(f"{file}:{line}: cannot read the path in '{shown}'; write it as a string without escapes, or as concat! of such strings and env!(\"CARGO_MANIFEST_DIR\")")
                    elif target.is_file():
                        target = target.resolve()
                        edges.setdefault(target, set()).add((file, include))
                        work.append((target, True, package))
            self.trees[roots] = edges, broken
        return self.trees[roots]

    def routes(self, path):
        """Return the routes that lead to path from its crate roots, sorted. A crate root is one route without guards,
        since its own crate always compiles it, unless it is a lib.rs or main.rs that Cargo does not name and another
        file declares, which makes it a module. A file in no crate is one such route too, as Kani compiles it alone.

        It follows each out-of-line `mod` declaration from the crate roots by rustc's rules, including
        `#[path = "..."]` and each path that a cfg_attr may set, and each `include!("...")` item outside function
        bodies. It does not expand macros, so a declaration that a macro holds or builds is not a route it reads;
        `compiled_problems` checks those against the harnesses that Kani compiles.

        Raises:
            ValueError: No route that it reads reaches path. The message names each reached file, declaration and
                `include!` that it could not read.
        """
        if (crates := crate_roots(path)) is None:
            return [Route(path, "", "")]
        roots, named = crates
        edges, broken = self.module_tree(roots)
        if path in roots and path not in edges:
            return [Route(path, "", "")]
        if path not in edges:
            unread = "".join(f"; {message}" for message in broken)
            raise ValueError(f"{path}: no module declaration that the record can read leads to this file from a crate root; declare it with `mod <name>;` or `#[path = \"...\"]` outside macros and function bodies, in a file that a crate root reaches{unread}")

        def walk(file, visiting):
            root = file in named or file in roots and all(declarer == file for declarer, _ in edges.get(file, ()))
            found = [Route(file, "", "")] if root else []
            for declarer, declaration in edges.get(file, ()):
                if declarer in visiting:
                    continue
                parsed = self.parse(declarer)
                enclosing = enclosing_modules(parsed, declaration)
                items = [(0, 0, -1)] + [(module.start, module.keyword, module.body) for module in enclosing] + [(declaration.start, declaration.keyword, declaration.body)]
                guards = cfg_guards(parsed.source, items)
                # An included file's items sit in the modules around the include!; a declared file's in its module.
                local = (enclosing[-1].name if enclosing else "") if declaration in parsed.includes else declaration.name
                found += [Route(route.root, " ".join(filter(None, (route.guards, guards))), "::".join(filter(None, (route.module, local))))
                          for route in walk(declarer, visiting | {declarer})]
            return found

        return sorted(walk(path, {path}))


def route_label(path, routes):
    """Return the guards that routes give path's items, as the record holds them: one route's own guards, or for more
    than one route `routes(...)` with each route as its crate root's path relative to path's directory, a colon and
    its guards, or `unguarded` for a route without any, sorted and separated by `; `."""
    found = sorted((os.path.relpath(route.root, path.parent), route.guards) for route in routes)
    if len(found) == 1:
        return found[0][1]
    labelled = "; ".join(f"{root}: {guards or 'unguarded'}" for root, guards in found)
    return f"routes({labelled})"


def kani_surface(path, reader):
    source = rust_masks(path.read_text(encoding="utf-8"))
    text, mask = source.uncommented, source.without_comments_or_strings
    if renaming := RENAMING_IMPORT.search(mask):
        raise ValueError(f"{path}: '{collapse(renaming[0])}' brings a Kani assumption, cover, stub or harness attribute in under another name; write each as kani::<name> so the record can read it")
    functions, modules, opaque, _, _ = rust_functions(mask)
    declared = route_label(path, reader.routes(path))

    def owner_at(position, *, attribute=False):
        if not any(start <= position < end for start, end in opaque):
            for function in reversed(functions):
                if function.start <= position < function.end and (position < function.body if attribute else position > function.body):
                    return function
        line = mask.count("\n", 0, position) + 1
        raise ValueError(f"{path}:{line}: cannot identify a function owner; write Kani forms in free functions under inline modules, outside macro definitions and impl or trait bodies")

    surface = Surface()
    spans, read = [], []
    for kind, pattern in MACROS:
        for match in pattern.finditer(mask):
            end = after_closing(mask, match.end() - 1)
            read.append((match.start(), end))
            argument = rust_masks(text[match.end():end - 1])
            owner = owner_at(match.start(), attribute=kind == "stub").name
            spans.append((match.start(), f"{kind} {collapse(argument.uncommented, argument.literals)} in {owner}", ""))
    for match in PROOF.finditer(mask):
        read.append(match.span())
        harness = owner_at(match.start(), attribute=True)
        enclosing = sorted((item for item in functions + modules if item.start <= harness.start and harness.end <= item.end), key=lambda item: item.start)
        guards = " ".join(filter(None, (declared, cfg_guards(source, [(0, 0, -1)] + [(item.start, item.keyword, item.body) for item in enclosing]))))
        spans.append((match.start(), f"harness {harness.name}", guards))
    for token in KANI_TOKEN.finditer(mask):
        if not any(start <= token.start() < end for start, end in read):
            line = mask.count("\n", 0, token.start()) + 1
            raise ValueError(f"{path}:{line}: '{collapse(token[0])}' is in a form the record cannot read; write kani::assume(...), kani::any_where(...), kani::cover!(...), #[kani::stub(...)] or #[kani::proof], alone or under #[cfg_attr(kani, ...)]")
    for _, item, guards in sorted(spans):
        surface.add(item, guards)
    return surface


@functools.cache
def checker():
    return kani.Kani()


@functools.cache
def compiled_in(package):
    """Return each harness that Kani compiles in the Cargo package at package.

    Raises:
        ValueError: Kani is not installed, or cannot compile the package.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="baseline-kani-", dir=storage.ensure_temp_root()) as work:
            return tuple(kani.compiled(package, Path(work), checker()))
    except (kani.CheckError, runner.Unavailable) as error:
        raise ValueError(f"cannot ask Kani which harnesses it compiles in {package}: {error}") from error


# A closure or a `const _` block puts an anonymous segment in Kani's name for a harness inside it.
ANONYMOUS = re.compile(r"\{\w+#\d+\}|_")


def item_path(name):
    return "::".join(part.removeprefix("r#") for part in name.split("::") if not ANONYMOUS.fullmatch(part))


def route_owner(name, modules, owners):
    """Return the owner in owners, keyed by item_path, that Kani's harness name gives under one of modules, or None.

    The name must start with the module path itself. Anonymous segments are dropped only after it, since no route
    that the record reads runs through a closure or a `const _` block.
    """
    parts = [part.removeprefix("r#") for part in name.split("::")]
    for module in modules:
        prefix = [part.removeprefix("r#") for part in module.split("::")] if module else []
        if parts[:len(prefix)] == prefix and (owner := owners.get(item_path("::".join(parts[len(prefix):])))):
            return owner
    return None


def compiled_problems(path, surface, reader, recorded=None):
    """Return the lines on which the harnesses that Kani compiles from path disagree with surface and recorded, and
    surface's harnesses that it compiles, as `harness <owner>` items, or None for them when no Cargo package holds
    path.

    Each harness that Kani compiles from path must be one of surface's harnesses under the module path of a route
    that the record reads. A harness in recorded that Kani compiles on no route is a harness that was switched off.

    Raises:
        ValueError: Kani is not installed, or cannot compile the package.
    """
    package = next((folder for folder in path.parents if (folder / "Cargo.toml").is_file()), None)
    if package is None:
        return [f"  not compiled {item}" for item in recorded or ()], None
    names = {harness.name for harness in compiled_in(package) if harness.source == path}
    modules = {route.module for route in reader.routes(path)}
    owners = {re.sub(r"\[\d+\]$", "", KANI_KEY.fullmatch(item)[2]) for item in surface if item.startswith("harness ")}
    found = {name: route_owner(name, modules, {item_path(owner): owner for owner in owners}) for name in names}
    lines = [f"  FAIL Kani compiles {name} from this file, but no route that the record reads gives that name; declare "
             "the module with `mod <name>;` or `#[path = \"...\"]` outside macros and function bodies"
             for name, owner in sorted(found.items()) if owner is None]
    compiled = sorted({f"harness {owner}" for owner in found.values() if owner is not None})
    lines += [f"  not compiled {item}" for item in sorted(set(recorded or ()) - set(compiled))]
    return lines, compiled


SURFACES = {"lean": lean_surface, "tla": tla_surface, "kani": kani_surface}


def digest(surface):
    return hashlib.sha256(json.dumps(surface, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def read_record(path):
    record = json.loads(path.read_text(encoding="utf-8"))
    models = record.get("models") if isinstance(record, dict) else None
    if not isinstance(models, dict) or record.get("format") != FORMAT:
        raise ValueError(f"{path}: unsupported record format; run record with a new record file")
    for model, entry in models.items():
        if not isinstance(entry, dict) or entry.get("kind") not in SURFACES or not isinstance(entry.get("surface"), dict):
            raise ValueError(f"{path}: malformed entry for {model}")
        compiled = entry.get("compiled", [])
        if not isinstance(compiled, list) or not all(isinstance(name, str) for name in compiled):
            raise ValueError(f"{path}: malformed entry for {model}")
    return models


def write_record(path, models):
    path.parent.mkdir(parents=True, exist_ok=True)
    runner.atomic_write(path, json.dumps({"format": FORMAT, "models": models}, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def record(record_path, files):
    for file in files:
        if file.suffix not in KINDS:
            print(f"usage: {file} has no model surface; expected one of {', '.join(KINDS)}")
            return 2
    models = read_record(record_path) if record_path.exists() else {}
    updates, notes, reader = {}, {}, RouteReader()
    for file in files:
        kind = KINDS[file.suffix]
        surface = kani_surface(file.resolve(), reader) if kind == "kani" else SURFACES[kind](file.resolve())
        entry = {"kind": kind, "digest": digest(surface), "surface": surface}
        if kind == "kani":
            # A harness that no longer compiles is recorded from its text alone; compare asks Kani again.
            try:
                problems, names = compiled_problems(file.resolve(), surface, reader)
            except ValueError as error:
                notes[str(file.resolve())] = f"  not checked against Kani: {error}"
            else:
                if problems:
                    raise ValueError(f"{file.resolve()}: " + "; ".join(problem.strip().removeprefix("FAIL ") for problem in problems))
                if names is not None:
                    entry["compiled"] = names
        updates[str(file.resolve())] = entry
    for model, entry in updates.items():
        print(f"RECORDED {model} {entry['digest']}")
        previous = models.get(model, {}).get("digest")
        if previous and previous != entry["digest"]:
            print(f"  previous {previous}")
        if model in notes:
            print(notes[model])
    write_record(record_path, {**models, **updates})
    return 0


KANI_KEY = re.compile(r"(harness |(?:assume|cover|stub) .* in )(\S+)( #\d+)?", re.DOTALL)


def renamed(surface, old_module, new_module):
    """Rewrite each Kani owner under old_module to sit under new_module, where `crate` is the file's root."""
    old, new = ([] if path == "crate" else path.split("::") for path in (old_module, new_module))
    result = {}
    for name, value in surface.items():
        head, owner, duplicate = KANI_KEY.fullmatch(name).groups()
        parts = owner.split("::")
        if parts[:len(old)] == old:
            owner = "::".join(new + parts[len(old):])
        result[f"{head}{owner}{duplicate or ''}"] = value
    if len(result) != len(surface):
        raise ValueError(f"renaming {old_module} to {new_module} merges recorded items")
    return result


def move(record_path, old_file, new_file, module):
    models = read_record(record_path) if record_path.is_file() else {}
    old, new = str(old_file.resolve()), str(new_file.resolve())
    if old not in models:
        print(f"usage: {old} has no record entry; record it before the move")
        return 2
    kind = models[old]["kind"]
    if KINDS.get(new_file.suffix) != kind:
        print(f"usage: {new} is not a {kind} model file")
        return 2
    if module and kind != "kani":
        print("usage: --module applies only to a Kani harness file")
        return 2
    entry = models.pop(old)
    surface, compiled = entry["surface"], entry.get("compiled")
    if module:
        surface = renamed(surface, *module)
        compiled = compiled and list(renamed(dict.fromkeys(compiled), *module))
    if new in models:
        if overlap := surface.keys() & models[new]["surface"].keys():
            raise ValueError(f"{new} already records {', '.join(sorted(overlap))}")
        surface = {**models[new]["surface"], **surface}
        # The merged entry holds Kani's list only when both entries were checked against Kani at record.
        compiled = [*models[new]["compiled"], *compiled] if "compiled" in models[new] and compiled is not None else None
    models[new] = {"kind": kind, "digest": digest(surface), "surface": surface}
    if compiled is not None:
        models[new]["compiled"] = sorted(compiled)
    write_record(record_path, models)
    print(f"MOVED {old} -> {new}")
    return 0


def differences(kind, old, new):
    lines = []
    if kind == "tla" and not any(name.startswith("imports ") for name in old):
        lines.append("  previous baseline did not track imported modules; review and record this matrix again")
    if kind == "tla" and "TLA+ layout version" not in old:
        lines.append("  previous baseline did not preserve TLA+ layout; review and record this matrix again")
    for name in old:
        if name not in new:
            lines.append(f"  removed {name}")
        elif old[name] != new[name]:
            lines += [f"  changed {name}", f"    old: {old[name]}", f"    new: {new[name]}"]
    lines += [f"  added {name}" for name in new if name not in old and name.split(" ", 1)[0] in NARROWING[kind]]
    return lines


def compare(record_path):
    if not record_path.is_file():
        print(f"usage: record file {record_path} does not exist; run record first")
        return 2
    models = read_record(record_path)
    changed, reader = 0, RouteReader()
    for model, entry in models.items():
        try:
            if not Path(model).is_file():
                lines = ["  file is missing"]
            else:
                surface = kani_surface(Path(model), reader) if entry["kind"] == "kani" else SURFACES[entry["kind"]](Path(model))
                lines = differences(entry["kind"], entry["surface"], surface)
                if entry["kind"] == "kani":
                    try:
                        problems, names = compiled_problems(Path(model), surface, reader, entry.get("compiled"))
                        lines += problems
                        if names is not None and "compiled" not in entry:
                            lines.append("  not checked against Kani at record, so compare cannot see a harness that "
                                         "stopped compiling on a route that the record does not read")
                    except ValueError as error:
                        lines.append(f"  FAIL {error}")
        except (OSError, ValueError, KeyError, TypeError) as error:
            lines = [f"  FAIL {error}"]
        changed += bool(lines)
        print(f"{'CHANGED' if lines else 'UNCHANGED'} {model}")
        if lines:
            print("\n".join(lines))
    print(f"SUMMARY {len(models) - changed} unchanged, {changed} changed")
    return int(changed > 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    recording = commands.add_parser("record", help="record or update the entries for these model files")
    recording.add_argument("record_file", type=Path)
    recording.add_argument("models", nargs="+", type=Path)
    commands.add_parser("compare", help="compare every recorded model with its file").add_argument("record_file", type=Path)
    moving = commands.add_parser("move", help="move a model's recorded entry to the file it moved to")
    moving.add_argument("record_file", type=Path)
    moving.add_argument("old_file", type=Path)
    moving.add_argument("new_file", type=Path)
    moving.add_argument("--module", nargs=2, metavar=("OLD", "NEW"),
                        help="the Kani harnesses moved from module OLD to NEW; crate names the file's root")
    arguments = parser.parse_args()
    if arguments.command == "record":
        return record(arguments.record_file, arguments.models)
    if arguments.command == "move":
        return move(arguments.record_file, arguments.old_file, arguments.new_file, arguments.module)
    return compare(arguments.record_file)


def guarded_main():
    try:
        return main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"FAIL baseline: {error}")
        return 1


if __name__ == "__main__":
    # The runner turns a stopping signal into an exception, so Kani's work directory is removed before the exit.
    runner.run(guarded_main)
