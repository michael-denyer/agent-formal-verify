# Contributing

Use [GitHub issues](https://github.com/michael-denyer/agent-formal-verify/issues) for bugs and proposals, and pull requests for changes.

## Develop locally

Clone the repository and install Node.js, Bun 1.3.14 and [prek](https://prek.j178.dev/installation/). Enable the commit hooks once per clone, then run all checks from the repository root:

```shell
prek install
prek run --all-files
```

prek prepares the pinned lint tools in its own cache. The hooks check plugin metadata, skill references, helper tests, shell scripts, Python, Markdown, JSON, YAML and GitHub Actions workflows. CI runs the same checks and also copies the skills into an isolated installation to check that their files match. Keep every skill reference, helper and template within `skills/` so copied installations work.

CI also checks local documentation links and heading anchors with lychee in offline mode and audits workflow security with zizmor. To run these checks locally, install lychee 0.24.2 and zizmor 1.29.0, then run:

```shell
lychee --offline --no-progress --include-fragments \
  --exclude-path .git --exclude-path .agents/skills \
  --exclude-path node_modules --exclude-path .lake '**/*.md'
zizmor --offline --persona pedantic --min-severity low .github/workflows/
```

Test the plugin in Claude Code with `claude --plugin-dir /absolute/path/to/agent-formal-verify`. To test model runners, prepare their tools using [tool setup](skills/formal-verify/references/setup.md). Runner changes should demonstrate a valid model passing and a broken property failing. Verification runners must report missing tools without downloading them; preparation belongs in `setup.sh`.

For skill changes, check a realistic request against the instructions. Confirm that the agent chooses suitable targets, preserves the source behaviour, and reports assumptions and proof gaps. Keep prose direct and remove slogans and unsupported claims.

## Submit a change

Use an unprefixed branch name. Keep each pull request focused on one problem. Describe the problem, resulting behaviour and validation. Include a small reproduction for bug fixes and relevant tests for changed tool behaviour. Avoid including caches, generated build files or unrelated edits.

## Release

Update both plugin manifests, the Claude marketplace entry and `CHANGES.md` together. `node tools/check.mjs` checks that the versions and license declarations agree. Document changes to setup requirements or pinned tools so users know what an update requires.

## Dependency updates

Dependabot opens weekly update PRs for GitHub Actions, the pinned lint hooks and prek. Updates wait seven days after release and must pass CI before review; they are not merged automatically.

Update the Bun version, isolated-installation `skills` CLI pin, lychee image tag and digest, and zizmor tool version manually in CI. Lean pins and TLC's version and checksum also need deliberate updates: run a valid model and a failing property with the new tools before changing their pins.

## License

Submit contributions under [GPL-3.0-only](LICENSE), the repository's license. Identify any third-party material and preserve its required notices.
