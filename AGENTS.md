# Polyagent

## Product

- Build the stock Codex, Claude Code, and Antigravity routing skill: Markdown and TSV that the
  agent reads, with no runtime. Keep the repository and its builds independent of other projects
  and of Git; use the small packaging script.
- Keep table shapes explicit and checked by `scripts/profiles.py`. The host harness owns model
  capability acceptance.
- Keep one profile format for all hosts. `routes.tsv` is keyed by host, rows with the same host,
  route and difficulty are an ordered fallback list, and hosts with a closed model set filter their
  own rows through the subagent tool's advertised models.
- Bundled profiles live in the skill and are never copied into user configuration. Never read or
  modify the previous Polyagent installation.
- Write concise, plain documentation. Add a document only when users need it.

## Changes

- Test behavior through the packaged plugin and the reference selection in `scripts/profiles.py`.
  Tests make no model calls; `just eval` is the opt-in model check for skill wording.
- Run `just verify` for changes to the skill, the tables or distribution; it includes the plugin
  lifecycle tests against the packaged marketplace.
- Use Conventional Commits. The type decides the next release: use `fix` or `feat` for anything
  users will notice, because other types release nothing.

## Releases

- Release, or change repository visibility, only when the user requests that step.
- For authorized releases, follow [BUILD.md](BUILD.md) and run `just release-publish` from the
  clean, reviewed release commit in `origin/main`. Reserve lower-level publication commands for
  diagnosis or recovery.
- A release is complete only when the workflow verifies the source tag, the marketplace, the
  GitHub Release and installation from origin. On failure, report a partial release and resume the
  same workflow from the same commit.
