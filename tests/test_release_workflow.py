"""Release orchestration uses local fixtures and fake commands, never hosted publication."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_marketplace import candidate as make_candidate

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("release_workflow", SCRIPTS / "release_workflow.py")
assert SPEC is not None and SPEC.loader is not None
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)
sys.path.pop(0)

COMMIT = "a" * 40
TAG = "release/v1.0.0"


@pytest.fixture
def built(tmp_path):
    candidate = make_candidate(tmp_path, "1.0.0")
    return candidate, workflow.marketplace.inspect(candidate, TAG, COMMIT)


def setup_workflow(monkeypatch, built):
    _candidate, manifest = built
    events = []
    monkeypatch.setattr(workflow, "preflight", lambda root: ("1.0.0", COMMIT, "Notes.\n"))
    monkeypatch.setattr(workflow, "canonical_tag", lambda *args: events.append("tag"))
    monkeypatch.setattr(workflow, "package", lambda *args: manifest)
    monkeypatch.setattr(workflow.marketplace, "source_check", lambda *args: {"commit": COMMIT})
    def git(root, *args):
        if args[0] == "ls-remote":
            if args[-1] == workflow.marketplace.MARKETPLACE_REF:
                return "b" * 40 + "\trefs/heads/marketplace"
            return COMMIT + "\trefs/tags/" + TAG
        return ""
    monkeypatch.setattr(workflow.marketplace, "git", git)
    monkeypatch.setattr(workflow, "run", lambda root, *args, **kw: events.append(args[0]))
    def publish(*args):
        events.append("marketplace")
        return {"commit": "b" * 40, "pushed": True}
    monkeypatch.setattr(workflow.marketplace, "publish", publish)
    monkeypatch.setattr(workflow, "publish_release", lambda *args: events.append("release"))
    monkeypatch.setattr(workflow, "github_releases", lambda root: [
        {"tagName": TAG, "isDraft": False, "isPrerelease": False, "isLatest": True}])
    monkeypatch.setattr(workflow, "origin_smoke", lambda *args: events.append("smoke"))
    return events


def test_successful_order_and_final_identity(tmp_path, monkeypatch, built):
    events = setup_workflow(monkeypatch, built)
    result = workflow.workflow(tmp_path, built[0])
    assert result["complete"]
    assert events == ["tag", "just", "marketplace", "release", "smoke", "git"]
    assert result["marketplace_commit"] == "b" * 40 and result["tag"] == TAG


@pytest.mark.parametrize("failed", ["verification", "origin installation smoke"])
def test_failure_exposes_partial_state_and_retry(tmp_path, monkeypatch, built, failed):
    events = setup_workflow(monkeypatch, built)
    def fail(*args, **kwargs):
        raise ValueError("injected failure")
    target = "run" if failed == "verification" else "origin_smoke"
    original = getattr(workflow, target)
    monkeypatch.setattr(workflow, target, fail)
    with pytest.raises(ValueError) as error:
        workflow.workflow(tmp_path, built[0])
    status = json.loads(str(error.value))
    assert status["failed_stage"] == failed
    assert status["partial_publication_possible"]
    if failed == "verification":
        assert "marketplace" not in events
    else:
        assert "marketplace publication" in status["completed_stages"]
    monkeypatch.setattr(workflow, target, original)
    assert workflow.workflow(tmp_path, built[0])["complete"]


def test_mutation_during_verification_stops_publication(tmp_path, monkeypatch, built):
    events = setup_workflow(monkeypatch, built)
    skill = built[0] / "plugins/polyagent/skills/polyagent/SKILL.md"
    monkeypatch.setattr(workflow, "run", lambda *args, **kw: skill.write_bytes(b"changed"))
    with pytest.raises(ValueError, match="verification"):
        workflow.workflow(tmp_path, built[0])
    assert "marketplace" not in events


def test_local_tag_conflict_never_pushes(tmp_path, monkeypatch):
    calls = []
    def git(root, *args):
        calls.append(args)
        return TAG if args[0] == "tag" else "c" * 40
    monkeypatch.setattr(workflow.marketplace, "git", git)
    with pytest.raises(ValueError, match="conflicts"):
        workflow.canonical_tag(tmp_path, TAG, COMMIT)
    assert all(args[0] != "push" for args in calls)


def test_dirty_source_stops_before_remote_access(tmp_path, monkeypatch):
    def git(root, *args):
        if args[0] == "rev-parse":
            return str(tmp_path)
        if args[0] == "status":
            return " M README.md"
        pytest.fail("must not access remote")
    monkeypatch.setattr(workflow.marketplace, "git", git)
    with pytest.raises(ValueError, match="clean"):
        workflow.preflight(tmp_path)


def test_newer_marketplace_is_rejected(tmp_path, monkeypatch, built):
    monkeypatch.setattr(workflow.marketplace, "git", lambda *args: "b" * 40)
    monkeypatch.setattr(workflow.marketplace, "published_identity",
                        lambda *args: {"version": "2.0.0", "source_tag": None, "source_commit": None})
    monkeypatch.setattr(workflow, "run", lambda *args: pytest.fail("must not build"))
    with pytest.raises(ValueError, match="newer"):
        workflow.package(tmp_path, built[0], TAG, COMMIT)


def test_published_version_with_other_source_is_rejected(tmp_path, monkeypatch, built):
    monkeypatch.setattr(workflow.marketplace, "git", lambda *args: "b" * 40)
    monkeypatch.setattr(workflow.marketplace, "published_identity", lambda *args: {
        "version": "1.0.0", "source_commit": "c" * 40, "source_tag": TAG})
    monkeypatch.setattr(workflow, "run", lambda *args: pytest.fail("must not build"))
    with pytest.raises(ValueError, match="conflicting source"):
        workflow.package(tmp_path, built[0], TAG, COMMIT)


def test_default_candidate_is_rebuilt_from_source(tmp_path, monkeypatch):
    default = tmp_path / "dist/marketplace"
    default.mkdir(parents=True)
    (default / "stale").write_text("left over from an earlier build\n")
    commands = []
    def build(root, *args, **kwargs):
        commands.append(args)
        import shutil
        shutil.rmtree(default)
        make_candidate(tmp_path, "1.0.0").rename(default)
    matched = []
    monkeypatch.setattr(workflow.marketplace, "git", lambda *args: "")
    monkeypatch.setattr(workflow, "run", build)
    monkeypatch.setattr(workflow.marketplace, "source_match",
                        lambda root, candidate, commit: matched.append((candidate, commit)))
    manifest = workflow.package(tmp_path, default, TAG, COMMIT)
    assert commands == [("python3", "scripts/package.py", "build")]
    assert matched == [(default, COMMIT)] and manifest["version"] == "1.0.0"
    with pytest.raises(ValueError, match="must already exist"):
        workflow.package(tmp_path, tmp_path / "missing", TAG, COMMIT)


def local_repository(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True,
                                       stderr=subprocess.PIPE).strip()
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    for host in ("codex", "claude", "antigravity"):
        path = root / f"plugins/polyagent/.{host}-plugin/plugin.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"name": "polyagent", "version": "1.0.0"}\n')
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0\n\nInitial release.\n")
    git("add", ".")
    git("commit", "-m", "chore: prepare initial release")
    git("remote", "add", "origin", str(remote))
    git("push", "-q", "-u", "origin", "main")
    return root, git


def test_real_git_tag_push_is_idempotent_and_conflicts_fail(tmp_path):
    root, git = local_repository(tmp_path)
    commit = git("rev-parse", "HEAD")
    git("tag", "-a", "unrelated", "-m", "unrelated annotated tag")
    git("config", "push.followTags", "true")
    workflow.canonical_tag(root, TAG, commit)
    assert git("ls-remote", "origin", "refs/tags/unrelated") == ""
    before = git("ls-remote", "origin", "refs/tags/" + TAG)
    workflow.canonical_tag(root, TAG, commit)
    assert git("ls-remote", "origin", "refs/tags/" + TAG) == before
    (root / "new").write_text("change")
    git("add", ".")
    git("commit", "-m", "feat: new behavior")
    git("push", "-q", "origin", "main")
    with pytest.raises(ValueError, match="conflicts"):
        workflow.canonical_tag(root, TAG, git("rev-parse", "HEAD"))
    assert git("ls-remote", "origin", "refs/tags/" + TAG) == before


def test_unprepared_feature_commit_rejected(tmp_path, monkeypatch):
    root, git = local_repository(tmp_path)
    git("tag", TAG)
    (root / "new").write_text("feature")
    git("add", ".")
    git("commit", "-m", "feat: new behavior")
    git("push", "-q", "origin", "main")
    original = workflow.marketplace.git
    def local_git(repository, *args):
        if args[:2] == ("remote", "get-url"):
            return "https://github.com/ohmgh/polyagent.git"
        return original(repository, *args)
    monkeypatch.setattr(workflow.marketplace, "git", local_git)
    monkeypatch.setenv("POLYAGENT_STOCK_CODEX", sys.executable)
    with pytest.raises(ValueError, match="pending version bump"):
        workflow.preflight(root)


def test_prepared_release_passes_preflight(tmp_path, monkeypatch):
    root, git = local_repository(tmp_path)
    original = workflow.marketplace.git
    def local_git(repository, *args):
        if args[:2] == ("remote", "get-url"):
            return "https://github.com/ohmgh/polyagent.git"
        return original(repository, *args)
    monkeypatch.setattr(workflow.marketplace, "git", local_git)
    monkeypatch.setenv("POLYAGENT_STOCK_CODEX", sys.executable)
    assert workflow.preflight(root) == ("1.0.0", git("rev-parse", "HEAD"), "Initial release.\n")


def record(tag, draft=False, prerelease=False, latest=False):
    return {"tagName": tag, "isDraft": draft, "isPrerelease": prerelease, "isLatest": latest}


@pytest.mark.parametrize(("listed", "expected"), [
    ([record("release/v0.9.0", latest=True)], "create"),
    ([record(TAG, latest=True)], None),
    ([record(TAG, draft=True)], "edit"),
    ([record(TAG), record("release/v0.9.0", latest=True)], "edit"),
    ([record(TAG, prerelease=True)], "prerelease"),
    ([record("release/v1.1.0", latest=True)], "newer"),
])
def test_github_release_is_created_once_and_kept_latest(tmp_path, monkeypatch, listed, expected):
    commands = []
    def command(root, *args, **kwargs):
        if args[:3] == ("gh", "release", "list"):
            return json.dumps(listed)
        if args[2] == "create":
            assert Path(args[args.index("--notes-file") + 1]).read_text() == "Notes.\n"
        commands.append(args)
        return ""
    monkeypatch.setattr(workflow, "run", command)
    if expected in ("prerelease", "newer"):
        with pytest.raises(ValueError, match=expected):
            workflow.publish_release(tmp_path, TAG, "Notes.\n")
    else:
        workflow.publish_release(tmp_path, TAG, "Notes.\n")
    actions = [args[2] for args in commands]
    assert actions == ([expected] if expected in ("create", "edit") else [])
    for args in commands:
        assert args[3] == TAG and "--verify-tag" in args and "--latest" in args


def test_missing_github_release_fails_final_verification(tmp_path, monkeypatch, built):
    setup_workflow(monkeypatch, built)
    monkeypatch.setattr(workflow, "github_releases", lambda root: [record("release/v0.9.0", latest=True)])
    with pytest.raises(ValueError) as error:
        workflow.workflow(tmp_path, built[0])
    status = json.loads(str(error.value))
    assert status["failed_stage"] == "final remote verification"
    assert "GitHub Release publication" in status["completed_stages"]


def test_failed_tag_push_reports_possible_partial_publication(tmp_path, monkeypatch, built):
    setup_workflow(monkeypatch, built)
    def failure(*args):
        raise ValueError("connection lost")
    monkeypatch.setattr(workflow, "canonical_tag", failure)
    with pytest.raises(ValueError) as error:
        workflow.workflow(tmp_path, built[0])
    status = json.loads(str(error.value))
    assert status["failed_stage"] == "source tag" and status["partial_publication_possible"]


def test_artifacts_use_validated_agent_root_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ROOT_NAME", "custom-agents")
    with workflow.temporary_artifacts(tmp_path) as path:
        assert path.parent == tmp_path / "custom-agents"
        (path / "notes").write_text("temporary")
    assert not path.exists()
    monkeypatch.setenv("AGENT_ROOT_NAME", "../outside")
    with pytest.raises(ValueError, match="safe path"), workflow.temporary_artifacts(tmp_path):
        pytest.fail("invalid path accepted")


def test_prepublication_checks_clear_inherited_origin_smoke(tmp_path, monkeypatch, built):
    setup_workflow(monkeypatch, built)
    monkeypatch.setenv("POLYAGENT_GIT_ORIGIN_URL", "https://example.invalid/stale")
    monkeypatch.setenv("POLYAGENT_REQUIRE_ORIGIN_SMOKE", "1")
    def verify(root, *args, **kwargs):
        if args[0] == "just":
            env = kwargs["env"]
            assert not any(name.startswith("POLYAGENT_GIT_ORIGIN_") for name in env)
            assert "POLYAGENT_REQUIRE_ORIGIN_SMOKE" not in env
            assert env["POLYAGENT_REQUIRE_NATIVE_CODEX"] == "1"
            assert env["POLYAGENT_PREBUILT_MARKETPLACE"] == str(built[0])
    monkeypatch.setattr(workflow, "run", verify)
    assert workflow.workflow(tmp_path, built[0])["complete"]


def test_origin_smoke_pins_github_host_and_passes_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_HOST", "wrong.example.invalid")
    monkeypatch.setattr(workflow.shutil, "which", lambda *args: "/fake/gh")
    commands = []
    def command(root, *args, **kwargs):
        commands.append((args, kwargs.get("env")))
        return "test-token" if args[:3] == ("gh", "auth", "token") else ""
    monkeypatch.setattr(workflow, "run", command)
    workflow.origin_smoke(tmp_path, {"GH_HOST": "wrong.example.invalid",
                                     "POLYAGENT_GIT_ORIGIN_SOURCE_TAG": TAG})
    assert (("gh", "auth", "token", "--hostname", "github.com"), None) in commands
    smoke = next(env for args, env in commands if args[:3] == ("uv", "run", "pytest"))
    assert smoke["GH_TOKEN"] == "test-token" and smoke["POLYAGENT_GIT_ORIGIN_SOURCE_TAG"] == TAG
    assert "GIT_CONFIG_GLOBAL" in smoke and smoke["GH_HOST"] == "wrong.example.invalid"
