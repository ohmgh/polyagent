"""Native Git marketplace checks with disposable Codex and Polyagent state."""

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import assert_bundled_resources
from test_plugin_lifecycle import plugin_files, rpc


def run(args, *, cwd, env=None, timeout=45):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True,
                            timeout=timeout, check=False)
    assert result.returncode == 0, f"{args}: {result.stdout}\n{result.stderr}"
    return result.stdout


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    return {str(p.relative_to(root)): (digest(p), p.stat().st_mode & 0o777)
            for p in root.rglob("*") if p.is_file()}


def next_patch(version):
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def codex_env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    env = {
        "PATH": os.environ["PATH"], "HOME": str(home), "CODEX_HOME": str(codex_home),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
    }
    for key, value in os.environ.items():
        if key in {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_COUNT", "GH_TOKEN"} or key.startswith(
            ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
        ):
            env[key] = value
    return env


def native_codex():
    codex = os.environ.get("POLYAGENT_STOCK_CODEX") or shutil.which("codex")
    assert codex, "Codex CLI is required"
    print(f"native Git lifecycle Codex: {run([codex, '--version'], cwd=Path.cwd()).strip()}")
    return codex


def git(*args, cwd, env=None):
    return run(["git", *args], cwd=cwd, env=env).strip()


@contextlib.contextmanager
def git_marketplace(tmp_path, packaged):
    """Serve a real Git remote; main deliberately contains no plugin catalog."""
    source = tmp_path / "source"
    source.mkdir()
    git("init", "-b", "main", cwd=source)
    git("config", "user.name", "Polyagent fixture", cwd=source)
    git("config", "user.email", "fixture@example.invalid", cwd=source)
    (source / "README").write_text("The default branch has no marketplace.\n")
    git("add", "README", cwd=source)
    git("commit", "-m", "default branch", cwd=source)
    assert git("ls-tree", "-r", "--name-only", "HEAD", cwd=source) == "README"
    git("switch", "--orphan", "marketplace", cwd=source)
    shutil.copytree(packaged, source, dirs_exist_ok=True)
    git("add", "--force", "--all", cwd=source)
    git("commit", "-m", "snapshot A", cwd=source)
    assert set(git("ls-tree", "-r", "--name-only", "HEAD", cwd=source).splitlines()) == set(inventory(packaged))
    remote = tmp_path / "remote.git"
    run(["git", "clone", "--bare", str(source), str(remote)], cwd=tmp_path)
    git("remote", "add", "fixture", str(remote), cwd=source)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
    assert "marketplace.json" not in git("ls-tree", "-r", "--name-only", "main", cwd=remote)
    transport = tmp_path / "git-ssh-transport"
    transport.write_text(
        "#!/usr/bin/env python3\n"
        "import os, shlex, sys\n"
        "command = shlex.split(sys.argv[-1])\n"
        "if len(command) != 2 or command[0] != 'git-upload-pack' "
        "or command[1] != '/remote.git':\n"
        "    sys.exit(2)\n"
        f"os.execvp('git', ['git', 'upload-pack', {str(remote)!r}])\n"
    )
    transport.chmod(0o755)
    url = "ssh://fixture@127.0.0.1/remote.git"
    transport_env = {**os.environ, "GIT_SSH": str(transport), "GIT_CONFIG_GLOBAL": os.devnull}
    assert git("ls-remote", url, "refs/heads/marketplace", cwd=tmp_path, env=transport_env)
    yield source, remote, url, transport_env


def plugin_state(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for base in (root / "home/.polyagent", root / "project/.polyagent")
            for p in base.rglob("*") if p.is_file()}


def seed_configuration(root):
    contents = {
        "home/.polyagent/config.tsv": b"key\tvalue\ndefault_profile\tmy.custom\n",
        "home/.polyagent/profiles/software.default/profile.tsv": b"an old copied profile\n",
        "home/.polyagent/profiles/my.custom/tasks.tsv": b"my own profile\n",
        "project/.polyagent/config.tsv": b"key\tvalue\ndefault_profile\toff\n",
        "project/.polyagent/profiles/software.default/routes.tsv": b"repo partial override\n",
    }
    for relative, content in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return plugin_state(root)


def installed_plugin(plugin, expected):
    """An installed copy is exactly the published plugin tree: tables and text, nothing to run."""
    assert_bundled_resources(plugin)
    assert not (plugin / "bin").exists() and not (plugin / "skills/polyagent/polyagent").exists()
    assert plugin_files(plugin) == expected
    skill = (plugin / "skills/polyagent/SKILL.md").read_text()
    assert "## 1. Profile" in skill and "snapshot" not in skill


def codex_install(codex, env, cwd):
    result = json.loads(run([codex, "plugin", "add", "polyagent@polyagent", "--json"],
                            cwd=cwd, env=env))
    assert result["pluginId"] == "polyagent@polyagent"
    return Path(result["installedPath"])


def discovered(codex, env, work):
    skills = rpc(codex, env, work, [("skills/list", {"cwds": [str(work)], "forceReload": True})])[0]
    return [s["name"] for s in skills["data"][0]["skills"] if s.get("pluginId") and s["enabled"]]


def test_git_marketplace_install_update_and_lifecycle(packaged, tmp_path):
    codex = native_codex()
    original = inventory(packaged)
    version_a = json.loads((packaged / "plugins/polyagent/.codex-plugin/plugin.json").read_text())["version"]
    version_b = next_patch(version_a)
    with git_marketplace(tmp_path, packaged) as (source, remote, url, transport_env):
        env = {**codex_env(tmp_path), "GIT_SSH": transport_env["GIT_SSH"],
               "GIT_CONFIG_GLOBAL": transport_env["GIT_CONFIG_GLOBAL"]}
        work = tmp_path / "project"
        work.mkdir()
        git("init", "-b", "main", cwd=work)
        assert "marketplace.json" not in git("ls-tree", "-r", "--name-only", "main", cwd=remote)
        codex_add = json.loads(run([codex, "plugin", "marketplace", "add", url,
                                    "--ref", "marketplace", "--json"], cwd=work, env=env))
        assert "polyagent" in json.dumps(codex_add), codex_add
        codex_plugin = codex_install(codex, env, work)
        installed_plugin(codex_plugin, plugin_files(packaged / "plugins/polyagent"))
        assert not (Path(env["HOME"]) / ".polyagent").exists()
        assert discovered(codex, env, work) == ["polyagent:polyagent"]
        before = seed_configuration(tmp_path)

        # Snapshot B changes only text, as a release does, and carries its source trailers.
        plugin = source / "plugins/polyagent"
        for host in ("codex", "claude", "antigravity"):
            manifest = plugin / f".{host}-plugin/plugin.json"
            data = json.loads(manifest.read_text())
            data["version"] = version_b
            manifest.write_text(json.dumps(data, indent=2) + "\n")
        skill = plugin / "skills/polyagent/SKILL.md"
        skill.write_text(skill.read_text() + "\nSnapshot B.\n")
        profile = plugin / "skills/polyagent/profiles/general.default/profile.tsv"
        profile.write_text("key\tvalue\ndirective\tBundled update B.\ncallouts\t-\nreuse_agents\ton\n")
        source_tag = f"release/v{version_b}"
        source_commit = git("rev-parse", "main", cwd=source)
        git("tag", source_tag, source_commit, cwd=source)
        git("add", "--force", "--all", cwd=source)
        git("commit", "-m", f"Publish marketplace {version_b} from {source_tag}\n\n"
            f"Source-Tag: {source_tag}\nSource-Commit: {source_commit}\n", cwd=source)
        git("push", "fixture", "marketplace:marketplace", f"refs/tags/{source_tag}", cwd=source)
        expected_b = plugin_files(plugin)
        assert expected_b != plugin_files(packaged / "plugins/polyagent")
        run([codex, "plugin", "marketplace", "upgrade", "polyagent"], cwd=work, env=env)
        codex_plugin = codex_install(codex, env, work)
        installed_plugin(codex_plugin, expected_b)
        assert "Bundled update B." in (
            codex_plugin / "skills/polyagent/profiles/general.default/profile.tsv").read_text()
        assert plugin_state(tmp_path) == before
        assert discovered(codex, env, work) == ["polyagent:polyagent"]
        config = Path(env["CODEX_HOME"]) / "config.toml"
        config.write_text(config.read_text().replace("enabled = true", "enabled = false"))
        assert not discovered(codex, env, work)
        config.write_text(config.read_text().replace("enabled = false", "enabled = true"))
        assert discovered(codex, env, work) == ["polyagent:polyagent"]
        run([codex, "plugin", "remove", "polyagent@polyagent"], cwd=work, env=env)
        assert not json.loads(run([codex, "plugin", "list", "--json"], cwd=work, env=env))["installed"]
        assert plugin_state(tmp_path) == before
        codex_plugin = codex_install(codex, env, work)
        assert plugin_state(tmp_path) == before
        source.rename(tmp_path / "source-unavailable")
        remote.rename(tmp_path / "remote-unavailable.git")
        installed_plugin(codex_plugin, expected_b)
        assert inventory(packaged) == original


def test_actual_origin_smoke(tmp_path):
    if not os.environ.get("POLYAGENT_GIT_ORIGIN_URL"):
        if os.environ.get("POLYAGENT_REQUIRE_ORIGIN_SMOKE") == "1":
            pytest.fail("POLYAGENT_GIT_ORIGIN_URL is required for post-push smoke")
        pytest.skip("post-push origin smoke only")
    codex = native_codex()
    url = os.environ["POLYAGENT_GIT_ORIGIN_URL"]
    ref = os.environ["POLYAGENT_GIT_ORIGIN_REF"]
    commit = os.environ["POLYAGENT_GIT_ORIGIN_COMMIT"]
    source_commit = os.environ["POLYAGENT_GIT_ORIGIN_SOURCE_COMMIT"]
    source_tag = os.environ["POLYAGENT_GIT_ORIGIN_SOURCE_TAG"]
    assert len(commit) == len(source_commit) == 40
    assert source_tag.startswith("release/v")
    version = source_tag.removeprefix("release/v")
    assert git("ls-remote", url, f"refs/heads/{ref}", cwd=tmp_path).split()[0] == commit
    env = codex_env(tmp_path)
    work = tmp_path / "project"
    work.mkdir()
    run([codex, "plugin", "marketplace", "add", url, "--ref", ref], cwd=work, env=env)
    plugin = codex_install(codex, env, work)
    clone = tmp_path / "marketplace.git"
    run(["git", "clone", "--quiet", "--bare", "--branch", ref, "--depth", "1", url, str(clone)],
        cwd=tmp_path, timeout=120)
    assert git("rev-parse", "HEAD", cwd=clone) == commit
    message = git("log", "-1", "--format=%B", commit, cwd=clone)
    assert f"Source-Tag: {source_tag}" in message and f"Source-Commit: {source_commit}" in message
    published = {}
    for name in git("ls-tree", "-r", "--name-only", commit, "--", "plugins/polyagent", cwd=clone).splitlines():
        published[name.removeprefix("plugins/polyagent/")] = subprocess.run(
            ["git", "cat-file", "blob", f"{commit}:{name}"], cwd=clone, capture_output=True,
            check=True).stdout
    installed_plugin(plugin, published)
    manifest = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
    assert manifest["version"] == version
    assert not (Path(env["HOME"]) / ".polyagent").exists()
