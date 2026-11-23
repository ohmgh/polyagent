# Delegate one outcome

## 1. Grade

Grade `risk` (failure likelihood and impact), `complexity` (reasoning and coordination), and
`ambiguity` (unresolved uncertainty) from 1 (lowest) to 10 (highest). Use the highest grade as
difficulty.

## 2. Select

The host is the harness running this session: `codex` in Codex, `claude` in Claude Code,
`antigravity` in Antigravity. Read it and your role (`root`, or `delegate` when you are a subagent
or swarm worker) from the active session, not from model names or environment variables. If the host
cannot be determined, keep the outcome at root.

Read the active native subagent tool's schema, description, or model-list action; in Antigravity,
use `swarm` and its `models` action (`all: true`). When it advertises a model set, that set filters
your host's rows, using the tool's identifiers to match either `model` or `model-effort`. This
includes Codex's "Available model overrides" even when `model` is a string without an enum, Claude
Code's Agent model values, and Antigravity's `swarm` model list. It says nothing about other hosts.

1. Among the `routes.tsv` rows for your host and the task's route, take the first band whose
   difficulty is at least the task's difficulty. Its rows, in order, are the candidates. Drop a row
   whose model (or `model-effort`) an advertised set lacks; without an advertised set, keep every
   row. A `-` row means the root and ends the list.
2. If your role is `root`, your band is not `-`, and `callouts` names other hosts, repeat step 1
   for each named host in order and append its rows as external candidates tagged with that host.
3. The root is the last candidate.

A model and effort the user requests replaces steps 1 and 2 with that single candidate, and the
root still follows it. A request for another host's model needs that host in `callouts`; otherwise
stop and report. Authorized inheritance of the native parent's model and effort is likewise a
single candidate. Select again when the task, profile, or session context changes.

## 3. Bind a candidate

Scan candidates in order. The root candidate keeps the outcome at root. For a native candidate,
inspect the active subagent interface. For an external candidate, discover an available
integration that can perform the task for that host; there is no fixed catalog or required runner.
Inspect current schemas, descriptions, help, or capability metadata for model, effort, controls,
and the completion, failure, and cancellation support this task needs. Qualification does not
authorize installation, authentication, or other setup effects.

Skip a candidate only when its mechanism is missing or documented capabilities exclude its model
or effort; give a concise reason. An unfamiliar identifier is not proof of rejection. If a capable
interface accepts arbitrary identifiers without documenting acceptance, dispatch may proceed with
acceptance marked **unverified**. Never launch an inference probe.

Map the candidate and all requested controls without changing model or effort. For fresh children
under stock Codex contracts prohibiting overrides with full-history forks, map a selected native
candidate to `model`, `reasoning_effort`, and `fork_turns: "none"`, supplying self-contained
context. For a fresh inherited candidate, leave model and effort unset without imposing a fork
mode. A requested full-history fork conflicts with selected overrides under that contract; a
self-contained message does not fulfill full history.

In Antigravity, bind native candidates to `swarm` (`action: "add"`) rather than `invoke_subagent`:
map a selected candidate to `model: "<model>-<effort>"` and leave `model` unset for an inherited
candidate; set `name`, `brief`, and `workspace` (`"inherit"` for read-only or verification work,
`"share"` for concurrent writers, or `"branch"` when isolation is requested), leaving `fork` unset
unless history forking is requested.

If mandatory controls, context, or authority cannot be preserved, try another available binding for
the same candidate. If none works, stop only the affected dispatch before announcement or launch and
continue independent authorized work. Do not silently drop controls, downgrade settings, or skip to
another candidate to evade the conflict.

## 4. Reuse an eligible child

Consider reuse only after selecting and binding the new outcome's candidate. When `reuse_agents`
is `off`, start a fresh child for each delegated task, including follow-ups. Messages clarifying or
steering an execution already in progress remain part of that execution.

When `on`, prefer a child whose current host state confirms it is idle, whose prior execution
state is unambiguous, and whose new task naturally continues its previous work. Its retained
instructions and context must remain compatible with the new task, including required skills,
ownership, and authority. Work requiring fresh or independent context uses a fresh child.

The binding must preserve the selected host, model, effort, and requested controls. Known requested
settings plus documented continuation behavior can establish compatibility; contrary observed
settings disqualify reuse. For inherited candidates, establish compatibility with the current
parent's model and effort. If compatibility is unknown or the host cannot reliably continue and
track another execution, use a fresh child with the same bound candidate. In Antigravity, check
`swarm` `status` for a `waiting` worker with the same bound model and continue it on the board
without switching its model (`action: "model"`) or killing it. Do not change candidate order or
settings, wait for a busy child, or interrupt one to make reuse possible. Resolve or report an
unresolved prior dispatch for this outcome rather than replacing it, including on later turns.

For CLI callouts, track the persisted conversation ID separately from each process handle. Resume
that exact ID only after the previous invocation has terminated, with the same working directory,
configuration, and authority, mapping model, effort, and controls again. Confirm the returned ID
matches and receive this invocation's terminal result; a saved ID or an earlier result alone does
not establish completion.

## 5. Announce, dispatch, and receive

Write one child message for only the child-owned outcome; make fresh-child messages self-contained.
For continuations, supply new or changed inputs and instructions using compatible retained context.
Include required-skill instructions, constraints, completion criteria, and return format. Require
concise conclusions, decisive evidence, and open issues; for changes, also behavior, files,
verification, and risks. Tell every child not to spawn agents unless the user explicitly authorizes
nested delegation. Give concurrent writers separate ownership and require them to preserve other
edits.

Immediately before the actual native or external call, write this announcement as visible text in
the same message as the call, never only in reasoning:

```text
software.default → Implement native routing
→ risk: 7 complexity: 9 ambiguity: 4
→ implement: change • route: construction
→ band: 9 • gpt-6.2-astra: low • skills: none
```

The first line names the profile and a short label for the outcome. The last line starts with
`band`: the selected band's difficulty, or `requested` or `inherited`. An external candidate shows
its host, as in `claude opus: high`. List skills by name, or `none`. When the call has a title
field the host displays, such as the `description` of Claude Code's Agent tool, also set it to the
label followed by the model and effort. Launch or continue once with the child message and mapped settings. Do not
announce skipped candidates. A returned execution handle means `started`, an explicit rejection
`rejected`, and an indeterminate result `ambiguous`. Report failures with the requested candidate
and diagnostic. Rejection, exception, ambiguity, or timeout must not trigger automatic retry, fresh
replacement, or rerouting.

After dispatch, state the child-owned outcome and root-owned remainder before other work. Track the
execution handle, receive completion or failure for this execution rather than an earlier task on
the same child, and verify the result against the task. A started handle does not establish which
settings actually ran; keep requested model and effort separate from observed settings.
