#!/usr/bin/env python3
"""Lint Polyagent profiles and select routing candidates.

    profiles.py lint PROFILE_DIR...
    profiles.py select PROFILE_DIR --host HOST --action A --deliverable D --grades R,C,A
                [--role root|delegate] [--models HOST=m1,m2]... [--request HOST:MODEL:EFFORT]
                [--inherit]

`select` is the reference oracle for the procedure in references/delegation.md. It prints a JSON
object with the band and the ordered candidates: `MODEL:EFFORT` for the session's own host,
`HOST MODEL:EFFORT` for a callout, and `-` for the main agent, which always ends the list. The
object also carries the task's required skills, in table order.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEADERS = {
    "profile.tsv": ["key", "value"],
    "tasks.tsv": ["action", "deliverable", "route", "description", "skills"],
    "routes.tsv": ["host", "route", "difficulty", "model", "effort"],
}
PROFILE_KEYS = ["directive", "callouts", "reuse_agents"]
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PROFILE_NAME = re.compile(r"^[a-z0-9]+([.-][a-z0-9]+)*$")


class ProfileError(Exception):
    pass


def read_table(path: Path) -> list[list[str]]:
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise ProfileError(f"{path}: missing") from None
    except UnicodeDecodeError:
        raise ProfileError(f"{path}: not UTF-8") from None
    if not text.endswith("\n"):
        raise ProfileError(f"{path}: no trailing newline")
    rows = [line.split("\t") for line in text.splitlines()]
    header = HEADERS[path.name]
    if not rows or rows[0] != header:
        raise ProfileError(f"{path}: header must be {chr(9).join(header)!r}")
    for number, row in enumerate(rows[1:], 2):
        if len(row) != len(header) or any(cell.strip() != cell or not cell for cell in row):
            raise ProfileError(f"{path}:{number}: expected {len(header)} non-empty columns")
    return rows[1:]


def load(directory: Path) -> dict:
    """Read a profile and apply the shape rules the skill enforces, plus the stricter lint rules."""
    directory = Path(directory)
    if not PROFILE_NAME.match(directory.name):
        raise ProfileError(f"{directory}: profile names use lowercase letters, digits, '.' and '-'")
    profile = {row[0]: row[1] for row in read_table(directory / "profile.tsv")}
    if list(profile) != PROFILE_KEYS:
        raise ProfileError(f"{directory / 'profile.tsv'}: keys must be {', '.join(PROFILE_KEYS)}")
    if profile["reuse_agents"] not in ("on", "off"):
        raise ProfileError(f"{directory / 'profile.tsv'}: reuse_agents must be on or off")
    callouts = [] if profile["callouts"] == "-" else profile["callouts"].split(",")
    if any(not NAME.match(host) for host in callouts) or len(set(callouts)) != len(callouts):
        raise ProfileError(f"{directory / 'profile.tsv'}: callouts is '-' or distinct host names")

    tasks: dict[tuple[str, str], dict] = {}
    for number, (action, deliverable, route, description, skills) in enumerate(
        read_table(directory / "tasks.tsv"), 2
    ):
        where = f"{directory / 'tasks.tsv'}:{number}"
        if not (NAME.match(action) and NAME.match(deliverable)):
            raise ProfileError(f"{where}: action and deliverable are kebab-case names")
        if route != "-" and not NAME.match(route):
            raise ProfileError(f"{where}: route is '-' or a kebab-case name")
        if skills != "-" and any(not NAME.match(skill) for skill in skills.split(",")):
            raise ProfileError(f"{where}: skills is '-' or comma-separated skill names")
        if (action, deliverable) in tasks:
            raise ProfileError(f"{where}: duplicate task {action} {deliverable}")
        tasks[(action, deliverable)] = {
            "route": route, "description": description,
            "skills": [] if skills == "-" else skills.split(","),
        }

    routes: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
    for number, (host, route, difficulty, model, effort) in enumerate(
        read_table(directory / "routes.tsv"), 2
    ):
        where = f"{directory / 'routes.tsv'}:{number}"
        if not (NAME.match(host) and NAME.match(route)):
            raise ProfileError(f"{where}: host and route are kebab-case names")
        if not difficulty.isdigit() or not 1 <= int(difficulty) <= 10:
            raise ProfileError(f"{where}: difficulty is 1 to 10")
        if (model == "-") != (effort == "-") or " " in model or " " in effort:
            raise ProfileError(f"{where}: '-' model with '-' effort, or a model with an effort")
        band = int(difficulty)
        rows = routes.setdefault((host, route), [])
        if rows and band < rows[-1][0]:
            raise ProfileError(f"{where}: difficulty decreases within {host} {route}")
        if rows and rows[-1][0] == band and rows[-1][1] == "-":
            raise ProfileError(f"{where}: '-' ends the band for {host} {route} {band}")
        rows.append((band, model, effort))
    for (host, route), rows in routes.items():
        if rows[-1][0] != 10:
            raise ProfileError(f"{directory / 'routes.tsv'}: {host} {route} must end at 10")
    hosts = sorted({host for host, _ in routes})
    for host in hosts:
        for route in {route for _, route in routes}:
            if (host, route) not in routes:
                raise ProfileError(f"{directory / 'routes.tsv'}: {host} lacks route {route}")
    used = {task["route"] for task in tasks.values()} - {"-"}
    for route in used - {route for _, route in routes}:
        raise ProfileError(f"{directory / 'tasks.tsv'}: route {route} is not in routes.tsv")
    for route in {route for _, route in routes} - used:
        raise ProfileError(f"{directory / 'routes.tsv'}: route {route} is not used by tasks.tsv")
    return {"name": directory.name, "profile": profile, "callouts": callouts,
            "tasks": tasks, "routes": routes, "hosts": hosts}


def band(data: dict, host: str, route: str, difficulty: int) -> tuple[int, list]:
    rows = data["routes"].get((host, route))
    if rows is None:
        raise ProfileError(f"{data['name']}: no rows for {host} {route}")
    chosen = next(bound for bound, _, _ in rows if bound >= difficulty)
    return chosen, [(model, effort) for bound, model, effort in rows if bound == chosen]


def select(data: dict, host: str | None, action: str, deliverable: str, grades: tuple[int, int, int],
           role: str = "root", models: dict[str, list[str]] | None = None,
           request: tuple[str, str, str] | None = None, inherit: bool = False,
           installed: list[str] | None = None) -> dict:
    """Apply the selection procedure; see references/delegation.md section 2.

    The result carries the task's required skills. When `installed` lists the session's skills, a
    required skill it lacks is an error, as SKILL.md section 3 stops on a missing skill.
    """
    if any(not 1 <= grade <= 10 for grade in grades):
        raise ProfileError("grades are 1 to 10")
    task = data["tasks"].get((action, deliverable))
    if task is None:
        raise ProfileError(f"{data['name']}: no task {action} {deliverable}")
    for skill in task["skills"]:
        if installed is not None and skill not in installed:
            raise ProfileError(f"{data['name']}: skill {skill} is missing")
    difficulty = max(grades)
    matched = {"route": task["route"], "skills": task["skills"]}
    if task["route"] == "-":
        return {**matched, "band": None, "candidates": ["-"]}
    if inherit:
        return {**matched, "band": None, "candidates": ["inherit", "-"]}
    if request is not None:
        target_host, model, effort = request
        if host is None or target_host == host:
            return {**matched, "band": None, "candidates": [f"{model}:{effort}", "-"]}
        if role != "root" or target_host not in data["callouts"]:
            raise ProfileError(f"{data['name']}: callouts does not name {target_host}")
        return {**matched, "band": None,
                "candidates": [f"{target_host} {model}:{effort}", "-"]}
    if host is None:
        return {**matched, "band": None, "candidates": ["-"]}
    models = models or {}
    chosen, rows = band(data, host, task["route"], difficulty)
    candidates = [
        f"{model}:{effort}" for model, effort in rows
        if model != "-" and (
            host not in models
            or model in models[host]
            or f"{model}-{effort}" in models[host]
        )
    ]
    if rows[-1][0] != "-" and role == "root":
        for other in data["callouts"]:
            if other != host and (other, task["route"]) in data["routes"]:
                _, external = band(data, other, task["route"], difficulty)
                candidates += [f"{other} {model}:{effort}" for model, effort in external
                               if model != "-"]
    return {**matched, "band": chosen, "candidates": candidates + ["-"]}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    lint = commands.add_parser("lint")
    lint.add_argument("profiles", nargs="+", type=Path)
    pick = commands.add_parser("select")
    pick.add_argument("profile", type=Path)
    pick.add_argument("--host")
    pick.add_argument("--action", required=True)
    pick.add_argument("--deliverable", required=True)
    pick.add_argument("--grades", required=True, help="risk,complexity,ambiguity")
    pick.add_argument("--role", default="root", choices=["root", "delegate"])
    pick.add_argument("--models", action="append", default=[], help="HOST=m1,m2")
    pick.add_argument("--request", help="HOST:MODEL:EFFORT")
    pick.add_argument("--inherit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "lint":
            for directory in args.profiles:
                load(directory)
            return 0
        data = load(args.profile)
        grades = tuple(int(grade) for grade in args.grades.split(","))
        if len(grades) != 3:
            raise ProfileError("--grades takes three numbers")
        models = {}
        for item in args.models:
            host, _, names = item.partition("=")
            models[host] = names.split(",") if names else []
        request = tuple(args.request.split(":", 2)) if args.request else None
        if request is not None and len(request) != 3:
            raise ProfileError("--request takes HOST:MODEL:EFFORT")
        result = select(data, args.host, args.action, args.deliverable, grades,  # type: ignore[arg-type]
                        args.role, models, request, args.inherit)  # type: ignore[arg-type]
        print(json.dumps(result))
        return 0
    except ProfileError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
