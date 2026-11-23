import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("general.default", "software.default")
TABLES = ("profile.tsv", "routes.tsv", "tasks.tsv")


def pytest_sessionstart(session):
    if os.environ.get("POLYAGENT_REQUIRE_NATIVE_CODEX") != "1":
        return
    configured = os.environ.get("POLYAGENT_STOCK_CODEX")
    executable = shutil.which(configured) if configured else None
    if not executable:
        raise pytest.UsageError("Codex is required for native release checks (POLYAGENT_STOCK_CODEX)")
    result = subprocess.run([executable, "--version"], capture_output=True, text=True,
                            check=False)
    if result.returncode != 0:
        raise pytest.UsageError(f"Codex --version failed: {result.stderr.strip()}")
    print(f"native release host Codex: {result.stdout.strip()}")


@pytest.fixture(scope="session")
def packaged():
    prebuilt = os.environ.get("POLYAGENT_PREBUILT_MARKETPLACE")
    if prebuilt is not None:
        candidate = Path(prebuilt)
        if not candidate.is_absolute() or not candidate.is_dir():
            raise ValueError("POLYAGENT_PREBUILT_MARKETPLACE must be an existing absolute directory")
        return candidate
    subprocess.run(["python3", "scripts/package.py", "build"], cwd=ROOT, check=True)
    return ROOT / "dist/marketplace"


def assert_bundled_resources(plugin: Path) -> None:
    """Require the complete bundled profile and host metadata layout in an installed copy."""
    hosts = {".codex-plugin", ".claude-plugin"}
    assert {path.name for path in plugin.iterdir() if path.name.startswith(".")} == hosts
    for host in hosts:
        assert {path.name for path in (plugin / host).iterdir()} == {"plugin.json"}
    profiles = plugin / "skills/polyagent/profiles"
    expected_files = {Path(profile) / table for profile in PROFILES for table in TABLES}
    assert {p.relative_to(profiles) for p in profiles.rglob("*") if p.is_file()} == expected_files
    assert {p.relative_to(profiles) for p in profiles.rglob("*") if p.is_dir()} == {
        Path(profile) for profile in PROFILES
    }


def bundled_profile_files(plugin: Path) -> dict[str, bytes]:
    profiles = plugin / "skills/polyagent/profiles"
    return {str(path.relative_to(profiles)): path.read_bytes() for path in profiles.rglob("*.tsv")}
