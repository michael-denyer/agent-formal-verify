---
name: setup
description: "Prepare all shared tools for the agent-formal-verify plugin: Java, Python, TLC, elan and Lean. Use for initial installation, missing prerequisites, or /agent-formal-verify:setup."
---

# Set up formal verification tools

Prepare the complete shared toolset once, independently of any repository. Verification selects TLA+, Lean, or both from each repository's current targets. A global plugin installation uses the same tools across repositories.

1. Read [tool setup](../formal-verify/references/setup.md) for pinned versions and environment settings. Inspect the operating system and existing runtimes. Reuse installed prerequisites and tool caches.
2. Ensure a working JDK, Python 3, curl, a SHA256 tool and elan are available. Install missing prerequisites through the user's existing package manager or the upstream documented installer, following their installation constraints. If no suitable installation method is available, or the user has not allowed installation, report the missing prerequisites and their installation instructions.
3. Check that `java -version` succeeds. If `java` is not on PATH or macOS resolves it to a stub, set `JAVA` to the working JDK's `java` binary for the commands below, and report that setting, because verification needs it too.
4. Run both commands below with the absolute path of the `formal-verify` skill, which is this skill's sibling directory, in place of `<skill-dir>`. Treat installed plugin files as read-only. The Lean template supplies the default pin without creating a model project or changing elan's global default.

   ```shell
   bash <skill-dir>/scripts/setup.sh tla
   bash <skill-dir>/scripts/setup.sh lean <skill-dir>/examples/lean-template
   ```

5. Require a successful exit and a `READY` line from both commands. Report the tool versions or pins, any environment settings required for verification, and anything still missing. Readiness confirms the tooling; the matrix runner and Lean checker check model correctness. Repeating setup reuses prepared tools. Verification handles repository-specific Lean pins when needed.
