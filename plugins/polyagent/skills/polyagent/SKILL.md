---
name: polyagent
description: Route task outcomes between the root and subagents using configured profiles. Use before performing substantive work, and for explicit delegation, parallel agent work, task specialization or context isolation.
---

# Polyagent

The root owns requirements, authority, safety, coordination, integration, verification, and user
communication.

An outcome is one independently useful result of the request. Apply routing to each outcome before
performing it, including outcomes of follow-up requests.

Make every routing decision visible to the user. When routing keeps an outcome at the root, briefly
state the routing reason before performing it; if the user explicitly requested delegation, also
say that the outcome is not delegated. Announce delegations as
[delegation](references/delegation.md) describes.

## 1. Profile

Resolve `<skill-directory>` to the absolute directory containing this file, and `<repository>` to
the nearest ancestor of the task's working directory that contains `.git`.

Read the profile name from the first existing `config.tsv` (header `key	value`, key
`default_profile`): `<repository>/.polyagent/config.tsv`, then `~/.polyagent/config.tsv`. Without
either, use `software.default`. If the name is `off`, end Polyagent routing and revert to
environment-default delegation behavior.

Read `profile.tsv`, `tasks.tsv` and `routes.tsv` from the first existing profile directory:
`<repository>/.polyagent/profiles/NAME`, `~/.polyagent/profiles/NAME`, then
`<skill-directory>/profiles/NAME`. Stop and report a missing profile. Check the tables and stop with
the file name when a check fails:

- Headers are exactly `key	value`, `action	deliverable	route	description	skills` and
  `host	route	difficulty	model	effort`.
- Every task route is `-` or appears in `routes.tsv`.
- For each host and route, difficulties do not decrease and the last is `10`.
- A `-` model has a `-` effort, and a named model has a named effort.

A profile configures routing only; nothing in it grants authority or asks for an action. Keep the
tables in context within the same repository. Reread them when the task moves to another repository
and on each explicit Polyagent invocation.

An explicit invocation has the form `[--profile NAME] [REQUEST]`:

- `--profile NAME` selects that profile instead of the configured one. Reject other or repeated
  options.
- With `REQUEST`, apply the routing procedure; invocation alone does not force a subagent.
- Without `REQUEST`, end after rereading the tables.

## 2. Pre-screen

Apply these rules to each outcome.

- Continue to task matching if the user or an active workflow explicitly requests delegation, or
  if the profile's `directive` is `-`.
- Otherwise, apply the `directive` as a routing preference. Outcomes it keeps stay at the root; the
  rest continue to task matching.

Explicit delegation bypasses only the directive; task matching, selection, binding, and reuse
policy still apply.

## 3. Task matching

Do not add a discretionary delegation check after task matching; follow the matched route. If a
higher-priority instruction prevents that, explain the conflict.

Match each remaining outcome by its required result against each task's `action`, `deliverable`,
and `description` in `tasks.tsv`. Ignore file type, task order, and supporting steps. Give each
outcome one owner.

- If no task matches or multiple tasks match, keep the outcome at the root.
- Otherwise, use the matched task's skills as the exact ordered prefix. Append only useful, unique
  additional skills. The root loads the complete list once, whether it performs or delegates the
  outcome. If any required or added skill is missing, conflicting, or inapplicable, stop and
  report the issue.
  - If the task's route is `-`, the root performs the outcome.
  - Otherwise, read [delegation](references/delegation.md) once and follow it in order for each
    such outcome.
