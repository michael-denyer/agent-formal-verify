# Tool setup

Run `/agent-formal-verify:setup` once to prepare Java, Python, TLC, elan and Lean. In Codex, request this plugin's `setup` skill. The [setup skill](../../setup/SKILL.md) prepares both verification tools independently of any repository and reuses existing runtimes and caches.

The formal-verify skill selects tools from the current repository on every invocation. It reuses prepared tools and downloads missing versions through the setup helper when a Lean pin or plugin tool version changes. Repository changes do not require the user to rerun the full setup.

## Running the helpers

The helpers are in the `scripts/` directory of the installed `formal-verify` skill, including a copied skills-only installation. `<skill-dir>` below stands for that skill's absolute path.

Stay in the target repository and run each helper with `bash` and its absolute path. Pass absolute paths to model projects and matrices. Keep the installed skill files read-only, and create models and build outputs in the target repository. Shared tool caches can serve several repositories; each repository determines its own tool requirements and Lean pins.

## TLA+ and TLC

The setup helper needs a JDK, Python 3, curl, and `sha256sum` or `shasum` to verify the download. If `java` on PATH has no runtime, as with the macOS stub, set `JAVA` to a working JDK's `java` binary. Copy the [TLA+ template](../examples/tla-template/BoundedQueue.tla) and its `checks.matrix` into the project to start a spec.

```shell
bash <skill-dir>/scripts/setup.sh tla
bash <skill-dir>/scripts/tlc-matrix.sh /path/to/models/Name.matrix
```

The setup helper downloads the TLC release pinned in `scripts/tlc-tools.sh` from the TLA+ GitHub releases into `~/.cache/tla/`, verifies its pinned SHA256, and publishes the file atomically. Repeat setup reuses a verified download and replaces a cached file that does not match the pin. Parallel setup calls use different temporary files. Set `TLC_CACHE` to choose another cache directory. Set `TLC_JAR` to use an existing JAR; an explicitly supplied JAR is trusted and must already exist.

The matrix runner requires a prepared JAR and a working Java runtime. It checks Python 3 before running, so a failing model can always print its reduced trace. It does not download tools. Each run checks the formula its spec names `Spec` and sees only the modules beside that spec. `TLC_WORKERS` controls the TLC worker count.

## Lean 4

Install [elan](https://github.com/leanprover/elan#installation) through your normal package manager or its documented installer. Copy the [Lean template](../examples/lean-template/Model.lean) into the project, keeping its `lakefile.toml`, `lake-manifest.json` and pinned `lean-toolchain` file.

```shell
bash <skill-dir>/scripts/setup.sh lean /path/to/lean-project
bash <skill-dir>/scripts/lean-check.sh /path/to/lean-project
```

The setup helper checks the version in the project's current `lean-toolchain` and installs it only when it is not ready; it leaves the global default unchanged. The Lean checker uses `elan run` without its install flag, so a missing toolchain fails instead of downloading inside the checker. Lake builds may fetch dependencies declared by the model project. The supplied template has no external Lean packages.

The Lean checker builds every `.lean` file in the project by its path, so a file that no Lake library owns fails the build instead of going unchecked. It then compiles a short audit against the modules Lake reports for those files. The checker needs a pin of Lean 4.20.0 or later, the first whose Lake builds a module by its source path, and says so when an older pin fails. The audit lists every declaration that rests on an axiom beyond `propext`, `Classical.choice` and `Quot.sound`, so a model needs no `#print axioms` lines.

## CI

The helpers live in this plugin, not in the target repository. In CI, check out `michael-denyer/agent-formal-verify` at a pinned commit into a separate directory and run the helpers from its `skills/formal-verify/scripts/`. Update that pin deliberately, as for any other tool. A repository that vendors the scripts instead must keep their GPL-3.0-only license headers.

Install the chosen runtime in the CI environment, run the setup helper, then run the matrix runner or Lean checker as a separate step. Cache `TLC_CACHE` or elan's toolchain directory if useful, and keep the version pins with the models. Use the same JAR path, cache directory and `JAVA` setting in setup and verification.

```yaml
- uses: actions/checkout@<commit>
  with:
    repository: michael-denyer/agent-formal-verify
    ref: <pinned-commit>
    path: .formal-verify
- run: bash .formal-verify/skills/formal-verify/scripts/setup.sh tla
- run: bash .formal-verify/skills/formal-verify/scripts/tlc-matrix.sh "$PWD/tla/Name.matrix"
- run: bash .formal-verify/skills/formal-verify/scripts/setup.sh lean "$PWD/lean/Name"
- run: bash .formal-verify/skills/formal-verify/scripts/lean-check.sh "$PWD/lean/Name"
```
