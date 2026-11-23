"""Preview a local Conventional Commits release; --apply writes release preparation files."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = re.compile(r"release/v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MANIFESTS = ("plugins/polyagent/.codex-plugin/plugin.json",
             "plugins/polyagent/.claude-plugin/plugin.json",
             "plugins/polyagent/.antigravity-plugin/plugin.json")


def git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                 "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                 "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES"):
        env.pop(name, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.check_output(
        ["git", *args], cwd=root, env=env, text=True, stderr=subprocess.PIPE
    ).strip()


def bump_level(message: str) -> int:
    """Breaking changes are major even before 1.0; feat is minor, fix is patch."""
    header = re.match(r"([a-z]+)(?:\([^\n]+\))?(!)?: .+", message.splitlines()[0])
    if not header:
        return 0
    if header[2] or re.search(r"(?m)^BREAKING[ -]CHANGE: \S", message):
        return 3
    return {"feat": 2, "fix": 1}.get(header[1], 0)


def manifest_version(root: Path) -> str:
    """The plugin version, which all host manifests must state identically."""
    versions = {json.loads((root / name).read_text())["version"] for name in MANIFESTS}
    if len(versions) != 1:
        raise ValueError("The plugin manifests disagree on the version.")
    return str(versions.pop())


def prepare(root: Path, apply: bool = False) -> dict[str, object]:
    current = manifest_version(root)
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root.resolve():
        raise ValueError("Release preparation must run at the repository root.")
    tags = [tag for tag in git(root, "tag", "--merged", "HEAD").splitlines() if TAG.fullmatch(tag)]
    # Closest ancestor tag by commit distance; version breaks ties deterministically.
    tag = min(tags, key=lambda t: (int(git(root, "rev-list", "--count", f"refs/tags/{t}..HEAD")),
                                   tuple(-int(n) for n in t.removeprefix("release/v").split(".")))) if tags else None
    history = git(root, "log", "--format=%B%x00", f"refs/tags/{tag}..HEAD" if tag else "HEAD")
    messages = [message.strip() for message in history.split("\0") if message.strip()]
    level = max((bump_level(message) for message in messages), default=0)
    if tag:
        parts = [int(n) for n in tag.removeprefix("release/v").split(".")]
        if level:
            index = 3 - level
            parts[index] += 1
            parts[index + 1:] = [0] * (2 - index)
        version = ".".join(map(str, parts))
    else:
        version = current
    changed = tag is None or level > 0
    entries = [message.splitlines()[0] for message in messages if bump_level(message)] if tag else []
    section = f"## {version}\n\n" + "\n".join(f"- {entry}" for entry in entries or ["Initial release."]) + "\n"
    changelog_path = root / "CHANGELOG.md"
    previous = changelog_path.read_text() if changelog_path.exists() else "# Changelog\n"
    if tag is None:
        reviewed = re.search(r"(?ms)^## " + re.escape(version) + r"\n.*?(?=^## |\Z)", previous)
        if reviewed is not None:
            section = reviewed[0].rstrip() + "\n"
    result: dict[str, object] = {"current_version": current, "release_tag": tag,
                                "next_version": version, "release_needed": changed,
                                "changelog": section if changed else ""}
    if apply and changed:
        if git(root, "status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("Release preparation requires a clean working tree.")
        heading = f"## {version}\n"
        if heading in previous:
            changelog = re.sub(
                r"(?ms)^## " + re.escape(version) + r"\n.*?(?=^## |\Z)",
                lambda _: section + "\n", previous, count=1,
            ) if tag else previous
        else:
            changelog = previous.replace("# Changelog\n", "# Changelog\n\n" + section, 1)
        if heading not in changelog:
            raise ValueError("CHANGELOG.md must start with # Changelog.")
        for name in MANIFESTS:
            manifest = json.loads((root / name).read_text())
            manifest["version"] = version
            (root / name).write_text(json.dumps(manifest, indent=2) + "\n")
        changelog_path.write_text(changelog)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=("Uses the nearest ancestor release/vMAJOR.MINOR.PATCH tag. fix: increments patch; "
                "feat: increments minor; ! or BREAKING CHANGE increments major, including "
                "0.x (0.1.0 becomes 1.0.0). Other commits do not trigger a release. "
                "Without a release tag, prepares the version stated in the plugin manifests. "
                "--apply requires a clean tree and updates both plugin manifests and CHANGELOG.md. "
                "Commit and review these files separately; then use scripts/release_workflow.py to "
                "tag, verify, and publish. Without a canonical tag, the reviewed initial CHANGELOG "
                "section is preserved."),
    )
    parser.add_argument("--apply", action="store_true", help="write preparation files; never tag/publish")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(ROOT, args.apply), indent=2))
    except (subprocess.CalledProcessError, ValueError, OSError) as error:
        parser.exit(1, f"Release preparation failed: {error}\n")


if __name__ == "__main__":
    main()
