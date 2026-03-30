#!/usr/bin/env python3
"""
Claude Code hook to enforce exact package versions in package.json.
No ^ or ~ symbols allowed - always use exact versions like "19.0.1"
"""

import json
import re
import sys
from pathlib import Path


def is_package_json(file_path: str) -> bool:
    """check if file is a package.json"""
    return Path(file_path).name == 'package.json'


def find_semver_ranges(content: str) -> list[tuple[int, str, str]]:
    """find version strings with ^ or ~ prefixes"""
    issues = []
    lines = content.split('\n')

    # pattern to match package versions with ^ or ~
    # matches: "package-name": "^1.2.3" or "package-name": "~1.2.3"
    version_pattern = re.compile(
        r'"([^"]+)"\s*:\s*"([~^])(\d+\.\d+\.\d+[^"]*)"'
    )

    for line_num, line in enumerate(lines, 1):
        matches = version_pattern.finditer(line)
        for match in matches:
            package_name = match.group(1)
            prefix = match.group(2)
            version = match.group(3)
            issues.append((line_num, package_name, f"{prefix}{version}"))

    return issues


def find_version_ranges(content: str) -> list[tuple[int, str, str]]:
    """find version strings with range operators"""
    issues = []
    lines = content.split('\n')

    # pattern to match various range formats
    range_patterns = [
        # >=, <=, >, < operators
        (re.compile(r'"([^"]+)"\s*:\s*"([><=]+\s*\d+[^"]*)"'), 'range operator'),
        # x or * wildcards
        (re.compile(r'"([^"]+)"\s*:\s*"(\d+\.(?:x|\*)(?:\.\*)?)"'), 'wildcard'),
        (re.compile(r'"([^"]+)"\s*:\s*"(\d+\.\d+\.(?:x|\*))"'), 'wildcard'),
        # hyphen ranges like 1.0.0 - 2.0.0
        (re.compile(r'"([^"]+)"\s*:\s*"(\d+\.\d+\.\d+\s*-\s*\d+[^"]*)"'), 'hyphen range'),
        # || operator
        (re.compile(r'"([^"]+)"\s*:\s*"([^"]*\|\|[^"]*)"'), 'or operator'),
    ]

    for line_num, line in enumerate(lines, 1):
        for pattern, range_type in range_patterns:
            matches = pattern.finditer(line)
            for match in matches:
                package_name = match.group(1)
                version = match.group(2)
                # skip if it's a url or file path
                if not any(x in version for x in ['://', 'file:', 'git+']):
                    issues.append((line_num, package_name, version))

    return issues


def validate_package_json(file_path: str, content: str) -> list[str]:
    """validate package.json for exact versions"""
    if not is_package_json(file_path):
        return []

    all_issues = []

    # check for ^ and ~ prefixes
    semver_issues = find_semver_ranges(content)
    for line_num, package, version in semver_issues:
        clean_version = version.lstrip('^~')
        all_issues.append(
            f"line {line_num}: '{package}' uses '{version}' - "
            f"use exact version '{clean_version}' instead (no ^ or ~ prefix)"
        )

    # check for other range operators
    range_issues = find_version_ranges(content)
    for line_num, package, version in range_issues:
        all_issues.append(
            f"line {line_num}: '{package}' uses range '{version}' - "
            f"use an exact version number instead"
        )

    return all_issues


def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = input_data.get('tool_input', {})
    file_path = tool_input.get('file_path', '')

    if not file_path:
        sys.exit(0)

    # get the content
    new_content = tool_input.get('new_string', '') or tool_input.get('content', '')

    if not new_content:
        sys.exit(0)

    issues = validate_package_json(file_path, new_content)

    if issues:
        print("package.json version issues:", file=sys.stderr)
        for issue in issues[:10]:
            print(f"  • {issue}", file=sys.stderr)
        if len(issues) > 10:
            print(f"  ... and {len(issues) - 10} more issues", file=sys.stderr)
        print("\nrequirement: always use exact versions without ^ or ~ prefixes", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == '__main__':
    main()
