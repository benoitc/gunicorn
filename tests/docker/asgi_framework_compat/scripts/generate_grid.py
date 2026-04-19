#!/usr/bin/env python3
"""
Compatibility Grid Generator

Generates a compatibility matrix showing test results for each
ASGI framework tested with gunicorn's native ASGI worker.
"""

import json
import os
from datetime import datetime
from pathlib import Path


# Framework configuration
FRAMEWORKS = ["django", "fastapi", "starlette", "quart", "litestar", "blacksheep"]

FRAMEWORK_NAMES = {
    "django": "Django + Channels",
    "fastapi": "FastAPI",
    "starlette": "Starlette",
    "quart": "Quart",
    "litestar": "Litestar",
    "blacksheep": "BlackSheep",
}

# Test categories based on file names
CATEGORIES = {
    "http_scope": "HTTP Scope",
    "http_messages": "HTTP Messages",
    "websocket": "WebSocket",
    "lifespan": "Lifespan",
    "streaming": "Streaming",
}


def parse_results(results_file: Path) -> dict:
    """Parse pytest JSON results into framework/category structure."""
    with open(results_file) as f:
        data = json.load(f)

    results = {fw: {cat: {"passed": 0, "failed": 0, "total": 0}
                    for cat in CATEGORIES} for fw in FRAMEWORKS}

    tests = data.get("tests", [])
    for test in tests:
        nodeid = test.get("nodeid", "")
        outcome = test.get("outcome", "")

        # Extract framework from test parameters
        framework = None
        for fw in FRAMEWORKS:
            if f"[{fw}]" in nodeid or f"[{fw}-" in nodeid:
                framework = fw
                break

        if not framework:
            continue

        # Determine category from file name
        category = None
        for cat_key in CATEGORIES:
            if f"test_{cat_key}" in nodeid:
                category = cat_key
                break

        if not category:
            continue

        results[framework][category]["total"] += 1
        if outcome == "passed":
            results[framework][category]["passed"] += 1
        elif outcome == "failed":
            results[framework][category]["failed"] += 1

    return results


def generate_markdown(results: dict) -> str:
    """Generate markdown compatibility grid."""
    lines = []
    lines.append("# ASGI Framework Compatibility Grid")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("**Worker:** gunicorn ASGI worker (`-k asgi`)")
    lines.append("**Event Loop:** auto (uvloop if available)")
    lines.append("")

    # Main compatibility table
    lines.append("## Summary")
    lines.append("")

    header = "| Framework |"
    separator = "|-----------|"
    for cat in CATEGORIES.values():
        header += f" {cat} |"
        separator += "---------|"
    header += " Total |"
    separator += "-------|"

    lines.append(header)
    lines.append(separator)

    for fw in FRAMEWORKS:
        fw_results = results.get(fw, {})
        row = f"| {FRAMEWORK_NAMES[fw]} |"

        total_passed = 0
        total_tests = 0

        for cat_key in CATEGORIES:
            cat_data = fw_results.get(cat_key, {"passed": 0, "total": 0})
            passed = cat_data["passed"]
            total = cat_data["total"]
            total_passed += passed
            total_tests += total

            if total == 0:
                row += " - |"
            elif passed == total:
                row += f" {passed}/{total} |"
            else:
                row += f" **{passed}/{total}** |"

        if total_tests == 0:
            row += " - |"
        elif total_passed == total_tests:
            row += f" {total_passed}/{total_tests} |"
        else:
            row += f" **{total_passed}/{total_tests}** |"

        lines.append(row)

    lines.append("")
    lines.append("*Bold indicates failures*")
    lines.append("")

    # Calculate overall pass rate
    all_passed = sum(
        results[fw][cat]["passed"]
        for fw in FRAMEWORKS
        for cat in CATEGORIES
    )
    all_total = sum(
        results[fw][cat]["total"]
        for fw in FRAMEWORKS
        for cat in CATEGORIES
    )

    lines.append(f"**Overall:** {all_passed}/{all_total} tests passed ({100*all_passed//all_total}%)")
    lines.append("")

    return "\n".join(lines)


def main():
    base_dir = Path(__file__).parent.parent
    results_dir = base_dir / "results"
    results_file = results_dir / "pytest_results.json"

    if not results_file.exists():
        print(f"Results file not found: {results_file}")
        return

    results = parse_results(results_file)
    md_content = generate_markdown(results)

    # Write to results directory
    md_file = results_dir / "compatibility_grid.md"
    with open(md_file, "w") as f:
        f.write(md_content)
    print(f"Written: {md_file}")

    # Also write JSON summary
    json_file = results_dir / "compatibility_grid.json"
    summary = {
        "generated": datetime.now().isoformat(),
        "worker": "gunicorn.workers.gasgi.ASGIWorker",
        "frameworks": {
            fw: {
                "name": FRAMEWORK_NAMES[fw],
                "categories": results[fw],
                "total_passed": sum(results[fw][c]["passed"] for c in CATEGORIES),
                "total_tests": sum(results[fw][c]["total"] for c in CATEGORIES),
            }
            for fw in FRAMEWORKS
        }
    }
    with open(json_file, "w") as f:
        json.dump(summary, indent=2, fp=f)
    print(f"Written: {json_file}")

    # Print the markdown
    print("\n" + md_content)


if __name__ == "__main__":
    main()
