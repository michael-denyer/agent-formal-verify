# Tool setup

Run `/agent-formal-verify:setup` once to prepare Java, Python, TLC, elan and Lean. In Codex, request this plugin's setup skill. The [setup skill](../../setup/SKILL.md) prepares both verification tools independently of any repository and reuses existing runtimes and caches.

The formal-verify skill selects tools from the current repository on every invocation. It reuses prepared tools and downloads missing versions through the helpers below when a Lean pin or plugin tool version changes. Repository changes do not require the user to rerun the full setup.

Prepare the tool selected for the target before launching model agents. The commands below run from the installed `formal-verify` skill directory. They can also run from a copied skills-only installation.

During verification with a global installation, resolve the invocation's target repository before changing directories to run helpers. Pass absolute paths to its model projects and matrices. Shared tool caches can serve several repositories; each repository determines its own tool requirements and Lean pins. Keep installed plugin files read-only, and create models and build outputs in the target repository.

## TLA+ and TLC

Install a JDK, Python 3 and curl through your normal package manager. Setup also needs `sha256sum` or `shasum` to verify the download. On macOS, select a working JDK through `JAVA` if the `java` on PATH is the system stub.

```shell
bash scripts/setup.sh tla
bash scripts/tlc-matrix.sh /path/to/models/checks.matrix
```

Setup downloads TLC v1.7.4 from the TLA+ GitHub release into `~/.cache/tla/`, verifies its pinned SHA256, and publishes the file atomically. Repeat setup reuses a verified download. Parallel setup calls use different temporary files. Set `TLC_CACHE` to choose another cache directory. Set `TLC_JAR` to use an existing JAR; an explicitly supplied JAR is trusted and must already exist.

The matrix runner requires a prepared JAR and a working Java runtime. It checks Python 3 before running, so a failing model can always print its reduced trace. It does not download tools. `TLC_WORKERS` controls the TLC worker count.

## Lean 4

Install [elan](https://github.com/leanprover/elan#installation) through your normal package manager or its documented installer. Copy the [Lean template](../examples/lean-template/Model.lean) into the project, keeping its `lakefile.toml` and pinned `lean-toolchain` file.

```shell
bash scripts/setup.sh lean /path/to/lean-project
bash scripts/lean-check.sh /path/to/lean-project
```

Setup checks the version in the project's current `lean-toolchain` and installs it only when it is not ready; it leaves the global default unchanged. The checker uses `elan run` without its install flag, so a missing toolchain fails instead of downloading inside the checker. Lake builds may fetch dependencies declared by the model project. The supplied template has no external Lean packages.

## CI

Install the chosen runtime in the CI environment, run the appropriate setup command, then run the checker as a separate step. Cache `TLC_CACHE` or elan's toolchain directory if useful, and keep the version pins with the models. Use the same JAR path, cache directory and `JAVA` setting in setup and verification.
