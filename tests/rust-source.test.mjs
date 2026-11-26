// Copyright (c) 2026 Michael Denyer
// SPDX-License-Identifier: GPL-3.0-only
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { scripts } from "./helpers.mjs";

// Evaluate a Python expression over the JSON value `input` with rust_source imported, and return its value as JSON,
// or { error } for a ValueError.
function python(input, expression) {
  const script = [
    "import json, sys",
    `sys.path.insert(0, ${JSON.stringify(scripts)})`,
    "import rust_source",
    "input = json.loads(sys.argv[1])",
    "try:",
    `    value = ${expression}`,
    "except ValueError as error:",
    "    value = {'error': str(error)}",
    "print(json.dumps(value))",
  ].join("\n");
  const result = spawnSync("python3", ["-B", "-c", script, JSON.stringify(input)], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

// [uncommented, without_comments_or_strings, literal spans] for source.
const masks = (source) => python(source, "rust_source.rust_masks(input)");

test("rust_masks blanks comments, nested block comments included, in both texts and keeps every newline and offset", () => {
  assert.deepEqual(masks("a // c\nb /* x /* y */ z */ c"), ["a     \nb                   c", "a     \nb                   c", []]);
  assert.deepEqual(masks("/* one\ntwo */x"), ["      \n      x", "      \n      x", []]);
  // A comment that the input ends inside runs to the end.
  assert.deepEqual(masks("a // tail"), ["a        ", "a        ", []]);
  assert.deepEqual(masks("a /* open { "), ["a           ", "a           ", []]);
});

test("rust_masks blanks string and char contents in the mask alone and records each literal's span", () => {
  assert.deepEqual(masks('let s = "a \\" b // no"; f()'), ['let s = "a \\" b // no"; f()', 'let s = "            "; f()', [[8, 22]]]);
  // A lifetime is not a char literal.
  assert.deepEqual(masks("let c = 'x'; let q = '\\''; fn f<'a>(x: &'a u8) {}"), [
    "let c = 'x'; let q = '\\''; fn f<'a>(x: &'a u8) {}",
    "let c = ' '; let q = '  '; fn f<'a>(x: &'a u8) {}",
    [[8, 11], [21, 25]],
  ]);
  assert.deepEqual(masks('x = "unterminated'), ['x = "unterminated', 'x = "            ', [[4, 17]]]);
  assert.deepEqual(masks('b"x y"'), ['b"x y"', 'b"   "', [[1, 6]]]);
  assert.deepEqual(masks('"a\nb"'), ['"a\nb"', '" \n "', [[0, 5]]]);
  assert.deepEqual(masks("'\\n'"), ["'\\n'", "'  '", [[0, 4]]]);
});

test("rust_masks ends a raw string only at a quote with its own hashes, and a quote inside a comment opens no string", () => {
  assert.deepEqual(masks('r#"a " b"# br##"x"#y"## cr"z" end'), ['r#"a " b"# br##"x"#y"## cr"z" end', 'r#"     "# br##"    "## cr" " end', [[0, 10], [11, 23], [24, 29]]]);
  assert.deepEqual(masks('/* "open */ "// kept"'), ['            "// kept"', '            "       "', [[12, 21]]]);
  assert.deepEqual(masks('r#"open " x'), ['r#"open " x', 'r#"        ', [[0, 11]]]);
  // An identifier that ends in r is not a raw string's prefix.
  assert.deepEqual(masks('bar"q"'), ['bar"q"', 'bar" "', [[3, 6]]]);
});

test("after_closing returns the offset after an opener's closer, skipping nested brackets and those in strings", () => {
  const source = 'f(a, [b], {c}) + g(")")';
  const offsets = python({ source, openers: [1, 5, 10, 18] }, "[rust_source.after_closing(rust_source.rust_masks(input['source']).without_comments_or_strings, at) for at in input['openers']]");
  assert.deepEqual(offsets, [14, 8, 13, 23]);
  // Only the opener's own kind of bracket counts.
  assert.equal(python("(a]b)", "rust_source.after_closing(input, 0)"), 5);
  assert.deepEqual(python("{ (", "rust_source.after_closing(input, 0)"), { error: "unbalanced { at offset 0" });
});
