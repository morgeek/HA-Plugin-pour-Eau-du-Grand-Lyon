"""Tests for scripts/check_release.py (manifest / changelog / tag consistency)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_release", Path(__file__).resolve().parent.parent / "scripts" / "check_release.py"
)
assert _SPEC and _SPEC.loader
check_release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_release)

CHANGELOG = "# Changelog\n\n## [Non publié]\n\n## [3.6.1] - 2026-10-11\n\n- x\n\n## [3.5.5] - 2026-09-11\n"


def _manifest(version: str) -> str:
    return json.dumps({"version": version})


def test_consistent_versions_pass() -> None:
    assert check_release.check(_manifest("3.6.1"), CHANGELOG) == []
    assert check_release.check(_manifest("3.6.1"), CHANGELOG, "v3.6.1") == []


def test_manifest_behind_changelog_fails() -> None:
    errors = check_release.check(_manifest("3.5.5"), CHANGELOG)
    assert len(errors) == 1 and "3.5.5" in errors[0]


def test_tag_mismatch_fails() -> None:
    errors = check_release.check(_manifest("3.6.1"), CHANGELOG, "v3.6")
    assert len(errors) == 1 and "v3.6" in errors[0]


def test_unreleased_changes_block_a_release() -> None:
    changelog = CHANGELOG.replace("## [Non publié]\n", "## [Non publié]\n\n- oublié\n")
    assert check_release.check(_manifest("3.6.1"), changelog) == []
    assert any("Non publié" in e for e in check_release.check(_manifest("3.6.1"), changelog, "v3.6.1"))


def test_missing_changelog_version_fails() -> None:
    assert check_release.check(_manifest("1.0.0"), "# Changelog\n")


def test_repository_is_consistent() -> None:
    assert check_release.main.__module__  # script is importable
    root = Path(__file__).resolve().parent.parent
    manifest = (root / "custom_components/eau_grand_lyon/manifest.json").read_text(encoding="utf-8")
    assert check_release.check(manifest, (root / "CHANGELOG.md").read_text(encoding="utf-8")) == []
