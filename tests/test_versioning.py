import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts/release.py")
assert spec and spec.loader
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
MANIFESTS = ("plugins/polyagent/.codex-plugin/plugin.json",
             "plugins/polyagent/.claude-plugin/plugin.json",
             "plugins/polyagent/.antigravity-plugin/plugin.json")


@pytest.mark.parametrize(("message", "level"), [
    ("fix: repair", 1), ("feat(cli): add", 2), ("feat!: remove", 3),
    ("fix: change\n\nBREAKING CHANGE: old API removed", 3),
    ("docs: explain", 0), ("chore: clean", 0), ("ordinary message", 0),
])
def test_conventional_commits(message, level):
    assert release.bump_level(message) == level


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def manifest_versions(root):
    return {json.loads((root / name).read_text())["version"] for name in MANIFESTS}


@pytest.fixture
def repository(tmp_path):
    for name in MANIFESTS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        plugin = json.loads((ROOT / name).read_text())
        plugin["version"] = "0.1.0"
        path.write_text(json.dumps(plugin, indent=2) + "\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "feat: initial")
    return tmp_path


def test_initial_preview_and_apply(repository):
    assert release.prepare(repository)["next_version"] == "0.1.0"
    assert not (repository / "CHANGELOG.md").exists()
    release.prepare(repository, True)
    assert "## 0.1.0" in (repository / "CHANGELOG.md").read_text()


def test_initial_release_preserves_reviewed_changelog(repository):
    reviewed = "# Changelog\n\n## 0.1.0\n\n- Reviewed initial release.\n"
    (repository / "CHANGELOG.md").write_text(reviewed)
    git(repository, "add", "CHANGELOG.md")
    git(repository, "commit", "-qm", "docs: review initial changelog")

    result = release.prepare(repository, True)

    assert result["release_tag"] is None
    assert result["changelog"] == "## 0.1.0\n\n- Reviewed initial release.\n"
    assert (repository / "CHANGELOG.md").read_text() == reviewed


def test_release_ignores_retired_tag_namespace(repository):
    git(repository, "tag", "v0.1.0")
    git(repository, "commit", "--allow-empty", "-qm", "feat: later change")

    result = release.prepare(repository)

    assert result["release_tag"] is None
    assert result["next_version"] == "0.1.0"


def test_tagged_release_consistency(repository):
    git(repository, "tag", "release/v0.1.0")
    git(repository, "commit", "--allow-empty", "-qm", "feat: more")
    result = release.prepare(repository, True)
    assert result["next_version"] == "0.2.0"
    assert manifest_versions(repository) == {"0.2.0"}


def test_breaking_change_is_major(repository):
    git(repository, "tag", "release/v1.4.1")
    git(repository, "commit", "--allow-empty", "-qm",
        "feat!: route from profile tables\n\nBREAKING CHANGE: the runtime is gone")
    result = release.prepare(repository, True)
    assert result["next_version"] == "2.0.0"
    assert manifest_versions(repository) == {"2.0.0"}
    assert "- feat!: route from profile tables" in (repository / "CHANGELOG.md").read_text()


def test_disagreeing_manifests_are_rejected(repository):
    path = repository / MANIFESTS[1]
    plugin = json.loads(path.read_text())
    plugin["version"] = "0.0.9"
    path.write_text(json.dumps(plugin) + "\n")
    with pytest.raises(ValueError, match="disagree"):
        release.prepare(repository)


def test_no_qualifying_changes(repository):
    git(repository, "tag", "release/v0.1.0")
    git(repository, "commit", "--allow-empty", "-qm", "docs: explain")
    assert release.prepare(repository, True)["release_needed"] is False
    assert not git(repository, "status", "--porcelain")


def test_release_ignores_inherited_repository_selection(repository, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(repository / "nonexistent"))
    monkeypatch.setenv("GIT_WORK_TREE", str(repository / "wrong-tree"))
    assert release.prepare(repository)["next_version"] == "0.1.0"


def test_repeated_preparation_refreshes_pending_changelog(repository):
    (repository / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.0\n\n- Old release.\n")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "docs: changelog")
    git(repository, "tag", "release/v0.1.0")
    git(repository, "commit", "--allow-empty", "-qm", "feat: first")
    release.prepare(repository, True)
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "chore: prepare release")
    git(repository, "commit", "--allow-empty", "-qm", "fix: second")
    result = release.prepare(repository, True)
    written = (repository / "CHANGELOG.md").read_text()
    assert str(result["changelog"]) in written
    assert written.count("## 0.2.0") == 1
    assert "## 0.1.0\n\n- Old release.\n" in written
