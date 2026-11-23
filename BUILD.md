# Build

## Prerequisites

Git, Python 3.11+ as `python3`, uv, just, Codex and Claude Code. Publishing also needs the GitHub
CLI (`gh`) authenticated for this repository.

## Build and verify

```sh
just setup
just verify
just build
```

`setup` installs development dependencies. `verify` runs lint, including the profile table checks,
type checks and tests. The tests install the packaged plugin into disposable Codex configuration
and make no model calls. `build` assembles `dist/marketplace`, a verbatim copy of the plugin with
both marketplace catalogs.

`just eval --host claude --model MODEL`, `just eval --host codex --model MODEL`, or
`just eval --host antigravity --model MODEL` asks a real model to apply the shipped selection
procedure and skills rule to the routing cases in `tests/eval` and scores the answers against
`scripts/profiles.py`. It costs inference, so it is not part of `verify`; run it before a release
that changes the skill text or the tables.

## Local install

Each path changes your own host configuration. For Codex:

```sh
codex plugin marketplace add "$PWD/dist/marketplace"
codex plugin add polyagent@polyagent
```

For Claude Code:

```sh
claude plugin marketplace add "$PWD/dist/marketplace"
claude plugin install polyagent@polyagent
```

For Antigravity:

```sh
agy plugin validate --strict "$PWD/dist/marketplace/plugins/polyagent"
agy plugin install "$PWD/dist/marketplace/plugins/polyagent"
```

## Release

1. Preview with `just release`. The version follows Conventional Commits since the last
   `release/vX.Y.Z` tag: `fix` is a patch, `feat` a minor, a breaking change a major. Other commit
   types release nothing.
2. On a topic branch with a clean tree, run `just release-apply`, review and commit the result, and
   run `just verify`.
3. Land that commit on `main` and push it.
4. Once the release is authorized, run `just release-publish` from that commit. It tags the source,
   builds the package from it, verifies it, publishes the marketplace and the GitHub Release with
   the changelog section as its notes, and checks installation from origin.

If publication fails, it names the stage that failed. Rerun the same command from the same commit;
the package is rebuilt from the tagged source and checked against it before anything is published.

- Published versions are immutable. To change or roll back, release a higher version from a new
  commit. Never reset the `marketplace` branch.
- No release command changes repository visibility or installs into your own configuration. Both
  are separate steps that need their own authorization.

[MIT licensed](LICENSE)
