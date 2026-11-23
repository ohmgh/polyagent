"""The built marketplace is the checked-in plugin plus its license and catalogs."""

import importlib.util
import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from conftest import PROFILES, TABLES, assert_bundled_resources

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package", ROOT / "scripts/package.py")
assert SPEC is not None and SPEC.loader is not None
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


def files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_source_and_package_contain_only_polyagent(packaged):
    assert sorted(path.name for path in (ROOT / "plugins").iterdir()) == ["polyagent"]
    assert sorted(path.name for path in (packaged / "plugins").iterdir()) == ["polyagent"]
    assert {path.name for path in packaged.iterdir()} == {".agents", ".claude-plugin", "plugins"}
    plugin = packaged / "plugins/polyagent"
    assert_bundled_resources(plugin)
    assert {path.relative_to(plugin).as_posix() for path in plugin.rglob("*") if path.is_file()} == {
        ".codex-plugin/plugin.json", ".claude-plugin/plugin.json",
        ".antigravity-plugin/plugin.json", "LICENSE",
        "skills/polyagent/SKILL.md", "skills/polyagent/agents/openai.yaml",
        "skills/polyagent/references/delegation.md",
        *(f"skills/polyagent/profiles/{profile}/{table}" for profile in PROFILES for table in TABLES),
    }
    assert not json.loads((plugin / ".codex-plugin/plugin.json").read_text()).get("hooks")


def test_package_is_a_verbatim_copy_with_plain_modes(packaged):
    plugin = packaged / "plugins/polyagent"
    source = files(ROOT / "plugins/polyagent") | {"LICENSE": (ROOT / "LICENSE").read_bytes()}
    assert files(plugin) == source
    for path in packaged.rglob("*"):
        expected = 0o755 if path.is_dir() else 0o644
        assert stat.S_IMODE(path.stat().st_mode) == expected, path


def test_codex_manifest_and_catalog(packaged):
    version = package.manifest_version(ROOT)
    manifest = json.loads((packaged / "plugins/polyagent/.codex-plugin/plugin.json").read_text())
    assert manifest["version"] == version
    assert manifest["name"] == "polyagent"
    assert manifest["skills"] == "./skills/"
    catalog = json.loads((packaged / ".agents/plugins/marketplace.json").read_text())
    assert catalog["plugins"][0]["source"] == {"source": "local", "path": "./plugins/polyagent"}
    plugin = packaged / "plugins/polyagent"
    assert {path.name for path in plugin.iterdir() if path.name.startswith(".")} == {
        ".codex-plugin", ".claude-plugin", ".antigravity-plugin"}


def test_claude_manifest_and_catalog(packaged):
    version = package.manifest_version(ROOT)
    manifest = json.loads((packaged / "plugins/polyagent/.claude-plugin/plugin.json").read_text())
    assert manifest["version"] == version
    assert manifest["name"] == "polyagent"
    catalog = json.loads((packaged / ".claude-plugin/marketplace.json").read_text())
    assert catalog["name"] == "polyagent"
    assert catalog["plugins"] == [{"name": "polyagent", "source": "./plugins/polyagent",
                                   "description": manifest["description"]}]


def test_antigravity_manifest(packaged):
    version = package.manifest_version(ROOT)
    manifest = json.loads(
        (packaged / "plugins/polyagent/.antigravity-plugin/plugin.json").read_text()
    )
    allowed = {"name", "displayName", "version", "description", "author",
               "homepage", "repository", "logo", "suggestedPrompts", "disabled"}
    assert set(manifest) <= allowed
    assert manifest["version"] == version
    assert manifest["name"] == "polyagent"
    assert manifest["displayName"] == "Polyagent"
    assert manifest["description"] == package.DESCRIPTION
    assert manifest["author"] == {"name": "ohm"}
    assert manifest["homepage"] == "https://github.com/ohmgh/polyagent"
    assert manifest["repository"] == "https://github.com/ohmgh/polyagent"
    prompts = manifest["suggestedPrompts"]
    assert isinstance(prompts, list) and 1 <= len(prompts) <= 3
    assert all(isinstance(item, str) and item.strip() for item in prompts)


def test_build_requires_agreeing_manifest_versions(tmp_path):
    root = tmp_path / "source"
    shutil.copytree(ROOT / "plugins", root / "plugins")
    shutil.copy(ROOT / "LICENSE", root / "LICENSE")
    shutil.copy(ROOT / "scripts/package.py", root / "package.py")
    manifest = root / "plugins/polyagent/.claude-plugin/plugin.json"
    data = json.loads(manifest.read_text())
    data["version"] = "0.0.1"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="disagree"):
        package.build(root)
    assert not (root / "dist").exists()
    result = subprocess.run(["python3", str(ROOT / "scripts/package.py"), "package"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2 and "invalid choice" in result.stderr


def test_skill_names_no_runtime():
    skill = ROOT / "plugins/polyagent/skills/polyagent"
    text = (skill / "SKILL.md").read_text() + (skill / "references/delegation.md").read_text()
    for word in ("snapshot", "prepare --", "schema_version", "arm64", "bin/polyagent", "JSON"):
        assert word not in text, word
    assert len((skill / "SKILL.md").read_text().splitlines()) <= 80
