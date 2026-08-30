"""Fail when a non-empty integration Python module is not strictly above 95%."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    coverage_path = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json")
    report = json.loads(coverage_path.read_text(encoding="utf-8"))
    integration_prefix = "custom_components/eau_grand_lyon/"
    failures = []

    for filename, details in sorted(report["files"].items()):
        if not filename.startswith(integration_prefix) or not filename.endswith(".py"):
            continue
        summary = details["summary"]
        statements = int(summary["num_statements"])
        if statements == 0:
            continue
        percent = float(summary["percent_covered"])
        print(f"{percent:6.2f}%  {filename}")
        if percent <= 95.0:
            failures.append((filename, percent))

    if failures:
        print("\nModules at or below the required 95%:", file=sys.stderr)
        for filename, percent in failures:
            print(f"- {filename}: {percent:.2f}%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
