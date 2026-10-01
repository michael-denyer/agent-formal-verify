---
name: setup
description: "Prepare all shared tools for the agent-formal-verify plugin: Java, Python, TLC, elan and Lean. Use for initial installation, missing prerequisites, or /agent-formal-verify:setup."
---

# Set up formal verification tools

Prepare the complete shared toolset once, independently of any repository. Verification selects TLA+, Lean, or both from each repository's current targets. A global plugin installation uses the same tools across repositories.

1. Read [tool setup](../formal-verify/references/setup.md) for pinned versions and environment settings. Inspect the operating system and existing runtimes. Reuse installed prerequisites and tool caches.
2. Ensure a working JDK, Python 3, curl, a SHA256 tool and elan are available. Install missing prerequisites through the user's existing package manager or the upstream documented installer, following their installation constraints. If no suitable installation method is available, report the missing prerequisites and their installation instructions.
3. From this skill's directory, run both commands below. Treat installed plugin files as read-only. The Lean template supplies the default pin without creating a model project or changing elan's global default.

```shell
bash ../formal-verify/scripts/setup.sh tla
bash ../formal-verify/scripts/setup.sh lean ../formal-verify/examples/lean-template
```

If Java is not on PATH or macOS resolves it to a stub, supply the working JDK's executable through `JAVA` for setup and subsequent verification commands.

4. Require a successful exit and a `READY` line from both commands. Report the tool versions or pins, any environment settings required for verification, and anything still missing. Readiness confirms the tooling; model correctness is checked by the verification runners. Repeating setup reuses prepared tools. Verification handles repository-specific Lean pins when needed.
