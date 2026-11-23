"""Ask a real model to apply the skill's selection procedure to the eval cases.

    uv run python tests/eval/run.py --host claude --model haiku
    uv run python tests/eval/run.py --host codex --model gpt-6.2-sol --cases 1,24,26

The model reads the selection section of references/delegation.md, the skills rule of SKILL.md and
the profile tables, never a restatement of them, so the result measures the skill text that ships.
Each answer is scored against scripts/profiles.py. Exit status 1 reports at least one mismatch.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cases

SKILL = cases.ROOT / "plugins/polyagent/skills/polyagent"
OUTPUT = """## Output

Do not use any tools, run commands, read files, or search. Work only from the text above. Think
through each case, then reply with exactly one JSON array and nothing else, one object per case in
order:

{"id": <case id>, "band": <number, "requested", "inherited" or null>, "candidates": [...],
 "skills": [...]}

`candidates` is the ordered list the procedure produces, as strings: `"model:effort"` for your
host's model, `"host model:effort"` for an external candidate, `"-"` for the root, `"inherit"` for
an inherited model. `skills` is the ordered list of skill names the skills rule has you load, `[]`
for none. When the procedure or the skills rule says to stop and report, or the task or grades are
invalid, reply {"id": <case id>, "error": "<at most 12 words>"} for that case instead."""


def selection_text() -> str:
    text = (SKILL / "references/delegation.md").read_text()
    match = re.search(r"(?ms)^## 1\. Grade\n.*?(?=^## 3\. )", text)
    assert match is not None
    return match[0].strip()


def skills_text() -> str:
    text = (SKILL / "SKILL.md").read_text()
    match = re.search(r"(?ms)^- Otherwise, use the matched task's skills.*?report the issue\.$", text)
    assert match is not None
    return match[0]


def tables(directory: Path, names: list[str]) -> str:
    parts = []
    for name in names:
        parts.append(f"### Profile `{name}`")
        for table in ("profile.tsv", "tasks.tsv", "routes.tsv"):
            parts.append(f"{table}:\n```\n{(directory / name / table).read_text().strip()}\n```")
    return "\n\n".join(parts)


def prompt(selected: list[dict], directory: Path) -> str:
    names = sorted({item["profile"] for item in selected})
    lines = [json.dumps({key: value for key, value in item.items()}, separators=(",", ":"))
             for item in selected]
    return f"""You are the main agent in a coding session. For each case below, decide where the
routing profile sends a task by applying the procedure mechanically to the tables; do not use
judgment about what the task deserves. Grades are [risk, complexity, ambiguity]. `host` is the
harness running your session, or null when it cannot be determined. `models` is the model set your
host's subagent tool advertises, or null when it advertises none. `request` is a model and effort
the user asked for, as host:model:effort, or null. `inherit` says whether the parent's model and
effort are inherited. `installed` is the skills installed in your session; no skill beyond the
task's own is useful for any case.

## Profiles

{tables(directory, names)}

## Procedure

{selection_text()}

## Skills

The skill gives this rule for the task a case matches:

{skills_text()}

## Cases

```
{chr(10).join(lines)}
```

{OUTPUT}
"""


def ask(host: str, model: str, text: str, cwd: Path) -> str:
    stdin_text: str | None = text
    if host == "claude":
        command = ["claude", "-p", "--model", model, "--output-format", "text", "--tools", "",
                   "--no-session-persistence"]
    elif host == "antigravity":
        command = ["agy", "--model", model, "--output-format", "text",
                   "--disable-slash-commands", "-p", text]
        stdin_text = None
    else:
        command = ["codex", "exec", "-m", model, "-s", "read-only", "--skip-git-repo-check",
                   "--ephemeral", "-"]
    result = subprocess.run(command, input=stdin_text, cwd=cwd, text=True, capture_output=True,
                            check=False)
    if result.returncode:
        raise SystemExit(f"{command[0]} failed: {result.stderr.strip()}")
    return result.stdout


def parse(output: str) -> dict[int, dict]:
    start, end = output.find("["), output.rfind("]")
    if start < 0 or end < 0:
        raise SystemExit(f"No JSON array in the reply:\n{output}")
    return {int(item["id"]): item for item in json.loads(output[start:end + 1])}


def score(selected: list[dict], answers: dict[int, dict], directory: Path) -> list[str]:
    mismatches = []
    for item in selected:
        truth = cases.expected(item, directory)
        answer = answers.get(item["id"])
        if answer is None:
            mismatches.append(f"case {item['id']}: no answer")
        elif "error" in truth:
            if "error" not in answer:
                mismatches.append(f"case {item['id']}: expected an error, got {answer}")
        elif answer.get("candidates") != truth["candidates"] or (
                truth["band"] is not None and answer.get("band") != truth["band"]) or (
                answer.get("skills", []) != truth["skills"]):
            mismatches.append(f"case {item['id']}: expected {truth}, got {answer}")
    return mismatches


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--host", required=True, choices=["codex", "claude", "antigravity"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", help="comma-separated case ids; default all")
    parser.add_argument("--show-prompt", action="store_true")
    args = parser.parse_args(argv)
    wanted = {int(part) for part in args.cases.split(",")} if args.cases else None
    selected = [item for item in cases.CASES if wanted is None or item["id"] in wanted]
    with tempfile.TemporaryDirectory() as temporary:
        directory = cases.materialize(Path(temporary) / "profiles")
        text = prompt(selected, directory)
        if args.show_prompt:
            print(text)
            return 0
        answers = parse(ask(args.host, args.model, text, Path(temporary)))
        mismatches = score(selected, answers, directory)
    for line in mismatches:
        print(line)
    print(f"{args.host} {args.model}: {len(selected) - len(mismatches)}/{len(selected)} correct")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
