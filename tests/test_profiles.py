"""The bundled profiles lint clean, every shape rule fails on purpose, and the oracle routes."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from eval import cases

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/profiles.py"
profiles = cases.profiles
BUNDLED = cases.BUNDLED


@pytest.fixture
def directory(tmp_path):
    return cases.materialize(tmp_path / "profiles")


def edit(directory: Path, table: str, old: str, new: str, profile: str = "software.default") -> Path:
    path = directory / profile / table
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))
    return directory / profile


@pytest.mark.parametrize("profile", ["general.default", "software.default"])
def test_bundled_profiles_lint_clean(profile):
    data = profiles.load(BUNDLED / profile)
    assert data["hosts"] == ["antigravity", "claude", "codex"]
    assert data["callouts"] == []
    assert {task["route"] for task in data["tasks"].values()} == {
        "comprehension", "investigation", "judgment", "construction", "procedure"}


def test_bundled_routes_are_grouped_by_host_then_route():
    for profile in ("general.default", "software.default"):
        rows = (BUNDLED / profile / "routes.tsv").read_text().splitlines()[1:]
        hosts = [row.split("\t")[0] for row in rows]
        assert hosts == sorted(hosts, key=hosts.index)
        assert hosts.count("codex") == hosts.count("claude") == hosts.count("antigravity")
        assert hosts[0] == "codex"
        for host in ("codex", "claude", "antigravity"):
            routes = [row.split("\t")[1] for row in rows if row.startswith(host + "\t")]
            assert routes == sorted(routes, key=routes.index)


@pytest.mark.parametrize(("table", "old", "new", "message"), [
    ("profile.tsv", "key\tvalue", "key\tsetting", "header"),
    ("tasks.tsv", "action\tdeliverable", "action\tresult", "header"),
    ("routes.tsv", "host\troute", "harness\troute", "header"),
    ("tasks.tsv", "review\tassessment\tjudgment", "review\tassessment\tverdict", "not in routes.tsv"),
    ("routes.tsv", "codex\tjudgment\t9\t", "codex\tjudgment\t6\t", "decreases"),
    ("routes.tsv", "codex\tprocedure\t10\t", "codex\tprocedure\t9\t", "end at 10"),
    ("routes.tsv", "codex\tprocedure\t2\t-\t-", "codex\tprocedure\t2\t-\tlow", "'-' effort"),
    ("routes.tsv", "codex\tprocedure\t6\tgpt-6-luna\tmedium", "codex\tprocedure\t6\tgpt-6-luna\t-",
     "'-' effort"),
    ("routes.tsv", "codex\tprocedure\t6\t", "codex\tprocedure\tsix\t", "1 to 10"),
    ("routes.tsv", "codex\tprocedure\t2\t-\t-", "codex\tprocedure\t2\t-\t-\ncodex\tprocedure\t2\tgpt-6-luna\tlow",
     "ends the band"),
    ("tasks.tsv", "design\tplan\t", "design\tarchitecture\t", "duplicate task"),
    ("tasks.tsv", "inquire\tanswer\tcomprehension", "inquire\tanswer\tjudgment", "not used"),
    ("tasks.tsv", "inquire\tanswer\t", "Inquire\tanswer\t", "kebab-case"),
    ("tasks.tsv", "inquire\tanswer\tcomprehension\t", "inquire\tanswer\tcomprehension\t\t", "columns"),
    ("tasks.tsv", "defects and risks.\t-", "defects and risks.\tcode-review,TDD", "skill names"),
    ("profile.tsv", "reuse_agents\ton", "reuse_agents\tyes", "on or off"),
    ("profile.tsv", "callouts\t-", "callouts\tclaude,claude", "callouts"),
    ("profile.tsv", "callouts\t-\n", "", "keys must be"),
    ("routes.tsv", "claude\tprocedure\t10\tsonnet\tmedium\n", "", "end at 10"),
])
def test_shape_rules_name_the_file(directory, table, old, new, message):
    profile = edit(directory, table, old, new)
    with pytest.raises(profiles.ProfileError, match=message) as error:
        profiles.load(profile)
    assert table in str(error.value) or str(profile) in str(error.value)


def test_host_lacking_a_route_is_rejected(directory):
    path = directory / "software.default/routes.tsv"
    rows = [row for row in path.read_text().splitlines() if not row.startswith("claude\tprocedure\t")]
    path.write_text("\n".join(rows) + "\n")
    with pytest.raises(profiles.ProfileError, match="claude lacks route procedure"):
        profiles.load(directory / "software.default")


def test_encoding_and_newline_rules(directory):
    path = directory / "software.default/tasks.tsv"
    path.write_text(path.read_text().rstrip("\n"))
    with pytest.raises(profiles.ProfileError, match="trailing newline"):
        profiles.load(directory / "software.default")
    path.write_bytes(b"\xff\xfe" + path.read_bytes())
    with pytest.raises(profiles.ProfileError, match="UTF-8"):
        profiles.load(directory / "software.default")
    with pytest.raises(profiles.ProfileError, match="missing"):
        profiles.load(directory / "general.default" / "nowhere")


EXPECTED = {
    1: (9, ["gpt-6.2-astra:low", "-"]),
    2: (4, ["-"]),
    3: (6, ["gpt-6.2-sol:low", "-"]),
    4: (6, ["sonnet:medium", "-"]),
    5: (10, ["opus:xhigh", "-"]),
    6: (9, ["-"]),
    7: (7, ["gpt-6.2-sol:high", "-"]),
    8: (4, ["-"]),
    9: (10, ["-"]),
    10: (10, ["fable:high", "-"]),
    11: (9, ["gpt-6.2-astra:low", "-"]),
    12: (3, ["-"]),
    13: (5, ["gpt-6.2-sol:low", "-"]),
    14: (2, ["-"]),
    15: (6, ["gpt-6-luna:medium", "-"]),
    16: (10, ["sonnet:medium", "-"]),
    17: (5, ["-"]),
    18: (8, ["gpt-6-luna:high", "-"]),
    19: (8, ["sonnet:medium", "-"]),
    20: "no task refactor change",
    21: (None, ["gpt-6-luna:low", "-"]),
    22: "callouts does not name claude",
    23: (None, ["inherit", "-"]),
    24: (9, ["gpt-6.2-astra:low", "claude opus:high", "-"]),
    25: (9, ["gpt-6.2-astra:low", "-"]),
    26: (9, ["claude opus:high", "-"]),
    27: (7, ["gpt-6.2-sol:high", "claude opus:medium", "-"]),
    28: (None, ["-"]),
    29: (8, ["gpt-6.2-sol:medium", "-"]),
    30: "grades are 1 to 10",
    31: (8, ["gpt-6.2-sol:medium", "-"]),
    32: (9, ["opus:high", "-"]),
    33: (7, ["sonnet:high", "-"]),
    34: (6, ["gpt-6-luna:medium", "-"]),
    35: (10, ["-"]),
    36: (8, ["gpt-6.2-sol:medium", "-"]),
    37: (5, ["-"]),
    38: (7, ["gpt-6-luna:medium", "-"]),
    39: (8, ["gpt-6.2-sol:medium", "-"]),
    40: (9, ["opus:high", "-"]),
    41: (6, ["gpt-6-luna:medium", "-"]),
    42: (8, ["gpt-6.2-sol:medium", "-"]),
    43: (4, ["-"]),
    44: "skill coverage is missing",
    45: (7, ["opus:medium", "-"]),
    46: (8, ["gpt-6.2-sol:medium", "-"]),
    47: (4, ["-"]),
    48: (6, ["gemini-4-hydrogen:high", "-"]),
    49: (10, ["gemini-4-neon:xhigh", "-"]),
    50: (10, ["-"]),
    51: (9, ["gemini-4-argon:medium", "-"]),
    52: (9, ["-"]),
    53: (10, ["gemini-4-argon:medium", "-"]),
    54: (9, ["gemini-4-neon:high", "claude opus:high", "-"]),
    55: (9, ["gemini-4-neon:high", "-"]),
    56: (9, ["gpt-6.2-astra:medium", "antigravity gemini-4-argon:medium", "-"]),
}
SKILLS = {42: ["tdd", "coverage"], 43: ["tdd", "coverage"], 45: ["code-review"]}


def test_every_case_has_an_expectation():
    assert {item["id"] for item in cases.CASES} == set(EXPECTED)


@pytest.mark.parametrize("item", cases.CASES, ids=lambda item: str(item["id"]))
def test_oracle_matches_hand_routing(directory, item):
    result = cases.expected(item, directory)
    want = EXPECTED[item["id"]]
    if isinstance(want, str):
        assert want in result["error"]
    else:
        assert (result["band"], result["candidates"]) == want
        assert result["skills"] == SKILLS.get(item["id"], [])


def test_cli_lint_and_select(directory, tmp_path):
    bundled = sorted(str(path) for path in BUNDLED.iterdir())
    assert subprocess.run([sys.executable, SCRIPT, "lint", *bundled], check=False).returncode == 0
    result = subprocess.run([sys.executable, SCRIPT, "select", str(directory / "team.callouts"),
                             "--host", "codex", "--action", "implement", "--deliverable", "change",
                             "--grades", "9,9,9", "--models", "codex=gpt-6-luna,gpt-6.2-sol"],
                            capture_output=True, text=True, check=True)
    assert '"candidates": ["claude opus:high", "-"]' in result.stdout
    result = subprocess.run([sys.executable, SCRIPT, "select", str(directory / "software.default"),
                             "--host", "codex", "--action", "implement", "--deliverable", "change",
                             "--grades", "9,9,9", "--request", "claude:opus:high"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1 and "callouts" in result.stderr
    broken = edit(directory, "routes.tsv", "codex\tjudgment\t9\t", "codex\tjudgment\t6\t")
    result = subprocess.run([sys.executable, SCRIPT, "lint", str(broken)], capture_output=True,
                            text=True, check=False)
    assert result.returncode == 1 and "routes.tsv:12: difficulty decreases" in result.stderr


def test_eval_prompt_uses_the_shipped_skill_text(directory):
    spec = importlib.util.spec_from_file_location("run", ROOT / "tests/eval/run.py")
    assert spec is not None and spec.loader is not None
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    text = run.prompt(cases.CASES[:2], directory)
    assert "## 2. Select" in text and "## 3. Bind" not in text
    assert "use the matched task's skills as the exact ordered prefix" in text
    assert "report the issue.\n\n## Cases" in text and "read [delegation]" not in text
    assert "host\troute\tdifficulty\tmodel\teffort" in text
    answers = {1: {"id": 1, "band": 9, "candidates": ["gpt-6.2-astra:low", "-"]},
               2: {"id": 2, "band": 5, "candidates": ["-"]}}
    mismatch = ("case 2: expected {'band': 4, 'candidates': ['-'], 'skills': []}, "
                "got {'id': 2, 'band': 5, 'candidates': ['-']}")
    assert run.score(cases.CASES[:2], answers, directory) == [mismatch]
    skilled = [item for item in cases.CASES if item["id"] in (42, 44)]
    assert "tdd,coverage" in run.prompt(skilled, directory)
    answers = {42: {"id": 42, "band": 8, "candidates": ["gpt-6.2-sol:medium", "-"],
                    "skills": ["coverage", "tdd"]},
               44: {"id": 44, "error": "coverage is missing"}}
    assert [line.split(":")[0] for line in run.score(skilled, answers, directory)] == ["case 42"]
    assert run.parse('noise [{"id": 1, "band": 9, "candidates": []}] tail') == {
        1: {"id": 1, "band": 9, "candidates": []}}
