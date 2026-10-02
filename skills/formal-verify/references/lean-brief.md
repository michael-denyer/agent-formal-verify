# Lean modelling brief

Follow this brief to prove one sequential or arithmetic property with Lean 4. Your task gives the source files and line ranges, the functions with their integer types, the property, the model's `<Name>`, the absolute path of the Lake project and the absolute path `<skill-dir>`.

## Files

Write `Model/<Name>.lean` and `Model/<Name>.mutations` in the Lake project. Start from the two `BoundedQueue` files in `<skill-dir>/examples/lean-template/Model/`. Write no other file, so parallel agents share none. Put every declaration in `namespace <Name>`: the checker audits the project's modules together, and equal names clash. The header comment names the source files and line ranges the model follows and each assumption it makes.

Every `.lean` file in the project must belong to a library in the lakefile. With the template's lakefile, that is every file under `Model/`. Add Mathlib only when the arithmetic needs it, since its dependencies can increase setup and build time.

## Model

1. Transcribe the state type and functions with the code's integer widths, rounding, division and order of operations. Use `UInt32` or `Int` with explicit bounds where appropriate, and `Nat` only when values cannot go negative. Keep the source function names and cite `file:line` in doc comments. Preserve any bug during transcription so the model checks the code as written.
2. State the property as a `Prop` with a `Decidable` instance. It may describe an invariant, an encoder round trip, an index bound or states the machine must never reach.
3. Write and evaluate a bounded exhaustive check before proving the theorem. The template's `badPairs` finds states where one step breaks the invariant; `#eval` prints concrete counter-examples and `#guard` fails the build while any exist. Set the bound above the code's slot count, batch size, window and other constants so it includes boundary cases.
4. Prove one theorem per step or function for every size. Split on the guards, use `simp only [...]` to expose arithmetic, then use `omega` or `decide` for a finite type. If a proof needs a fact about the real code that the model lacks, state it as a theorem hypothesis and name it in a comment. Do not declare it as an `axiom`. An unfinished proof may use `sorry`, but the Lean checker reports it as a failure. The checker also fails every declaration that rests on an axiom beyond `propext`, `Classical.choice` and `Quot.sound`, which also rules out `native_decide`.

## Keep the model small

Write each fact once.

- Define the bounded inputs once and filter that list for each property, instead of a new nested loop per property.
- When two proofs share steps, prove the shared fact as one lemma and use it in both.
- Keep mutations in the mutations file. The model has no flag or second definition for a planted bug.

## Check

Stay in the target repository and pass absolute paths:

```shell
bash <skill-dir>/scripts/lean-check.sh <absolute-project-path> Model/<Name>.lean
python3 <skill-dir>/scripts/mutate.py <absolute-project-path>/Model/<Name>.mutations
```

The file name limits the Lean checker to your model, so another agent's unfinished file does not fail your check.

List plausible bugs in the mutations file, such as `<` instead of `≤`, a missing `+ 1` or a swapped argument. The mutation runner checks each on a copy of the file and names the theorems and `#guard` lines that fail. Expect both the bounded search's `#guard` and the theorem. It rejects a mutation that stops a definition compiling. Revise the properties behind each MISSED line.

## Report

Report only after reading the output of both commands. Give:

- the file paths, both commands, the checker's PASS or FAIL line and the mutation runner's output;
- for each counter-example, concrete inputs to the code's function, the source line of the failing arithmetic, a unit test with those inputs, whether shipped callers can pass those inputs, and the proposed fix;
- for a closed proof, its assumptions, including integer widths, bounds and each theorem hypothesis.
