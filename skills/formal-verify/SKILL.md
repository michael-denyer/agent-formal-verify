---
name: formal-verify
description: "Model-check thread protocols with TLA+ and TLC, and prove sequential invariants with Lean 4. Map counter-examples to source locations, reproductions and fixes, and keep the models in CI. Use for /agent-formal-verify:formal-verify, formal verification, model checking, Lean proofs, or concurrency bugs that runtime tests cannot reproduce."
---

# Formal verify

Model individual protocols or sequential invariants. Map counter-examples to events and locations in the source code. Before reporting a pass, confirm that each checked property detects a relevant mutation and that the Lean checker passes.

Choose tools according to the target:

| What can go wrong | Tool | Why |
| --- | --- | --- |
| Thread interleavings that lose wakeups, free resources twice, deliver items twice or out of order, block close, or report errors on the wrong thread | TLA+ with TLC | TLC explores the states of a small instance and reports counter-examples |
| Arithmetic or sequential transitions that break bounds, invariants or encoder round trips, or reach states the code assumes impossible | Lean 4 | Evaluate bounded instances, then prove the property for every size |

A thread protocol that depends on arithmetic such as `slot = item mod window` needs both tools. Use TLA+ for the interleavings with the arithmetic as a constant, and Lean for the arithmetic.

## 1. Pick the targets

Search with `rg` for `pthread_cond`, `pthread_mutex`, `atomic_`, `std::condition_variable`, `sync.Cond`, `chan`, `select`, `asyncio.Condition`, `Semaphore`, `atexit` and `setjmp`. Also search for protocol state names such as `ready`, `stop`, `done`, `finished`, `pending`, `inflight`, `head`, `tail` and `exiting`. Classify each hit:

- Model hand-written protocols, including hand-overs, bounded pipelines, queues with ordered output, shutdown, cleanup, retry and lease loops.
- Leave data-parallel loops over disjoint indices to ThreadSanitizer or the language's race detector, and say so in the reply.
- For library-owned channels or executors, model the calling code.
- Use Lean for arithmetic the protocol or output depends on. Examples include slot and splice indices, window bounds, sizes computed and checked differently, and encoder round trips. Search for `%`, `- 1`, `+ 1`, `>>`, `overlap`, `splice` and `offset` near the protocol's data.

Write a table with one row per target before modelling. A protocol and the arithmetic it depends on are separate targets. For a protocol, record its threads, shared variables, every wait and what wakes it, terminal states such as joined or closed, and resources whose ownership moves. Include slots, buffers, file handles and resources that `close` frees. For a Lean target, record the functions, their integer types and the property. Start with waits that have no escape, resources freed by two paths, and errors raised on a different thread from the one that reports them. Read the whole source file for each target so the model follows the code.

## 2. Prepare the tools

Prepare tools after picking targets and before launching agents. The helpers are in this skill's `scripts/` directory. Stay in the target repository and run each helper with `bash` and its absolute path. Pass absolute paths to models and matrices. [Tool setup](references/setup.md) describes the pins, caches and environment settings.

- When a target needs TLA+, run `bash <skill-dir>/scripts/setup.sh tla`.
- When a target needs Lean, every Lean model in the repository shares one Lake project. If the repository has none, copy `lakefile.toml`, `lake-manifest.json` and `lean-toolchain` from `<skill-dir>/examples/lean-template/` to `lean/` in the target repository, once. Then run `bash <skill-dir>/scripts/setup.sh lean <absolute-model-project-path>`.

Require a successful exit and a `READY` line from each command. The setup helper reuses ready tools and prepares missing tool versions, so the user does not need to rerun `/agent-formal-verify:setup` when a target or pin changes. Keep the installed skill files read-only and copy templates into the target repository.

If a system prerequisite such as Java or elan is missing, use the [setup skill](../setup/SKILL.md) to prepare it within the user's installation constraints and existing authorization. Report any prerequisite that cannot be prepared. If `java` on PATH has no runtime, set `JAVA` to a working JDK's `java` binary for the setup helper and the matrix runner.

The helpers:

- The setup helper, [`scripts/setup.sh`](scripts/setup.sh), is the only helper that downloads tools.
- The matrix runner, [`scripts/tlc-matrix.sh`](scripts/tlc-matrix.sh), runs TLC with a matrix of constants and prints one PASS or FAIL per run with its state count, then a SUMMARY line with the totals. A failing run prints its error trace reduced by [`scripts/tlc-trace.py`](scripts/tlc-trace.py) to the variables each step changed. Copy [`examples/tla-template/`](examples/tla-template/BoundedQueue.tla) to start a spec and its matrix.
- The Lean checker, [`scripts/lean-check.sh`](scripts/lean-check.sh), builds every `.lean` file in the pinned Lake project and audits every declaration of every built module. It fails on a build error, a `sorry`, a declaration that rests on an axiom beyond `propext`, `Classical.choice` and `Quot.sound`, or a `.lean` file that no Lake library owns. Given file names after the project, it checks only those files. Copy [`examples/lean-template/Model/BoundedQueue.lean`](examples/lean-template/Model/BoundedQueue.lean) to start a model.
- The mutation runner, [`scripts/mutate.py`](scripts/mutate.py), takes a model's `<Name>.mutations` file and applies each listed bug to a temporary copy of the model. It prints DETECTED or MISSED per mutation with what failed, UNCOVERED for a TLA+ property that no mutation targets, and a SUMMARY line. Both templates include a mutations file.

## 3. Model one protocol per agent

Spawn one agent per protocol, in parallel when supported. Use the host runtime's agent tools and follow the user's model configuration when selecting agents. If delegation is unavailable, model the targets yourself, one at a time, under the same requirements. An agent does not see this skill, so its brief must contain:

- the source files and line ranges, threads and shared variables from the table;
- the absolute paths of the matrix runner, the mutation runner and the TLA+ template, and any `JAVA` setting;
- the files to write, `tla/<Name>.tla`, `tla/<Name>.matrix` and `tla/<Name>.mutations` in the target repository, or the same names in its existing model directory, with the top-level formula named `Spec` as the matrix runner requires;
- the instruction to run `bash <absolute-path>/tlc-matrix.sh <absolute-path>/tla/<Name>.matrix`, then `python3 <absolute-path>/mutate.py <absolute-path>/tla/<Name>.mutations`, and to report only after reading their output;
- every modelling requirement below, copied in full.

One matrix file and one mutations file per spec let parallel agents work without sharing a file.

Modelling requirements for the brief:

- Use one step per critical section under the mutex and one per unlocked phase, such as build, parse or consume. Add an explicit `lock` variable when multiple lock acquisitions can race.
- Use a program counter per thread. Represent a condition-variable wait as a pc value in the wait set. Only a broadcast, signal or spurious wakeup can leave that set. The woken thread must retake the mutex and reread the state before acting. Give spurious wakeups no fairness requirement. In this encoding, a lost wakeup appears as a liveness violation rather than a TLC deadlock. Explain that in the model header and check liveness.
- Model resource ownership as a variable. Each slot or buffer must be free, in exactly one queue, or held by exactly one thread. Each produced item must be recorded by the consumer, awaiting hand-over, or freed.
- When `longjmp`, an exception, a panic or `exit()` can leave a critical section without unlocking, use separate variables for the mutex's actual owner and the lock ownership recorded in the thread's live frames. An unwind can leave these inconsistent and block later acquisitions. Preserve that state so the model can detect the hang. List every allocation and exit call that can run under each lock, including out-of-memory exits.
- Let the consumer call `next` any number of times, stop calling, or call `close` from any idle point. Include close before the first call, after the last item and after an error. When the producer has a failure path, let it fail at any item through a constant set `FailAt`.
- Check small instances and boundary cases. Use slot counts of 1, 2 and the shipped count, item counts of 0, 1, 3 and 5, and one, two and three workers.
- Check `TypeOK`, the ownership partition, delivery order, no delivery after end or error, the documented error-ordering guarantee, and no double free or leak at `closed`. For liveness, check that each blocking call returns, `close` terminates from every allowed calling state, and a run without `close` reaches the end. Require weak fairness on thread steps except consumer choices and spurious wakeups. Add strong fairness on a mutex acquisition only when a counter-example shows pure starvation by a spuriously waking peer. Name that assumption in the spec.
- Before reporting a pass, list mutations that represent plausible code bugs in the mutations file, as the template's does. Try replacing `while` with `if`, removing a broadcast, replacing FIFO order with stack order, leaving a flag set, or taking an item without removing it. Each mutation names the one property that must fail on it. The mutation runner applies them to copies, so the spec needs no `Mutation` constant and no mutation branches. When one replacement restores the behaviour before a fix, list it as a mutation instead of adding a constant that switches the fix off. Revise a property the runner reports as UNCOVERED, and the property or the mutation behind each MISSED line.
- Report file paths, the exact matrix runner and mutation runner commands with their SUMMARY lines, and a table of run labels, state counts and verdicts. Map each counter-example to code events with `file:line`. Assess reachability, identify real-code constraints the model lacks, and list properties it could not express.

## 4. Read the counter-example back into the code

For each violation, in this order:

1. Read the reduced trace that the matrix runner prints under the FAIL line. Map each step to a code event and source line.
2. Check reachability against the real constants and callers. If a violation occurs at `Slots=1` while the code ships `Slots=4`, decide whether the trace needs the smaller count or can also occur at the shipped one. Report the first as safe only while the count stays at the shipped value, and the second as a reachable bug. Keep the boundary configuration in the matrix either way.
3. Reproduce a reachable trace with a deterministic test, a ThreadSanitizer or race-detector run, or a stress loop using the trace's counts. Hooks, a small slot count or barriers can force the interleaving. If no practical reproduction exists, report that limitation and the model configuration that demonstrates the violation.
4. Change code only when the user asked for fixes. Otherwise report the trace, the reproduction and the proposed fix, and stop here.
5. Apply the smallest fix that prevents the trace, update the spec to match, and rerun the whole matrix. Keep the spec and code change together.
6. When the user asked for commits or pull requests, use one PR per bug. Include the spec, matrix and fix, with the state counts and mutation results in the description.

## 5. Lean for the sequential core

Use one agent per target, as in step 3. Each target is one file in the shared project from step 2, `lean/Model/<Name>.lean`, with its mutations in `lean/Model/<Name>.mutations`. The file's declarations sit in `namespace <Name>`, because the checker audits the project's modules together and equal names clash. The brief contains the source files and line ranges, the absolute paths of the Lean checker, the mutation runner and the template's [`Model/BoundedQueue.lean`](examples/lean-template/Model/BoundedQueue.lean) and `Model/BoundedQueue.mutations`, and the numbered steps below, copied in full. Each agent runs `bash <absolute-path>/lean-check.sh <absolute-path>/lean Model/<Name>.lean`, which checks its own file only, then `python3 <absolute-path>/mutate.py <absolute-path>/lean/Model/<Name>.mutations`, before reporting. When the agents have reported, run the Lean checker on the whole project without a file name.

Every `.lean` file in the project must belong to a library in the lakefile: with the template, that is every file under `Model/`. An existing project keeps its layout and must pin Lean 4.20.0 or later for the Lean checker. Add Mathlib only when the arithmetic needs it, since its dependencies can increase setup and build time.

1. Transcribe the state type and functions with the code's integer widths, rounding, division and order of operations. Use `UInt32` or `Int` with explicit bounds where appropriate, and `Nat` only when values cannot go negative. Keep the source function names and cite `file:line` in doc comments. Preserve any bug during transcription so the model checks the code as written.
2. State the property as a `Prop` with a `Decidable` instance. It may describe an invariant, an encoder round trip, an index bound or states the machine must never reach.
3. Write and evaluate a bounded exhaustive check before proving the theorem. The template's `badPairs` finds states where one step breaks the invariant; `#eval` prints concrete counter-examples and `#guard` fails the build while any exist. Set the bound above the code's slot count, batch size, window and other constants so it includes boundary cases.
4. Prove one theorem per step or function for every size. Split on the guards, use `simp only [...]` to expose arithmetic, then use `omega` or `decide` for a finite type. If a proof needs a fact about the real code that the model lacks, state it as a theorem hypothesis and name it in a comment. Do not declare it as an `axiom`. An unfinished proof may use `sorry`, but the Lean checker reports it as a failure. The checker also fails every declaration that rests on an axiom beyond `propext`, `Classical.choice` and `Quot.sound`, which also rules out `native_decide`.
5. List plausible bugs in the mutations file, such as `<` instead of `≤`, a missing `+ 1` or a swapped argument, and run the mutation runner. It checks each on a copy of the file and names the theorems and `#guard` lines that fail; expect both the bounded search's `#guard` and the theorem. It rejects a mutation that stops a definition compiling. Revise the properties behind each MISSED line.
6. Report the Lean checker command and its PASS or FAIL line, the mutation runner's output, concrete inputs to the code's function, the source line of the failing arithmetic, a unit test with those inputs, and the proposed fix. Step 4's rules on reachability, fixes and pull requests apply to Lean counter-examples too. For a closed proof, report its assumptions, including integer widths and bounds.

## 6. Keep the proof

Add CI only when the user asked for it or the repository already runs models in CI. Otherwise give the commands in the reply. The CI section of [tool setup](references/setup.md) describes how a CI job obtains the helpers, which are not in the target repository, and prepares the tools in a separate setup step. Run each matrix file through the matrix runner; see [`examples/tla-template/BoundedQueue.matrix`](examples/tla-template/BoundedQueue.matrix) for the directives. Keep the Lean project and its toolchain pin in the repository, and run the Lean checker on it. Run the mutation runner on each mutations file.

Each model's header comment must name the source code and line numbers it models. Refresh the references when the code moves. Record what each model checks and its boundary configuration in the project's testing documentation.

## What this does not cover

These models do not check memory ordering below the mutex. Keep the project's ThreadSanitizer or race-detector checks. Model floating-point results as the integers they round to, unless the property concerns the rounding itself.

A passing model establishes its stated properties under its assumptions. Report any real-code constraints the model omits and the hypotheses each theorem requires, so the reader can assess whether the result applies to the code.

## Reply

Return the target table with a verdict per row. Each TLA+ verdict includes its state counts and mutation results. Each Lean verdict includes the checker's PASS or FAIL line and mutation results. For each counter-example, report the code events, reachability, reproduction and the fix or proposed fix, with a PR link when one was opened. Include the matrix runner and Lean checker commands, the PASS count and properties that could not be expressed.
