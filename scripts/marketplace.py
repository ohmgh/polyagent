"""Validate and publish one marketplace snapshot built from a tagged source commit."""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Never

TAG = re.compile(r"release/v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA = re.compile(r"[0-9a-f]{40}$")
MARKETPLACE_REF = "refs/heads/marketplace"
SOURCE_REPOSITORY = "https://github.com/ohmgh/polyagent"
PLUGIN = "plugins/polyagent"
SKILL = f"{PLUGIN}/skills/polyagent"
BUNDLED_PROFILES = ("general.default", "software.default")
PROFILE_FILES = {
    f"{SKILL}/profiles/{profile}/{table}"
    for profile in BUNDLED_PROFILES
    for table in ("profile.tsv", "routes.tsv", "tasks.tsv")
}
REQUIRED = {
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    f"{PLUGIN}/.codex-plugin/plugin.json",
    f"{PLUGIN}/.claude-plugin/plugin.json",
    f"{PLUGIN}/LICENSE",
    f"{SKILL}/SKILL.md",
    f"{SKILL}/agents/openai.yaml",
    f"{SKILL}/references/delegation.md",
} | PROFILE_FILES
TRAILERS = {"Source-Tag": re.compile(r"(?m)^Source-Tag: (\S+)$"),
            "Source-Commit": re.compile(r"(?m)^Source-Commit: ([0-9a-f]{40})$")}


def fail(message: str) -> Never:
    raise ValueError(message)


def git(root: Path, *args: str, check: bool = True) -> str:
    environment = os.environ.copy()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                 "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"):
        environment.pop(name, None)
    run = subprocess.run(["git", *args], cwd=root, env=environment, text=True,
                         capture_output=True, check=False)
    if check and run.returncode:
        fail(f"git {' '.join(args)}: {run.stderr.strip()}")
    return run.stdout.strip()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_tuple(value: str) -> tuple[int, int, int]:
    match = TAG.fullmatch("release/v" + value)
    if match is None:
        fail(f"Invalid release version: {value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def source_check(root: Path, tag: str, main: str = "origin/main") -> dict[str, str]:
    match = TAG.fullmatch(tag)
    if match is None:
        fail("Source tag must be canonical release/vMAJOR.MINOR.PATCH.")
    commit = git(root, "rev-parse", "HEAD")
    if not SHA.fullmatch(commit) or git(root, "status", "--porcelain", "--untracked-files=normal"):
        fail("Source checkout must have a known commit and clean working tree.")
    actual = git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if actual != commit or git(root, "tag", "--points-at", "HEAD").splitlines().count(tag) != 1:
        fail("Source must be exactly the requested canonical tag.")
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", commit, main],
                              cwd=root, check=False).returncode == 0
    if not ancestor:
        fail("Source tag is not in main history.")
    return {"tag": tag, "commit": commit, "version": ".".join(match.groups())}


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (name != "" and not name.startswith("/") and "\\" not in name
            and all(part not in ("", ".", "..") for part in name.split("/"))
            and str(path) == name)


def inventory(root: Path) -> dict[str, dict[str, str | int]]:
    """Exactly the required regular files, all mode 0644, in exactly their directories."""
    if not root.is_dir() or root.is_symlink():
        fail("Candidate directory is missing or linked.")
    found: dict[str, dict[str, str | int]] = {}
    directories: set[str] = set()
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if not safe_name(name) or path.is_symlink() or \
                any(part in {".git", ".gitattributes", ".gitmodules"} for part in name.split("/")):
            fail(f"Unsafe candidate entry: {name}")
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            directories.add(name)
            continue
        if not stat.S_ISREG(mode):
            fail(f"Unsupported candidate entry: {name}")
        if path.lstat().st_nlink != 1:
            fail(f"Hard-linked candidate entry: {name}")
        if stat.S_IMODE(mode) != 0o644:
            fail(f"Unsupported candidate file mode: {name}")
        found[name] = {"sha256": digest(path.read_bytes()), "mode": 0o644}
    if not REQUIRED <= found.keys():
        fail(f"Missing marketplace files: {sorted(REQUIRED - found.keys())}")
    expected_directories = {
        str(parent) for name in found for parent in PurePosixPath(name).parents
        if str(parent) != "."
    }
    if found.keys() != REQUIRED or directories != expected_directories:
        fail("Unexpected marketplace inventory.")
    return found


def inspect(root: Path, tag: str, commit: str) -> dict[str, object]:
    if not SHA.fullmatch(commit) or TAG.fullmatch(tag) is None:
        fail("Invalid source identity.")
    files = inventory(root)
    version = tag.removeprefix("release/v")
    plugin = root / PLUGIN
    for host in ("codex", "claude"):
        manifest = json.loads((plugin / f".{host}-plugin/plugin.json").read_text())
        if manifest.get("version") != version or manifest.get("name") != "polyagent":
            fail(f"{host.capitalize()} manifest identity differs from release.")
    catalog = json.loads((root / ".claude-plugin/marketplace.json").read_text())
    plugins = catalog.get("plugins")
    if catalog.get("name") != "polyagent" or \
            not isinstance(plugins, list) or len(plugins) != 1 or \
            not isinstance(plugins[0], dict) or plugins[0].get("name") != "polyagent" or \
            plugins[0].get("source") != "./plugins/polyagent":
        fail("Claude catalog must identify the single local polyagent payload.")
    catalog = json.loads((root / ".agents/plugins/marketplace.json").read_text())
    plugins = catalog.get("plugins")
    if catalog.get("name") != "polyagent" or \
            not isinstance(plugins, list) or len(plugins) != 1 or \
            not isinstance(plugins[0], dict) or plugins[0].get("name") != "polyagent" or \
            plugins[0].get("source") != {"source": "local", "path": "./plugins/polyagent"}:
        fail("Catalog must identify the single local polyagent payload.")
    return {"source_tag": tag, "source_commit": commit, "version": version, "files": files}


def source_match(repository: Path, candidate: Path, commit: str) -> None:
    """The candidate's plugin files are the source commit's plugin files, byte for byte."""
    listed = git(repository, "ls-tree", "-r", "--name-only", commit, "--", PLUGIN).splitlines()
    expected = {name for name in inventory(candidate) if name.startswith(PLUGIN + "/")}
    if set(listed) | {f"{PLUGIN}/LICENSE"} != expected:
        fail("Candidate plugin files differ from the source commit.")
    for name in sorted(expected):
        source = "LICENSE" if name == f"{PLUGIN}/LICENSE" else name
        blob = subprocess.run(["git", "cat-file", "blob", f"{commit}:{source}"], cwd=repository,
                              capture_output=True, check=False)
        if blob.returncode or blob.stdout != (candidate / name).read_bytes():
            fail(f"Candidate file differs from the source commit: {name}")


def published_identity(root: Path, commit: str) -> dict[str, str | None]:
    """Version from the published manifest; source trailers from the publishing commit."""
    manifest = json.loads(git(root, "show", f"{commit}:{PLUGIN}/.codex-plugin/plugin.json"))
    message = git(root, "log", "-1", "--format=%B", commit)
    found = {key: pattern.search(message) for key, pattern in TRAILERS.items()}
    return {"version": str(manifest["version"]),
            "source_tag": found["Source-Tag"][1] if found["Source-Tag"] else None,
            "source_commit": found["Source-Commit"][1] if found["Source-Commit"] else None}


def publish(repository: Path, candidate: Path, tag: str, source_commit: str,
            remote: str = "origin") -> dict[str, str | bool]:
    manifest = inspect(candidate, tag, source_commit)
    git(repository, "fetch", "--no-tags", remote, "refs/heads/main:refs/remotes/publish/main")
    git(repository, "fetch", "--no-tags", remote, f"refs/tags/{tag}:refs/tags/{tag}")
    if git(repository, "rev-parse", f"refs/tags/{tag}^{{commit}}") != source_commit:
        fail("Remote canonical source tag points to a different commit.")
    if subprocess.run(["git", "merge-base", "--is-ancestor", source_commit,
                       "refs/remotes/publish/main"], cwd=repository, check=False).returncode:
        fail("Release source is not in current remote main.")
    source_match(repository, candidate, source_commit)
    tip = git(repository, "ls-remote", remote, MARKETPLACE_REF)
    previous = tip.split()[0] if tip else ""
    if previous:
        git(repository, "fetch", "--no-tags", remote, f"{MARKETPLACE_REF}:refs/remotes/publish/marketplace")
        if git(repository, "rev-parse", "refs/remotes/publish/marketplace") != previous:
            fail("Marketplace tip changed during fetch.")
        prior = published_identity(repository, previous)
        comparison = (version_tuple(str(manifest["version"])) > version_tuple(str(prior["version"]))) \
            - (version_tuple(str(manifest["version"])) < version_tuple(str(prior["version"])))
        if comparison < 0:
            fail("Release version regressed.")
        if comparison == 0:
            previous_tree = git(repository, "rev-parse", f"{previous}^{{tree}}")
            tree = candidate_tree(repository, candidate)
            if previous_tree != tree or prior["source_commit"] != source_commit:
                fail("Same version has different source or content.")
            return {"commit": previous, "pushed": False}
        if prior["source_commit"] and subprocess.run(
                ["git", "merge-base", "--is-ancestor", prior["source_commit"], source_commit],
                cwd=repository, check=False).returncode:
            fail("Release source regressed.")
    tree = candidate_tree(repository, candidate)
    message = (f"Publish marketplace {manifest['version']} from {tag}\n\n"
               f"Source-Tag: {tag}\nSource-Commit: {source_commit}\n")
    args = ["commit-tree", tree, "-m", message]
    if previous:
        args += ["-p", previous]
    commit = git(repository, *args)
    if git(repository, "ls-remote", remote, MARKETPLACE_REF).split()[:1] != ([previous] if previous else []):
        fail("Marketplace tip changed before push.")
    if inspect(candidate, tag, source_commit) != manifest:
        fail("Candidate changed before push.")
    git(repository, "push", "--no-follow-tags", remote, f"{commit}:{MARKETPLACE_REF}")
    return {"commit": commit, "pushed": True}


def candidate_tree(repository: Path, candidate: Path) -> str:
    with tempfile.TemporaryDirectory() as temporary:
        environment = os.environ.copy()
        environment["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
        git_directory = git(repository, "rev-parse", "--absolute-git-dir")
        environment["GIT_DIR"] = git_directory
        subprocess.run(["git", "read-tree", "--empty"], cwd=repository, env=environment, check=True)
        for name, entry in inventory(candidate).items():
            data = (candidate / name).read_bytes()
            if digest(data) != entry["sha256"]:
                fail(f"Candidate changed while staging: {name}")
            blob = subprocess.check_output(
                ["git", "hash-object", "--no-filters", "-w", "--stdin"],
                input=data, cwd=repository, env=environment).decode().strip()
            subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}"],
                           cwd=repository, env=environment, check=True)
        return subprocess.check_output(["git", "write-tree"], cwd=repository, env=environment,
                                       text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    source = sub.add_parser("source-check")
    source.add_argument("root", type=Path)
    source.add_argument("tag")
    source.add_argument("--main", default="origin/main")
    check = sub.add_parser("check")
    check.add_argument("candidate", type=Path)
    check.add_argument("tag")
    check.add_argument("commit")
    push = sub.add_parser("publish")
    push.add_argument("repository", type=Path)
    push.add_argument("candidate", type=Path)
    push.add_argument("tag")
    push.add_argument("source_commit")
    push.add_argument("--remote", default="origin")
    args = parser.parse_args()
    try:
        if args.command == "source-check":
            result = source_check(args.root, args.tag, args.main)
        elif args.command == "check":
            result = inspect(args.candidate, args.tag, args.commit)
        else:
            result = publish(args.repository, args.candidate, args.tag, args.source_commit,
                             args.remote)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, f"Marketplace publication failed: {error}\n")


if __name__ == "__main__":
    main()
