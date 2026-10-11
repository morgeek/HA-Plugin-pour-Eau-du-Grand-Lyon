"""Fail when the manifest version, the changelog and the release tag disagree.

Usage:
    python scripts/check_release.py            # manifest vs CHANGELOG.md
    python scripts/check_release.py v3.6.1     # also checks the git tag
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "eau_grand_lyon" / "manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_HEADING = re.compile(r"^## \[(\d+(?:\.\d+)+)\]", re.MULTILINE)
UNRELEASED_HEADING = re.compile(r"^## \[Non publié\]\s*$(.*?)(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)


def check(manifest_text: str, changelog_text: str, tag: str | None = None) -> list[str]:
    """Return the list of inconsistencies (empty when everything matches)."""
    errors: list[str] = []
    manifest_version = str(json.loads(manifest_text).get("version", ""))
    headings = VERSION_HEADING.findall(changelog_text)
    changelog_version = headings[0] if headings else ""

    if manifest_version != changelog_version:
        errors.append(
            f"manifest.json indique {manifest_version!r} "
            f"mais la dernière section du CHANGELOG est {changelog_version!r}"
        )

    if tag is not None:
        if tag != f"v{manifest_version}":
            errors.append(f"le tag {tag!r} ne correspond pas à manifest.json (attendu 'v{manifest_version}')")
        unreleased = UNRELEASED_HEADING.search(changelog_text)
        if unreleased and unreleased.group(1).strip():
            errors.append("le CHANGELOG contient encore des changements sous « Non publié » (absents de la release)")

    return errors


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else None
    errors = check(MANIFEST.read_text(encoding="utf-8"), CHANGELOG.read_text(encoding="utf-8"), tag)
    for error in errors:
        print(f"ERREUR: {error}", file=sys.stderr)
    if not errors:
        print("Versions cohérentes (manifest, CHANGELOG" + (", tag)" if tag else ")"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
