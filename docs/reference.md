# Reference

## Skills and slash commands

| Skill | Claude Code command | Purpose |
| --- | --- | --- |
| `setup` | `/agent-formal-verify:setup` | Prepare the complete shared toolset once |
| `formal-verify` | `/agent-formal-verify:formal-verify` | Model-check protocols and prove sequential invariants |

In Codex, type `$` and pick the skill, run `/skills`, or request the skill by name. The plugin ships no Codex prompts or slash commands. Parallel targets use the host's agent tools and your configured models. Hosts without delegation can process targets sequentially.

## Shared installation

To test a local checkout in Claude Code:

```shell
claude --plugin-dir /absolute/path/to/agent-formal-verify
```

For a skills-only installation, use `skills/`. Its references, helpers and templates stay inside that tree. Copy both the `setup` and `formal-verify` skills so their references resolve.

Installing the plugin adds skills and helpers. Run setup to prepare the verification tools. The plugin has no hooks.

## Runtime setup and tool pins

The [setup skill](../skills/setup/SKILL.md) prepares a working JDK, Python 3, curl, a SHA256 tool, TLC, elan and Lean. It reuses existing prerequisites and installs missing ones through your package manager or the upstream documented installer, within your installation constraints. It prepares both verification tools and needs no target repository.

[Tool setup](../skills/formal-verify/references/setup.md) is the reference for everything after that first run: how verification prepares a changed Lean pin or tool version without a setup rerun, what global installations share, where caches live, the version pins, the direct helper commands, environment settings and CI.

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

Tool caches survive plugin updates. Run setup again only if a release introduces a new system prerequisite.

## Scope and evidence

The [verification skill](../skills/formal-verify/SKILL.md) directs the agent to select protocols and sequential invariants, transcribe their behaviour, and check their properties. It uses TLC to explore bounded instances, and Lean to evaluate bounded searches and prove properties for every size.

Before reporting a pass, it requires mutations that demonstrate the properties detect relevant bugs. They are kept in a file beside each model, and the mutation runner rechecks them. The Lean checker audits every declaration for `sorry` and for axioms beyond Lean's three standard ones. For failures, it requires source locations, reachability checks, and a reproduction where practical. The agent changes code, commits and opens pull requests only when you ask for fixes; it then fixes the code and model together, with one PR per bug.

Replies, pull requests and documents are written for a reader who knows the code and has used neither tool. They lead with what goes wrong in the code, state each property as what it guarantees, and say what a TLC pass, a Lean proof and a detected mutation each mean.

A passing model establishes its stated properties under its assumptions. Reports must identify omitted code constraints and unfinished proofs. These models do not check memory ordering below the mutex; keep ThreadSanitizer or race-detector checks. They do not establish correctness of the entire program or guarantee a particular number of discovered bugs.
