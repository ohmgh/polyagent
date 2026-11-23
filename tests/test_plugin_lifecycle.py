"""Install the routing plugin in disposable Codex, Antigravity, and user state."""

import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from conftest import assert_bundled_resources


def next_patch(version):
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def plugin_files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def rpc(codex, env, cwd, methods):
    process = subprocess.Popen(
        [codex, "app-server"], env=env, cwd=cwd, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    messages = queue.Queue()
    assert process.stdin and process.stdout
    stdout = process.stdout
    threading.Thread(target=lambda: [messages.put(json.loads(line)) for line in stdout],
                     daemon=True).start()
    results = []
    try:
        calls = [("initialize", {"clientInfo": {"name": "polyagent-test", "version": "0.1.0"},
                                 "capabilities": {"experimentalApi": True}}), *methods]
        for index, (method, params) in enumerate(calls):
            process.stdin.write(json.dumps({"id": index, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            while True:
                message = messages.get(timeout=20)
                if message.get("id") == index:
                    assert "error" not in message, message
                    results.append(message["result"])
                    break
    finally:
        process.terminate()
        process.wait(timeout=5)
    return results[1:]


def test_install_update_disable_remove_and_reinstall(packaged, tmp_path):
    codex = os.environ.get("POLYAGENT_STOCK_CODEX") or shutil.which("codex") or "codex"
    host_version = subprocess.check_output([codex, "--version"], text=True).strip()
    assert host_version.startswith("codex-cli "), host_version
    print(f"native Codex host: {host_version}")
    marketplace = tmp_path / "marketplace"
    shutil.copytree(packaged, marketplace)
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "CODEX_HOME": str(codex_home),
           "XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_DATA_HOME": str(tmp_path / "data")}

    def command(*args):
        result = subprocess.run([codex, "plugin", *args], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=30, check=False)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def install():
        command("marketplace", "add", str(marketplace))
        installed = json.loads(command("add", "polyagent@polyagent", "--json"))
        assert installed["pluginId"] == "polyagent@polyagent"
        plugin = Path(installed["installedPath"])
        assert_bundled_resources(plugin)
        assert plugin_files(plugin) == plugin_files(marketplace / "plugins/polyagent")
        return installed

    def discovered():
        skills, hooks = rpc(codex, env, tmp_path, [
            ("skills/list", {"cwds": [str(tmp_path)], "forceReload": True}),
            ("hooks/list", {"cwds": [str(tmp_path)]}),
        ])
        assert not hooks["data"][0]["hooks"]
        return {skill["name"] for skill in skills["data"][0]["skills"]
                if skill.get("pluginId") and skill["enabled"]}

    # User and repository configuration is the user's; installation never reads or writes it.
    for relative, content in {
        ".polyagent/config.tsv": "key\tvalue\ndefault_profile\tmy.custom\n",
        ".polyagent/profiles/my.custom/notes.txt": "Keep my custom profile.\n",
        ".polyagent/profiles/software.default/profile.tsv": "an old copied profile\n",
        "project/.polyagent/config.tsv": "key\tvalue\ndefault_profile\toff\n",
    }.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def configuration():
        return {str(p.relative_to(tmp_path)): p.read_bytes()
                for root in (tmp_path / ".polyagent", tmp_path / "project/.polyagent")
                for p in root.rglob("*") if p.is_file()}

    before = configuration()
    installed = install()
    assert discovered() == {"polyagent:polyagent"}
    assert sorted(path.name for path in Path(installed["installedPath"]).parent.parent.iterdir()) == [
        "polyagent"]
    assert configuration() == before

    source = marketplace / "plugins/polyagent"
    updated_version = next_patch(json.loads((source / ".codex-plugin/plugin.json").read_text())["version"])
    for host in ("codex", "claude", "antigravity"):
        manifest_path = source / f".{host}-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = updated_version
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    (source / "skills/polyagent/profiles/general.default/profile.tsv").write_text(
        "key\tvalue\ndirective\tBundled update B.\ncallouts\t-\nreuse_agents\ton\n")
    skill = source / "skills/polyagent/SKILL.md"
    skill.write_text(skill.read_text() + "\nUpdate B.\n")
    updated = install()
    assert updated["version"] == updated_version
    assert "Update B." in (Path(updated["installedPath"]) / "skills/polyagent/SKILL.md").read_text()
    assert configuration() == before
    config = codex_home / "config.toml"
    config.write_text(config.read_text().replace("enabled = true", "enabled = false"))
    assert not discovered()
    config.write_text(config.read_text().replace("enabled = false", "enabled = true"))
    assert discovered() == {"polyagent:polyagent"}
    command("remove", "polyagent@polyagent")
    assert not json.loads(command("list", "--json"))["installed"]
    install()
    assert configuration() == before
    assert discovered() == {"polyagent:polyagent"}


def test_antigravity_validate_install_update_disable_remove_and_reinstall(packaged, tmp_path):
    agy = os.environ.get("POLYAGENT_STOCK_AGY") or shutil.which("agy")
    if not agy:
        if os.environ.get("POLYAGENT_REQUIRE_NATIVE_AGY") == "1":
            pytest.fail("Antigravity CLI (agy) is required")
        pytest.skip("Antigravity CLI (agy) is not installed")
    host_version = subprocess.check_output([agy, "--version"], text=True).strip()
    assert host_version, host_version
    print(f"native Antigravity host: {host_version}")
    marketplace = tmp_path / "marketplace"
    shutil.copytree(packaged, marketplace)
    source = marketplace / "plugins/polyagent"
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path),
           "XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_DATA_HOME": str(tmp_path / "data")}

    def command(*args):
        result = subprocess.run([agy, "plugin", *args], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=30, check=False)
        assert result.returncode == 0, f"{args}: {result.stdout}\n{result.stderr}"
        return result.stdout

    def validate():
        report = json.loads(command("validate", "--strict", "--json", str(source)))
        assert report["manifest"] == ".antigravity-plugin/plugin.json"
        assert report["name"] == "polyagent"
        assert report["components"] == {
            "agents": 0, "hooks": 0, "mcpServers": 0, "rules": 0, "sidecars": 0, "skills": 1,
        }
        assert all(item["severity"] not in ("error", "warning") for item in report["findings"])

    def listed():
        return json.loads(command("list", "--json"))

    def install(expected_version):
        command("install", str(source))
        entries = listed()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["name"] == "polyagent"
        assert entry["enabled"] is True
        assert entry["source"] == "antigravity"
        assert entry["version"] == expected_version
        assert entry["skills"] == ["polyagent"]
        plugin = Path(entry["path"])
        assert plugin.is_relative_to(tmp_path / ".gemini/config/plugins")
        assert_bundled_resources(plugin)
        assert plugin_files(plugin) == plugin_files(source)
        return plugin

    for relative, content in {
        ".polyagent/config.tsv": "key\tvalue\ndefault_profile\tmy.custom\n",
        ".polyagent/profiles/my.custom/notes.txt": "Keep my custom profile.\n",
        ".polyagent/profiles/software.default/profile.tsv": "an old copied profile\n",
        "project/.polyagent/config.tsv": "key\tvalue\ndefault_profile\toff\n",
    }.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def configuration():
        return {str(p.relative_to(tmp_path)): p.read_bytes()
                for root in (tmp_path / ".polyagent", tmp_path / "project/.polyagent")
                for p in root.rglob("*") if p.is_file()}

    initial_version = json.loads(
        (source / ".antigravity-plugin/plugin.json").read_text()
    )["version"]
    before = configuration()
    validate()
    install(initial_version)
    assert configuration() == before

    updated_version = next_patch(initial_version)
    for host in ("codex", "claude", "antigravity"):
        manifest_path = source / f".{host}-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = updated_version
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    (source / "skills/polyagent/profiles/general.default/profile.tsv").write_text(
        "key\tvalue\ndirective\tBundled update B.\ncallouts\t-\nreuse_agents\ton\n")
    skill = source / "skills/polyagent/SKILL.md"
    skill.write_text(skill.read_text() + "\nUpdate B.\n")

    validate()
    updated = install(updated_version)
    assert "Update B." in (updated / "skills/polyagent/SKILL.md").read_text()
    assert configuration() == before

    command("disable", "polyagent")
    assert listed()[0]["enabled"] is False
    command("enable", "polyagent")
    assert listed()[0]["enabled"] is True

    command("uninstall", "polyagent")
    assert listed() == []
    assert configuration() == before

    install(updated_version)
    assert configuration() == before
