"""Routing cases shared by the oracle tests and the model eval.

Each case names a profile, a task, grades (risk, complexity, ambiguity), the host running the
session (or None when it cannot be determined), the role, the model set the host's subagent tool
advertises (None when it advertises none), an optional user request `host:model:effort`, whether
the parent's model is inherited, and the skills installed in the session.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLED = ROOT / "plugins/polyagent/skills/polyagent/profiles"
SPEC = importlib.util.spec_from_file_location("profiles", ROOT / "scripts/profiles.py")
assert SPEC is not None and SPEC.loader is not None
profiles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiles)

CODEX = ["gpt-6-luna", "gpt-6-sol", "gpt-6.2-sol", "gpt-6.2-astra"]
CODEX_NO_ASTRA = ["gpt-6-luna", "gpt-6.2-sol"]
CLAUDE = ["sonnet", "opus", "haiku"]
CLAUDE_FABLE = ["sonnet", "opus", "haiku", "fable"]
SD, TC, TS, GD = "software.default", "team.callouts", "team.skills", "general.default"


def case(id: int, profile: str, action: str, deliverable: str, grades: tuple[int, int, int],
         host: str | None, models: list[str] | None, role: str = "root",
         request: str | None = None, inherit: bool = False,
         installed: tuple[str, ...] = ()) -> dict:
    return {"id": id, "profile": profile, "action": action, "deliverable": deliverable,
            "grades": list(grades), "host": host, "role": role, "models": models,
            "request": request, "inherit": inherit, "installed": list(installed)}


CASES = [
    case(1, SD, "implement", "change", (7, 9, 4), "codex", CODEX),
    case(2, SD, "implement", "change", (4, 4, 4), "codex", CODEX),
    case(3, SD, "implement", "change", (5, 2, 1), "codex", CODEX),
    case(4, SD, "implement", "change", (6, 6, 6), "claude", CLAUDE),
    case(5, SD, "implement", "change", (10, 1, 1), "claude", CLAUDE),
    case(6, SD, "implement", "change", (9, 9, 9), "codex", CODEX_NO_ASTRA),
    case(7, SD, "review", "assessment", (3, 7, 2), "codex", CODEX),
    case(8, SD, "review", "assessment", (4, 4, 4), "codex", CODEX),
    case(9, SD, "review", "assessment", (10, 3, 3), "claude", CLAUDE),
    case(10, SD, "review", "assessment", (10, 3, 3), "claude", CLAUDE_FABLE),
    case(11, SD, "diagnose", "root-cause", (8, 2, 2), "codex", CODEX),
    case(12, SD, "diagnose", "root-cause", (3, 3, 3), "codex", CODEX),
    case(13, SD, "diagnose", "root-cause", (4, 1, 1), "codex", CODEX),
    case(14, SD, "execute", "test-results", (2, 2, 2), "claude", CLAUDE),
    case(15, SD, "execute", "test-results", (3, 1, 1), "codex", CODEX),
    case(16, SD, "execute", "test-results", (7, 1, 1), "claude", CLAUDE),
    case(17, SD, "inquire", "answer", (5, 5, 5), "codex", CODEX),
    case(18, SD, "inquire", "answer", (6, 1, 1), "codex", CODEX),
    case(19, SD, "inquire", "answer", (6, 1, 1), "claude", CLAUDE),
    case(20, SD, "refactor", "change", (7, 7, 7), "codex", CODEX),
    case(21, SD, "implement", "change", (9, 9, 9), "codex", CODEX, request="codex:gpt-6-luna:low"),
    case(22, SD, "implement", "change", (9, 9, 9), "codex", CODEX, request="claude:opus:high"),
    case(23, SD, "implement", "change", (9, 9, 9), "codex", CODEX, inherit=True),
    case(24, TC, "implement", "change", (9, 9, 9), "codex", CODEX),
    case(25, TC, "implement", "change", (9, 9, 9), "codex", CODEX, role="delegate"),
    case(26, TC, "implement", "change", (9, 9, 9), "codex", CODEX_NO_ASTRA),
    case(27, TC, "review", "assessment", (7, 7, 7), "codex", CODEX),
    case(28, SD, "implement", "change", (7, 7, 7), None, None),
    case(29, SD, "implement", "change", (7, 7, 7), "codex", None),
    case(30, SD, "implement", "change", (11, 1, 1), "codex", CODEX),
    case(31, SD, "implement", "tests", (8, 8, 8), "codex", CODEX),
    case(32, SD, "design", "plan", (9, 1, 1), "claude", CLAUDE),
    case(33, SD, "research", "evidence-report", (7, 7, 7), "claude", CLAUDE),
    case(34, SD, "execute", "operation-result", (6, 6, 5), "codex", CODEX),
    case(35, SD, "investigate", "codebase-map", (9, 10, 2), "claude", CLAUDE),
    case(36, GD, "evaluate", "assessment", (6, 6, 6), "codex", CODEX),
    case(37, GD, "create", "artifact", (5, 5, 5), "claude", CLAUDE),
    case(38, GD, "execute", "operation-result", (4, 4, 4), "codex", CODEX),
    case(39, SD, "implement", "change", (1, 1, 8), "codex", CODEX),
    case(40, TC, "implement", "change", (9, 9, 9), "claude", CLAUDE),
    case(41, SD, "execute", "test-results", (5, 6, 4), "codex", CODEX_NO_ASTRA),
    case(42, TS, "implement", "tests", (8, 8, 8), "codex", CODEX,
         installed=("code-review", "coverage", "tdd")),
    case(43, TS, "implement", "tests", (2, 2, 2), "codex", CODEX,
         installed=("code-review", "coverage", "tdd")),
    case(44, TS, "implement", "tests", (8, 8, 8), "codex", CODEX, installed=("code-review", "tdd")),
    case(45, TS, "review", "assessment", (7, 7, 7), "claude", CLAUDE,
         installed=("code-review", "coverage", "tdd")),
    case(46, TS, "implement", "change", (7, 7, 7), "codex", CODEX,
         installed=("code-review", "coverage", "tdd")),
]


def materialize(directory: Path) -> Path:
    """Copy the bundled profiles and add two variants of software.default.

    team.callouts names Claude in `callouts`. team.skills requires skills for two tasks; the bundled
    profiles require none, so it is the only place a non-empty skills list is exercised.
    """
    shutil.copytree(BUNDLED, directory, dirs_exist_ok=True)
    for name, table, changes in (
        (TC, "profile.tsv", [("callouts\t-\n", "callouts\tclaude\n")]),
        (TS, "tasks.tsv", [("defects and risks.\t-\n", "defects and risks.\tcode-review\n"),
                           ("test definitions.\t-\n", "test definitions.\ttdd,coverage\n")]),
    ):
        shutil.copytree(BUNDLED / SD, directory / name, dirs_exist_ok=True)
        path = directory / name / table
        text = path.read_text()
        for old, new in changes:
            assert old in text, old
            text = text.replace(old, new)
        path.write_text(text)
    return directory


def expected(item: dict, directory: Path) -> dict:
    """What the reference oracle selects for a case: band, candidates and skills, or an error."""
    data = profiles.load(directory / item["profile"])
    models = {item["host"]: item["models"]} if item["models"] is not None and item["host"] else None
    request = tuple(item["request"].split(":")) if item["request"] else None
    try:
        result = profiles.select(data, item["host"], item["action"], item["deliverable"],
                                 tuple(item["grades"]), item["role"], models, request,
                                 item["inherit"], item["installed"])
    except profiles.ProfileError as error:
        return {"error": str(error)}
    return {"band": result["band"], "candidates": result["candidates"], "skills": result["skills"]}
