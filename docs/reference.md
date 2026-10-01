# Reference

## Skills and slash commands

| Skill | Claude Code command | Purpose |
| --- | --- | --- |
| `setup` | `/agent-formal-verify:setup` | Prepare the complete shared toolset once |
| `formal-verify` | `/agent-formal-verify:formal-verify` | Model-check protocols and prove sequential invariants |

In Codex, request the plugin's skill by name. Parallel targets use the host's agent tools and your configured models. Hosts without delegation can process targets sequentially.

## Shared installation

To test a local checkout in Claude Code:

```shell
claude --plugin-dir /absolute/path/to/agent-formal-verify
```

For a skills-only installation, use `skills/`. Its references, helpers and templates stay inside that tree. Copy both the `setup` and `formal-verify` skills so their references resolve.

Installing the plugin adds skills and helpers. Run setup to prepare the verification tools. The plugin has no hooks.

## Runtime setup and tool pins

The [setup skill](../skills/setup/SKILL.md) prepares a working JDK, Python 3, curl, a SHA256 tool, TLC, elan and Lean. It reuses existing prerequisites and installs missing ones through your package manager or the upstream documented installer, within your installation constraints. It prepares both verification tools and needs no target repository.

Global installations share the TLC cache and elan toolchains across repositories. Setup keeps elan's global default unchanged. See [tool setup](../skills/formal-verify/references/setup.md) for cache locations, version pins, direct helper commands and environment settings.

Each verification invocation selects tools from the repository's current source and models. It reuses prepared tools and fetches missing versions when a Lean pin or plugin tool version changes. Repository changes do not require a manual setup rerun. Models and build outputs belong in the target repository; installed plugin helpers and templates remain read-only.

Low-level runners require prepared tools. CI runs preparation separately before checking models.

## Plugin updates

For Claude Code, run in your terminal:

```shell
claude plugin update agent-formal-verify@agent-formal-verify
```

Run `/reload-plugins` in an existing session to load the update. You can enable marketplace auto-updates through `/plugin`. See [Claude Code plugin updates](https://code.claude.com/docs/en/discover-plugins#keep-plugins-updated).

For Codex:

```shell
codex plugin marketplace upgrade agent-formal-verify
```

Start a new session to use the refreshed plugin. See [Codex marketplace management](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli).

Tool caches survive plugin updates. Verification prepares changed tool pins when needed. Run setup again if a release introduces a new system prerequisite.

## Scope and evidence

The [verification skill](../skills/formal-verify/SKILL.md) directs the agent to select protocols and sequential invariants, transcribe their behaviour, and check their properties. It uses TLC to explore bounded instances, and Lean to evaluate bounded searches and prove properties for every size.

Before reporting a pass, it requires mutations that demonstrate the properties detect relevant bugs. For failures, it requires source locations, reachability checks, a reproduction where practical, and fixes to the code and model together. Each bug gets its own PR with state counts and mutation results.

A passing model establishes its stated properties under its assumptions. Reports must identify omitted code constraints and unfinished proofs. These models do not check memory ordering below the mutex; keep sanitizer checks. They do not establish correctness of the entire program or guarantee a particular number of discovered bugs.
