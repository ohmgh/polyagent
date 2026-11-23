"""Publish a reviewed source release: its tag, its verified marketplace and its GitHub Release."""

import argparse
import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import marketplace
import release

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "ohmgh/polyagent"
ORIGINS = {"https://github.com/ohmgh/polyagent", "https://github.com/ohmgh/polyagent.git",
           "git@github.com:ohmgh/polyagent.git", "ssh://git@github.com/ohmgh/polyagent.git"}


def run(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=root, env=env, text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(f"{' '.join(args)} failed:\n{result.stdout.strip()}\n{result.stderr.strip()}")
    return result.stdout.strip()


@contextlib.contextmanager
def temporary_artifacts(root: Path) -> Iterator[Path]:
    name = os.environ.get("AGENT_ROOT_NAME", ".agents")
    if not name or name in (".", "..") or Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("AGENT_ROOT_NAME must be one safe path component.")
    directory = root / name
    if directory.is_symlink():
        raise ValueError("Agent artifact root must not be a symlink.")
    directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-", dir=directory) as temporary:
        yield Path(temporary)


def notes(root: Path, version: str) -> str:
    match = re.search(r"(?ms)^## " + re.escape(version) + r"\n(.*?)(?=^## |\Z)",
                      (root / "CHANGELOG.md").read_text())
    if match is None or not match[1].strip():
        raise ValueError("Missing reviewed CHANGELOG section.")
    return match[1].strip() + "\n"


def preflight(root: Path) -> tuple[str, str, str]:
    if Path(marketplace.git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("Run from the source repository root.")
    if marketplace.git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Release source must be clean and reviewed.")
    for direction in ((), ("--push",)):
        urls = marketplace.git(root, "remote", "get-url", *direction, "--all", "origin").splitlines()
        if len(urls) != 1 or urls[0] not in ORIGINS:
            raise ValueError("origin must identify only https://github.com/ohmgh/polyagent.")
    stock = os.environ.get("POLYAGENT_STOCK_CODEX") or shutil.which("codex") or ""
    if not stock or not Path(stock).is_file() or not os.access(stock, os.X_OK):
        raise ValueError("POLYAGENT_STOCK_CODEX must point to an executable stock Codex.")
    os.environ["POLYAGENT_STOCK_CODEX"] = str(Path(stock).resolve())
    marketplace.git(root, "fetch", "--no-tags", "origin",
                    "refs/heads/main:refs/remotes/origin/main")
    commit = marketplace.git(root, "rev-parse", "HEAD")
    run(root, "git", "merge-base", "--is-ancestor", commit, "origin/main")
    version = release.manifest_version(root)
    marketplace.version_tuple(version)
    preview = release.prepare(root)
    if preview["next_version"] != version:
        raise ValueError("Release preparation has a pending version bump.")
    body = notes(root, version)
    if preview["changelog"] and preview["release_tag"]:
        expected = str(preview["changelog"]).partition("\n")[2].strip()
        if body.strip() != expected:
            raise ValueError("CHANGELOG does not match release preparation preview.")
    return version, commit, body


def canonical_tag(root: Path, tag: str, commit: str) -> None:
    local = marketplace.git(root, "tag", "--list", tag)
    if local:
        if marketplace.git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}") != commit:
            raise ValueError("Local canonical tag conflicts with HEAD.")
    else:
        remote = marketplace.git(root, "ls-remote", "origin", f"refs/tags/{tag}")
        if remote:
            marketplace.git(root, "fetch", "--no-tags", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
            if marketplace.git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}") != commit:
                raise ValueError("Remote canonical tag conflicts with HEAD.")
        else:
            marketplace.git(root, "tag", tag, commit)
    marketplace.source_check(root, tag)
    marketplace.git(root, "push", "--no-follow-tags", "origin", f"refs/tags/{tag}:refs/tags/{tag}")


def package(root: Path, candidate: Path, tag: str, commit: str) -> dict[str, Any]:
    """Build the candidate from the tagged source and check it against the published tip."""
    version = tag.removeprefix("release/v")
    tip = marketplace.git(root, "ls-remote", "origin", marketplace.MARKETPLACE_REF)
    published = False
    if tip:
        marketplace.git(root, "fetch", "--no-tags", "origin",
                        f"{marketplace.MARKETPLACE_REF}:refs/remotes/publish/marketplace")
        identity = marketplace.published_identity(root, tip.split()[0])
        if marketplace.version_tuple(str(identity["version"])) > marketplace.version_tuple(version):
            raise ValueError("Marketplace already has a newer version.")
        published = identity["version"] == version
        if published and (identity["source_commit"] != commit or identity["source_tag"] != tag):
            raise ValueError("Published version has conflicting source.")
    if candidate == root / "dist/marketplace":
        run(root, "python3", "scripts/package.py", "build")
    elif not candidate.is_dir():
        raise ValueError("A custom candidate must already exist; builds use dist/marketplace.")
    manifest: dict[str, Any] = marketplace.inspect(candidate, tag, commit)
    marketplace.source_match(root, candidate, commit)
    if published and marketplace.candidate_tree(root, candidate) != marketplace.git(
            root, "rev-parse", f"{tip.split()[0]}^{{tree}}"):
        raise ValueError("Published version differs from the rebuilt candidate.")
    return manifest


def github_releases(root: Path) -> list[dict[str, Any]]:
    return json.loads(run(root, "gh", "release", "list", "--repo", REPOSITORY, "--limit", "1000",
                          "--json", "tagName,isDraft,isPrerelease,isLatest"))


def publish_release(root: Path, tag: str, body: str) -> None:
    """Publish the notes-only GitHub Release for the tag as latest; a rerun changes nothing."""
    version = marketplace.version_tuple(tag.removeprefix("release/v"))
    existing = None
    for item in github_releases(root):
        name = item["tagName"]
        if name == tag:
            existing = item
        elif marketplace.TAG.fullmatch(name) and not item["isDraft"] and not item["isPrerelease"] \
                and marketplace.version_tuple(name.removeprefix("release/v")) > version:
            raise ValueError("A newer GitHub Release is already published.")
    if existing is None:
        with temporary_artifacts(root) as temporary:
            (temporary / "notes.md").write_text(body)
            run(root, "gh", "release", "create", tag, "--repo", REPOSITORY, "--verify-tag",
                "--title", "Polyagent " + tag.removeprefix("release/v"),
                "--notes-file", str(temporary / "notes.md"), "--latest")
    elif existing["isPrerelease"]:
        raise ValueError("The GitHub Release for this tag is a prerelease.")
    elif existing["isDraft"] or not existing["isLatest"]:
        run(root, "gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--latest",
            "--verify-tag")


def origin_smoke(root: Path, environment: dict[str, str]) -> None:
    gh = shutil.which("gh")
    if gh is None:
        raise ValueError("gh is required for origin installation smoke.")
    # The smoke isolates HOME. Pass credentials only in memory, never in the config or logs.
    token = environment.get("GH_TOKEN") or environment.get("GITHUB_TOKEN")
    if not token:
        token = run(root, "gh", "auth", "token", "--hostname", "github.com")
    with temporary_artifacts(root) as temporary:
        config = temporary / "gitconfig"
        run(root, "git", "config", "--file", str(config), "--add", "credential.helper", "")
        run(root, "git", "config", "--file", str(config), "--add", "credential.helper",
            "!" + shlex.quote(gh) + " auth git-credential")
        run(root, "uv", "run", "pytest", "-q",
            "tests/test_git_plugin_lifecycle.py::test_actual_origin_smoke",
            env={**environment, "GH_TOKEN": token, "GIT_CONFIG_GLOBAL": str(config)})


def workflow(root: Path, candidate: Path) -> dict[str, Any]:
    def start_stage(name: str) -> str:
        print(f"Release stage: {name}", file=sys.stderr, flush=True)
        return name

    completed: list[str] = []
    stage = start_stage("preflight")
    try:
        version, commit, body = preflight(root)
        tag = "release/v" + version
        completed.append(stage)
        stage = start_stage("source tag")
        canonical_tag(root, tag, commit)
        completed.append(stage)
        stage = start_stage("package")
        manifest = package(root, candidate, tag, commit)

        def unchanged() -> None:
            if marketplace.inspect(candidate, tag, commit) != manifest:
                raise ValueError("Candidate changed during release.")
            if marketplace.source_check(root, tag)["commit"] != commit:
                raise ValueError("Source changed during release.")

        unchanged()
        completed.append(stage)
        environment = {**os.environ, "POLYAGENT_REQUIRE_NATIVE_CODEX": "1",
                       "POLYAGENT_PREBUILT_MARKETPLACE": str(candidate)}
        for name in list(environment):
            if name.startswith("POLYAGENT_GIT_ORIGIN_") or name == "POLYAGENT_REQUIRE_ORIGIN_SMOKE":
                environment.pop(name)
        stage = start_stage("verification")
        run(root, "just", "verify", env=environment)
        unchanged()
        completed.append(stage)
        stage = start_stage("marketplace publication")
        published = marketplace.publish(root, candidate, tag, commit)
        unchanged()
        completed.append(stage)
        stage = start_stage("GitHub Release publication")
        publish_release(root, tag, body)
        unchanged()
        completed.append(stage)
        stage = start_stage("origin installation smoke")
        environment.update({"POLYAGENT_REQUIRE_ORIGIN_SMOKE": "1",
                            "POLYAGENT_GIT_ORIGIN_URL": marketplace.SOURCE_REPOSITORY + ".git",
                            "POLYAGENT_GIT_ORIGIN_REF": "marketplace",
                            "POLYAGENT_GIT_ORIGIN_COMMIT": str(published["commit"]),
                            "POLYAGENT_GIT_ORIGIN_SOURCE_COMMIT": commit,
                            "POLYAGENT_GIT_ORIGIN_SOURCE_TAG": tag})
        origin_smoke(root, environment)
        unchanged()
        completed.append(stage)
        stage = start_stage("final remote verification")
        marketplace.git(root, "fetch", "--no-tags", "origin",
                        "refs/heads/main:refs/remotes/origin/main")
        run(root, "git", "merge-base", "--is-ancestor", commit, "origin/main")
        remote_tags = marketplace.git(root, "ls-remote", "origin", f"refs/tags/{tag}",
                                      f"refs/tags/{tag}^{{}}")
        tag_refs = dict(line.split()[::-1] for line in remote_tags.splitlines())
        if tag_refs.get(f"refs/tags/{tag}^{{}}", tag_refs.get(f"refs/tags/{tag}")) != commit:
            raise ValueError("Remote source tag changed during release.")
        remote_tip = marketplace.git(root, "ls-remote", "origin", marketplace.MARKETPLACE_REF)
        if remote_tip.split()[:1] != [published["commit"]]:
            raise ValueError("Remote marketplace changed during release.")
        if not any(item["tagName"] == tag and item["isLatest"] and not item["isDraft"]
                   for item in github_releases(root)):
            raise ValueError("GitHub Release is missing or not latest.")
        unchanged()
        completed.append(stage)
        return {"complete": True, "completed_stages": completed, "tag": tag,
                "source_commit": commit, "marketplace_commit": published["commit"]}
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        raise ValueError(json.dumps({"complete": False, "failed_stage": stage,
                                    "completed_stages": completed,
                                    "partial_publication_possible": stage != "preflight",
                                    "error": str(error)})) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=ROOT / "dist/marketplace")
    args = parser.parse_args()
    try:
        print(json.dumps(workflow(ROOT, args.candidate.resolve()), indent=2))
    except ValueError as error:
        parser.exit(1, f"Release workflow failed: {error}\n")


if __name__ == "__main__":
    main()
