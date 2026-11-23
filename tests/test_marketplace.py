"""Publication boundaries use real local Git remotes and candidates matched to their source."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "marketplace", Path(__file__).resolve().parents[1] / "scripts/marketplace.py")
assert SPEC is not None and SPEC.loader is not None
marketplace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(marketplace)
PROFILES = ("general.default", "software.default")
TABLES = ("profile.tsv", "routes.tsv", "tasks.tsv")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


def plugin_files(version: str, marker: str = "A") -> dict[str, bytes]:
    """The plugin tree that a source commit and its candidate share."""
    manifest = json.dumps({"name": "polyagent", "version": version}).encode() + b"\n"
    files = {
        "skills/polyagent/SKILL.md": f"# Polyagent {marker}\n".encode(),
        "skills/polyagent/references/delegation.md": b"delegate\n",
        "skills/polyagent/agents/openai.yaml": b"interface: {}\n",
        ".codex-plugin/plugin.json": manifest,
        ".claude-plugin/plugin.json": manifest,
        ".antigravity-plugin/plugin.json": manifest,
    }
    for profile in PROFILES:
        for table in TABLES:
            files[f"skills/polyagent/profiles/{profile}/{table}"] = b"test\n"
    return files


def write_tree(root: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def candidate(root: Path, version: str, marker: str = "A") -> Path:
    tree = root / "candidate"
    if tree.exists():
        shutil.rmtree(tree)
    write_tree(tree / "plugins/polyagent", plugin_files(version, marker) | {"LICENSE": b"MIT\n"})
    write_json(tree / ".claude-plugin/marketplace.json", {"name": "polyagent",
        "plugins": [{"name": "polyagent", "source": "./plugins/polyagent"}]})
    write_json(tree / ".agents/plugins/marketplace.json", {"name": "polyagent",
        "plugins": [{"name": "polyagent", "source": {
            "source": "local", "path": "./plugins/polyagent"}}]})
    return tree


def source_commit(work: Path, version: str, marker: str = "A") -> str:
    """Commit the plugin tree for a version on the current branch and tag it."""
    write_tree(work / "plugins/polyagent", plugin_files(version, marker))
    (work / "LICENSE").write_bytes(b"MIT\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", f"chore(release): prepare {version}")
    git(work, "tag", f"release/v{version}")
    return git(work, "rev-parse", "HEAD")


def remote_fixture(tmp_path: Path) -> tuple[Path, Path, str, str]:
    remote = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
    git(work, "config", "user.name", "Test")
    git(work, "config", "user.email", "test@example.com")
    first = source_commit(work, "0.1.0", "A")
    second = source_commit(work, "0.1.1", "B")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-q", "origin", "main", "--tags")
    return remote, work, first, second


def test_source_requires_clean_exact_main_tag(tmp_path: Path) -> None:
    _, work, first, _ = remote_fixture(tmp_path)
    git(work, "checkout", "-q", "--detach", first)
    assert marketplace.source_check(work, "release/v0.1.0")["commit"] == first
    with pytest.raises(ValueError, match="canonical"):
        marketplace.source_check(work, "v0.1.0")
    with pytest.raises(ValueError, match="exactly"):
        marketplace.source_check(work, "release/v0.1.1")
    (work / "LICENSE").write_text("dirty")
    with pytest.raises(ValueError, match="clean"):
        marketplace.source_check(work, "release/v0.1.0")


def test_candidate_rejects_executables_links_and_mutation(tmp_path: Path) -> None:
    source = "a" * 40
    tree = candidate(tmp_path, "0.1.0")
    manifest = marketplace.inspect(tree, "release/v0.1.0", source)
    assert set(manifest["files"]) == marketplace.REQUIRED  # type: ignore[arg-type]
    skill = tree / "plugins/polyagent/skills/polyagent/SKILL.md"
    skill.chmod(0o755)
    with pytest.raises(ValueError, match="file mode"):
        marketplace.inspect(tree, "release/v0.1.0", source)
    skill.chmod(0o644)
    skill.write_text("mutated\n")
    assert marketplace.inspect(tree, "release/v0.1.0", source) != manifest
    skill.unlink()
    skill.symlink_to(tree / "plugins/polyagent/LICENSE")
    with pytest.raises(ValueError, match="Unsafe"):
        marketplace.inspect(tree, "release/v0.1.0", source)


def test_candidate_rejects_extra_catalog_plugin(tmp_path: Path) -> None:
    source = "c" * 40
    tree = candidate(tmp_path, "0.1.0")
    catalog = tree / ".agents/plugins/marketplace.json"
    contents = json.loads(catalog.read_text())
    contents["plugins"].append({"name": "another", "source": "./plugins/polyagent"})
    write_json(catalog, contents)
    with pytest.raises(ValueError, match="single"):
        marketplace.inspect(tree, "release/v0.1.0", source)


@pytest.mark.parametrize("missing", [
    ".claude-plugin/marketplace.json",
    "plugins/polyagent/.claude-plugin/plugin.json",
    "plugins/polyagent/.antigravity-plugin/plugin.json",
    "plugins/polyagent/LICENSE",
    "plugins/polyagent/skills/polyagent/profiles/general.default/routes.tsv",
    "plugins/polyagent/skills/polyagent/profiles/software.default/tasks.tsv",
])
def test_candidate_requires_every_file(tmp_path: Path, missing: str) -> None:
    source = "c" * 40
    tree = candidate(tmp_path, "0.1.0")
    (tree / missing).unlink()
    with pytest.raises(ValueError, match="Missing"):
        marketplace.inspect(tree, "release/v0.1.0", source)


def test_candidate_rejects_mismatched_identity(tmp_path: Path) -> None:
    source = "c" * 40
    tree = candidate(tmp_path, "0.1.0")
    write_json(tree / "plugins/polyagent/.claude-plugin/plugin.json",
               {"name": "polyagent", "version": "0.0.9"})
    with pytest.raises(ValueError, match="Claude manifest"):
        marketplace.inspect(tree, "release/v0.1.0", source)
    tree = candidate(tmp_path, "0.1.0")
    write_json(tree / "plugins/polyagent/.codex-plugin/plugin.json",
               {"name": "other", "version": "0.1.0"})
    with pytest.raises(ValueError, match="Codex manifest"):
        marketplace.inspect(tree, "release/v0.1.0", source)
    tree = candidate(tmp_path, "0.1.0")
    write_json(tree / "plugins/polyagent/.antigravity-plugin/plugin.json",
               {"name": "polyagent", "version": "0.0.9"})
    with pytest.raises(ValueError, match="Antigravity manifest"):
        marketplace.inspect(tree, "release/v0.1.0", source)
    tree = candidate(tmp_path, "0.1.0")
    write_json(tree / ".claude-plugin/marketplace.json",
               {"name": "polyagent", "plugins": [{"name": "polyagent", "source": "./elsewhere"}]})
    with pytest.raises(ValueError, match="Claude catalog"):
        marketplace.inspect(tree, "release/v0.1.0", source)


@pytest.mark.parametrize("extra", [
    "install.sh",
    "plugins/polyagent/bin/polyagent",
    "plugins/polyagent/build-info.json",
    "plugins/polyagent/notices/example-1.0/LICENSE-MIT",
    "plugins/polyagent/skills/polyagent/polyagent",
    "plugins/polyagent/skills/polyagent/profiles/extra.tsv",
    "plugins/polyagent/skills/polyagent/profiles/software.default/extra.tsv",
    "plugins/polyagent/skills/polyagent/profiles/other/profile.tsv",
    ".extra-plugin/marketplace.json",
    "plugins/polyagent/.claude-plugin/extra.json",
])
def test_candidate_rejects_unexpected_file(tmp_path: Path, extra: str) -> None:
    source = "c" * 40
    tree = candidate(tmp_path, "0.1.0")
    path = tree / extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("unexpected\n")
    with pytest.raises(ValueError, match="inventory"):
        marketplace.inspect(tree, "release/v0.1.0", source)


@pytest.mark.parametrize("extra", [
    "plugins/polyagent/skills/polyagent/profiles/extra",
    "plugins/polyagent/resources",
    ".extra-plugin",
    "plugins/polyagent/.claude-plugin/extra",
])
def test_candidate_rejects_unexpected_empty_directory(tmp_path: Path, extra: str) -> None:
    source = "c" * 40
    tree = candidate(tmp_path, "0.1.0")
    (tree / extra).mkdir(parents=True)
    with pytest.raises(ValueError, match="inventory"):
        marketplace.inspect(tree, "release/v0.1.0", source)


def test_source_match_requires_the_tagged_plugin_files(tmp_path: Path) -> None:
    _, work, first, second = remote_fixture(tmp_path)
    marketplace.source_match(work, candidate(tmp_path, "0.1.0", "A"), first)
    marketplace.source_match(work, candidate(tmp_path, "0.1.1", "B"), second)
    with pytest.raises(ValueError, match="differs from the source commit: .*SKILL.md"):
        marketplace.source_match(work, candidate(tmp_path, "0.1.0", "B"), first)
    with pytest.raises(ValueError, match="differs from the source commit: .*plugin.json"):
        marketplace.source_match(work, candidate(tmp_path, "0.1.1", "A"), first)
    (work / "plugins/polyagent/extra.txt").write_text("stale\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "feat: add a file the candidate lacks")
    with pytest.raises(ValueError, match="plugin files differ"):
        marketplace.source_match(work, candidate(tmp_path, "0.1.1", "B"), git(work, "rev-parse", "HEAD"))


def test_publisher_is_fast_forward_versioned_and_idempotent(tmp_path: Path) -> None:
    remote, work, first, second = remote_fixture(tmp_path)
    tree = candidate(tmp_path, "0.1.0", "A")
    published = marketplace.publish(work, tree, "release/v0.1.0", first)
    assert published["pushed"] is True
    first_tip = git(work, "ls-remote", str(remote), marketplace.MARKETPLACE_REF).split()[0]
    assert published["commit"] == first_tip
    assert git(work, "show", first_tip + ":plugins/polyagent/skills/polyagent/SKILL.md") == "# Polyagent A"
    assert marketplace.published_identity(work, first_tip) == {
        "version": "0.1.0", "source_tag": "release/v0.1.0", "source_commit": first}
    retry = marketplace.publish(work, tree, "release/v0.1.0", first)
    assert retry["pushed"] is False and retry["commit"] == first_tip
    (tree / "plugins/polyagent/skills/polyagent/SKILL.md").write_text("# Polyagent A2\n")
    with pytest.raises(ValueError, match="differs from the source commit"):
        marketplace.publish(work, tree, "release/v0.1.0", first)
    tree = candidate(tmp_path, "0.1.1", "B")
    newer = marketplace.publish(work, tree, "release/v0.1.1", second)
    assert newer["pushed"] is True
    assert git(work, "merge-base", "--is-ancestor", first_tip, str(newer["commit"])) == ""
    with pytest.raises(ValueError, match="regressed"):
        marketplace.publish(work, candidate(tmp_path, "0.1.0", "A"), "release/v0.1.0", first)


def test_publisher_follows_a_tip_without_source_trailers(tmp_path: Path) -> None:
    remote, work, first, _ = remote_fixture(tmp_path)
    legacy_tree = marketplace.candidate_tree(work, candidate(tmp_path, "0.0.9"))
    legacy = git(work, "commit-tree", legacy_tree, "-m", "Publish marketplace 0.0.9")
    git(work, "push", "-q", "origin", f"{legacy}:{marketplace.MARKETPLACE_REF}")
    assert marketplace.published_identity(work, legacy) == {
        "version": "0.0.9", "source_tag": None, "source_commit": None}
    published = marketplace.publish(work, candidate(tmp_path, "0.1.0", "A"), "release/v0.1.0", first)
    assert published["pushed"] is True
    assert git(work, "rev-parse", f"{published['commit']}^") == legacy
    assert git(work, "ls-remote", str(remote), marketplace.MARKETPLACE_REF).split()[0] == published["commit"]


def test_publisher_does_not_follow_unrelated_annotated_tags(tmp_path: Path) -> None:
    _, work, first, second = remote_fixture(tmp_path)
    published = marketplace.publish(work, candidate(tmp_path, "0.1.0", "A"), "release/v0.1.0", first)
    git(work, "tag", "-a", "local-only", str(published["commit"]), "-m", "Keep local")
    git(work, "config", "push.followTags", "true")

    marketplace.publish(work, candidate(tmp_path, "0.1.1", "B"), "release/v0.1.1", second)

    assert git(work, "ls-remote", "origin", "refs/tags/local-only") == ""


def test_publisher_rejects_non_main_source_and_tip_race(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    _, work, first, _ = remote_fixture(tmp_path)
    other = git(work, "commit-tree", git(work, "write-tree"), "-m", "unrelated")
    git(work, "tag", "release/v0.1.9", other)
    git(work, "push", "-q", "origin", "refs/tags/release/v0.1.9")
    with pytest.raises(ValueError, match="current remote main"):
        marketplace.publish(work, candidate(tmp_path, "0.1.9", "B"), "release/v0.1.9", other)
    tree = candidate(tmp_path, "0.1.0", "A")
    original = marketplace.git
    calls = 0

    def changed_tip(root: Path, *args: str, check: bool = True) -> str:
        nonlocal calls
        if args[:2] == ("ls-remote", "origin"):
            calls += 1
            if calls == 2:
                return "f" * 40 + "\t" + marketplace.MARKETPLACE_REF
        return original(root, *args, check=check)

    monkeypatch.setattr(marketplace, "git", changed_tip)
    with pytest.raises(ValueError, match="tip changed"):
        marketplace.publish(work, tree, "release/v0.1.0", first)
    monkeypatch.setattr(marketplace, "git", original)
    assert git(work, "ls-remote", "origin", marketplace.MARKETPLACE_REF) == ""


def test_higher_version_cannot_regress_source(tmp_path: Path) -> None:
    _, work, first, second = remote_fixture(tmp_path)
    marketplace.publish(work, candidate(tmp_path, "0.1.1", "B"), "release/v0.1.1", second)
    git(work, "checkout", "-q", "-b", "side", first)
    sideways = source_commit(work, "0.1.2", "C")
    git(work, "checkout", "-q", "main")
    git(work, "merge", "-q", "--no-ff", "-X", "theirs", "-m", "merge side", "side")
    git(work, "push", "-q", "origin", "main", "refs/tags/release/v0.1.2")
    with pytest.raises(ValueError, match="source regressed"):
        marketplace.publish(work, candidate(tmp_path, "0.1.2", "C"), "release/v0.1.2", sideways)


def test_publisher_requires_remote_tag_at_exact_source(tmp_path: Path) -> None:
    _, work, first, _ = remote_fixture(tmp_path)
    with pytest.raises(ValueError, match="tag points"):
        marketplace.publish(work, candidate(tmp_path, "0.1.1", "B"), "release/v0.1.1", first)
    with pytest.raises(ValueError, match="couldn't find remote ref"):
        marketplace.publish(work, candidate(tmp_path, "0.1.9", "A"), "release/v0.1.9", first)
    assert git(work, "ls-remote", "origin", marketplace.MARKETPLACE_REF) == ""


def test_candidate_mutation_after_staging_never_pushes(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    _, work, first, _ = remote_fixture(tmp_path)
    tree = candidate(tmp_path, "0.1.0", "A")
    original = marketplace.candidate_tree

    def mutate(root: Path, published_tree: Path) -> str:
        staged = original(root, published_tree)
        (published_tree / "plugins/polyagent/skills/polyagent/SKILL.md").write_bytes(b"changed after stage")
        return staged

    monkeypatch.setattr(marketplace, "candidate_tree", mutate)
    with pytest.raises(ValueError, match="changed before push"):
        marketplace.publish(work, tree, "release/v0.1.0", first)
    assert git(work, "ls-remote", "origin", marketplace.MARKETPLACE_REF) == ""
