# Changes

## 0.1.10 - sound Lean audit and clearer agent instructions

`lean-check.sh` audits every declaration of every built module with Lean, so a theorem that rests on a declared axiom, `native_decide` or `sorry` fails even when the model has no `#print axioms` line. It builds every `.lean` file in the project by path, so an unimported module is checked and a file that no Lake library owns fails; a default build skipped both. A project with no declarations fails. A long theorem name no longer causes a false failure. The Lean template drops its `#print axioms` lines.

The matrix runner reports the final state count; it previously reported the count from TLC's first progress line on longer runs.

`setup.sh tla` replaces a cached JAR that does not match the pin. `setup.sh lean` prints a `FAIL` line when an installed toolchain does not run.

The formal-verify skill prepares tools after picking targets, tells each agent brief to carry the helper paths, uses one matrix file per spec, and requires mutations for both tools on a copy or reverted. It changes code, commits and opens pull requests only when the user asked for fixes. Tool setup explains how CI obtains the helpers. Both skills run helpers by absolute path with `bash`.

Removed `.codex-plugin/prompts/`, which the Codex plugin manifest never loaded.

## 0.1.9 - verifier fixes and worked TLA+ example

The matrix runner now reduces the trace of an invariant violation or a deadlock; it previously reduced only temporal counter-examples and printed the raw log for the rest. The reducer reads one-variable specs and exits 1 on a log without a trace.

Each matrix run gets its own directory, so a spec no longer resolves modules left by an earlier spec. A missing spec is reported in one line.

The matrix runner fails a `check` line placed before any `spec` line, which it previously dropped while the run still passed, and a `run` line without a `|`, which it previously turned into a constant named after the label.

`lean-check.sh` prints multi-line `#eval` output whole, no longer counts `error:` text in output as a build error, and fails a theorem that `#print axioms` shows resting on a declared axiom. The Lean template guards its bounded search with `#guard`, so a counter-example fails the build.

Added a TLA+ template beside the Lean one; it replaces `examples/template.matrix`. CI runs both checkers on the examples and on mutated copies.

The tests run under `node --test` and include the metadata checks that `tools/check.mjs` held, so development no longer needs Bun.

## 0.1.8 - validation and simpler metadata

Removed the separate root version file. Validation compares the plugin manifests, marketplace entry and release notes directly.

Added prek hooks shared with CI, including Python and workflow linting. Dependabot proposes weekly updates for lint tools, prek and GitHub Actions.

CI checks local documentation links and heading anchors offline and audits workflow security with zizmor.

## 0.1.7 - simplify contribution guidance

Removed the separate reporting document and contact fields from plugin metadata.

## 0.1.6 - clarify the workflow diagram and method

Moved the diagram subtitle into a README heading and added a short workflow explanation. The introduction credits Boris Cherny's targeted formal-verification method.

## 0.1.5 - workflow graphic and shorter README

Added a workflow diagram and a getting-started example. Moved detailed installation, update and verification guidance into a reference page.

## 0.1.4 - GPLv3 and contributor documentation

The plugin uses GPL-3.0-only. Added contributor guidance, issue forms and a pull request template. The README now explains the verification workflow and updates for Claude Code and Codex. Edited the skills and template comments for clearer prose.

## 0.1.3 - set up all tools once, select them during verification

Setup prepares the complete shared toolset independently of any repository. Formal verification selects tools from its current targets and prepares any missing pinned artifacts before modelling. Repository changes and new Lean pins do not require a manual setup rerun. Lean preparation reuses a working pinned toolchain without calling the installer. CI runners still require a separate preparation step.

## 0.1.2 - clarify global setup scope

Setup resolves the invocation's repository before running helpers from the installed plugin. Global installations share tool caches while selecting tools and respecting Lean pins separately for each repository. Installed helpers and templates remain read-only; model files and build outputs belong in the target repository.

## 0.1.1 - add an agent setup command

`/agent-formal-verify:setup` inspects the repository's thread protocols, sequential invariants and existing models, then prepares TLA+, Lean, or both before verification. Explicit tool arguments are overrides. It reuses existing runtimes, installs missing required prerequisites through the user's package manager when available, and runs the pinned setup helper. Lean setup uses an existing project's pin or the bundled template; setup reports tool readiness without creating a model project or changing the global Lean default.

## 0.1.0 - formal verification with TLA+ and Lean

A standalone plugin for modelling thread protocols with TLA+ and TLC and proving sequential invariants with Lean 4. It includes matrix and proof runners, templates, and explicit tool preparation. Verification checks require prepared tools; they do not install a JDK, elan, TLC, or a Lean toolchain. TLC downloads use unique temporary files and verify the checksum before publishing to the cache.
