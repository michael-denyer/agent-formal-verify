---
name: formal-verify
description: "Model-check thread protocols with TLA+ and TLC, and prove sequential invariants with Lean 4. Map counter-examples to source locations, reproductions and fixes, and keep the models in CI. Use for /formal-verify, formal verification, model checking, Lean proofs, or concurrency bugs that runtime tests cannot reproduce."
---

# Formal verify

Model individual protocols or sequential invariants. Map counter-examples to events and locations in the source code. Before reporting a pass, confirm that each checked property detects a relevant mutation or that each Lean theorem is proved without `sorry`.

Choose tools according to the target:

| What can go wrong | Tool | Why |
| --- | --- | --- |
| Thread interleavings that lose wakeups, free resources twice, deliver items twice or out of order, block close, or report errors on the wrong thread | TLA+ with TLC | TLC explores the states of a small instance and reports counter-examples |
| Arithmetic or sequential transitions that break bounds, invariants or encoder round trips, or reach states the code assumes impossible | Lean 4 | Evaluate bounded instances, then prove the property for every size |

A thread protocol that depends on arithmetic such as `slot = item mod window` needs both tools. Use TLA+ for the interleavings with the arithmetic as a constant, and Lean for the arithmetic.

## Tool preparation

On every verification request, pick targets from the current source and models before preparing tools. Resolve the invocation's target repository before running installed helpers, as described in [tool setup](references/setup.md).

Before launching agents, run `scripts/setup.sh tla` when the selected targets need TLA+. Run `scripts/setup.sh lean <absolute-model-project-path>` for each distinct Lean pin they need. For a new Lean project, use the bundled template's pin. These helpers reuse ready tools and prepare missing tool versions. The user does not need to rerun `/setup` when a target or pin changes. Require a successful exit and a `READY` line. Keep installed templates read-only and copy models into the target repository.

If a system prerequisite such as Java or elan is missing, use the [setup skill](../setup/SKILL.md) to prepare it within the user's installation constraints and existing authorization. Report any prerequisite that cannot be prepared. The low-level verification runners remain suitable for CI and do not install tools; CI runs preparation separately.

Use the host runtime's shell and agent tools. Follow the user's model configuration when selecting agents. If delegation is unavailable, model targets sequentially.

[`scripts/tlc-matrix.sh`](scripts/tlc-matrix.sh) runs TLC with a matrix of constants and prints one PASS or FAIL per run with its state count. [`scripts/tlc-trace.py`](scripts/tlc-trace.py) reduces a counter-example to the variables each step changed.

[`scripts/lean-check.sh`](scripts/lean-check.sh) builds the pinned Lake project and fails on errors or `sorry`. Copy [`examples/lean-template/`](examples/lean-template/Model.lean) to start a new model project.

## 1. Pick the targets

Search with `rg` for `pthread_cond`, `pthread_mutex`, `atomic_`, `std::condition_variable`, `sync.Cond`, `chan`, `select`, `asyncio.Condition`, `Semaphore`, `atexit` and `setjmp`. Also search for protocol state names such as `ready`, `stop`, `done`, `finished`, `pending`, `inflight`, `head`, `tail` and `exiting`. Classify each hit:

- Model hand-written protocols, including hand-overs, bounded pipelines, queues with ordered output, shutdown, cleanup, retry and lease loops.
- Check data-parallel loops over disjoint indices with the sanitizer.
- For library-owned channels or executors, model the calling code.
- Use Lean for arithmetic the protocol or output depends on. Examples include slot and splice indices, window bounds, sizes computed and checked differently, and encoder round trips. Search for `%`, `- 1`, `+ 1`, `>>`, `overlap`, `splice` and `offset` near the protocol's data.

Write a table with one row per protocol before modelling. Record its threads, shared variables, every wait and what wakes it, terminal states such as joined or closed, and resources whose ownership moves. Include slots, buffers, file handles and resources that `close` frees. Start with waits that have no escape, resources freed by two paths, and errors raised on a different thread from the one that reports them. Read the whole source file for each protocol so the model follows the code.

## 2. Model one protocol per agent

Spawn one agent per protocol, in parallel when supported, with the brief below. Each writes `tla/<Name>.tla` beside the code and checks it before reporting. Return the report to the main agent.

Include the source files and line ranges, threads and shared variables from the table, and these modelling requirements:

- Use one step per critical section under the mutex and one per unlocked phase, such as build, parse or consume. Add an explicit `lock` variable when multiple lock acquisitions can race.
- Use a program counter per thread. Represent a condition-variable wait as a pc value in the wait set. Only a broadcast, signal or spurious wakeup can leave that set. The woken thread must retake the mutex and reread the state before acting. Give spurious wakeups no fairness requirement. In this encoding, a lost wakeup appears as a liveness violation rather than a TLC deadlock. Explain that in the model header and check liveness.
- Model resource ownership as a variable. Each slot or buffer must be free, in exactly one queue, or held by exactly one thread. Each produced item must be recorded by the consumer, awaiting hand-over, or freed.
- When `longjmp`, an exception, a panic or `exit()` can leave a critical section without unlocking, use separate variables for the mutex's actual owner and the lock ownership recorded in the thread's live frames. An unwind can leave these inconsistent and block later acquisitions. Preserve that state so the model can detect the hang. List every allocation and exit call that can run under each lock, including out-of-memory exits.
- Let the consumer call `next` any number of times, stop calling, or call `close` from any idle point. Include close before the first call, after the last item and after an error. When the producer has a failure path, let it fail at any item through a constant set `FailAt`.
- Check small instances and boundary cases. Use the shipped slot count plus 1 and 2, item counts of 0, 1, 3 and 5, and one, two and three workers.
- Check `TypeOK`, the ownership partition, delivery order, no delivery after end or error, the documented error-ordering guarantee, and no double free or leak at `closed`. For liveness, check that each blocking call returns, `close` terminates from every allowed calling state, and a run without `close` reaches the end. Require weak fairness on thread steps except consumer choices and spurious wakeups. Add strong fairness on a mutex acquisition only when a counter-example shows pure starvation by a spuriously waking peer. Name that assumption in the spec.
- Before reporting a pass, introduce mutations that represent plausible code bugs. Try replacing `while` with `if`, removing a broadcast, replacing FIFO order with stack order, leaving a flag set, or taking an item without removing it. Record which property detects each mutation. Revise properties that detect none of the relevant mutations.
- Report file paths, the exact TLC command for each configuration, and a table of state counts and verdicts. Map each counter-example to code events with `file:line`. Assess reachability, identify real-code constraints the model lacks, and list properties it could not express.

## 3. Read the counter-example back into the code

For each violation, in this order:

1. Run `tlc-trace.py tlc.log`. Map each step to a code event and source line.
2. Check reachability against the real constants and callers. If a violation occurs at `Slots=1` while the code ships `Slots=4`, distinguish a dependency on the larger count from a reachable hang. Keep the boundary configuration in the matrix either way.
3. Reproduce a reachable trace with a deterministic test, a sanitizer run, or a stress loop using the trace's counts. Hooks, a small slot count or barriers can force the interleaving. If no practical reproduction exists, report that limitation and the model configuration that demonstrates the violation.
4. Apply the smallest fix that prevents the trace, update the spec to match, and rerun the whole matrix. Commit the spec and code together.
5. Use one PR per bug. Include the spec, matrix entry and fix, with the state counts and mutation results in the description.

## 4. Lean for the sequential core

Use one agent per target, as in the TLA+ step, with the brief below. Copy [`examples/lean-template/`](examples/lean-template/Model.lean), including `lakefile.toml` and the pinned `lean-toolchain`. Add Mathlib only when the arithmetic needs it, since its dependencies can increase setup and build time.

1. Transcribe the state type and functions with the code's integer widths, rounding, division and order of operations. Use `UInt32` or `Int` with explicit bounds where appropriate, and `Nat` only when values cannot go negative. Keep the source function names and cite `file:line` in doc comments. Preserve any bug during transcription so the model checks the code as written.
2. State the property as a `Prop` with a `Decidable` instance. It may describe an invariant, an encoder round trip, an index bound or states the machine must never reach.
3. Write and evaluate a bounded exhaustive check before proving the theorem. The template's `badPairs` finds states where one step breaks the invariant; `#eval` prints concrete counter-examples. Set the bound above the code's slot count, batch size, window and other constants so it includes boundary cases.
4. Prove one theorem per step or function for every size. Split on the guards, use `simp only [...]` to expose arithmetic, then use `omega` or `decide` for a finite type. If a proof needs a fact about the real code that the model lacks, name it in a comment. An unfinished proof may use `sorry`, but `lean-check.sh` reports it as a failure.
5. Mutate the model with plausible bugs, such as `<` instead of `≤`, a missing `+ 1` or a swapped argument. Confirm that the bounded search finds a counter-example and the theorem fails. Revise properties that detect none of the relevant mutations.
6. Report concrete inputs to the code's function, the source line of the failing arithmetic, a unit test with those inputs, and the fix. For a closed proof, report its assumptions, including integer widths and bounds.

## 5. Keep the proof

Prepare the chosen tools in a separate CI setup step using [tool setup](references/setup.md). Run TLA+ specs through `tlc-matrix.sh` with a matrix file beside them. See [`examples/template.matrix`](examples/template.matrix) for the directives. Keep Lean projects and their toolchain pins in the repository, and run `lean-check.sh <dir>` in CI.

Each model's header comment must name the source code and line numbers it models. Refresh the references when the code moves. Record what each model checks and its boundary configuration in the project's testing documentation.

## What this does not cover

These models do not check memory ordering below the mutex. Keep sanitizer checks. Model floating-point results as the integers they round to, unless the property concerns the rounding itself.

A passing model establishes its stated properties under its assumptions. Report any real-code constraints the model omits and the hypotheses each theorem requires, so the reader can assess whether the result applies to the code.

## Reply

Return the protocol table with a verdict per row. For each counter-example, report the code events, reachability, reproduction and fix with its PR link. Include the matrix command, PASS count and properties that could not be expressed. Each verdict must include its state count or mutation results.
