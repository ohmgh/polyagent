"""Assemble the Codex and Claude Code plugin and its marketplace catalogs in dist/marketplace."""

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTION = "Profile-based automatic subagent delegation."
MANIFESTS = ("plugins/polyagent/.codex-plugin/plugin.json",
             "plugins/polyagent/.claude-plugin/plugin.json")


def manifest_version(root: Path = ROOT) -> str:
    """The plugin version, which both host manifests must state identically."""
    versions = {json.loads((root / name).read_text())["version"] for name in MANIFESTS}
    if len(versions) != 1:
        raise ValueError("The plugin manifests disagree on the version.")
    return str(versions.pop())


def build(root: Path = ROOT) -> Path:
    """Copy the plugin as checked in, add the license and write both catalogs."""
    manifest_version(root)
    marketplace = root / "dist/marketplace"
    if marketplace.exists():
        shutil.rmtree(marketplace)
    plugin = marketplace / "plugins/polyagent"
    shutil.copytree(root / "plugins/polyagent", plugin,
                    ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "._*"))
    shutil.copyfile(root / "LICENSE", plugin / "LICENSE")
    for path in plugin.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    catalogs = {
        ".agents/plugins/marketplace.json": {
            "name": "polyagent",
            "interface": {"displayName": "Polyagent"},
            "plugins": [{
                "name": "polyagent",
                "source": {"source": "local", "path": "./plugins/polyagent"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }],
        },
        ".claude-plugin/marketplace.json": {
            "name": "polyagent",
            "owner": {"name": "ohm"},
            "description": DESCRIPTION,
            "plugins": [{
                "name": "polyagent",
                "source": "./plugins/polyagent",
                "description": DESCRIPTION,
            }],
        },
    }
    for name, catalog in catalogs.items():
        path = marketplace / name
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(catalog, indent=2) + "\n")
    print(marketplace)
    return marketplace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build"])
    parser.parse_args()
    try:
        build()
    except (ValueError, OSError) as error:
        parser.exit(1, f"Build failed: {error}\n")


if __name__ == "__main__":
    main()
