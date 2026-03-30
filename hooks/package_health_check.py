#!/usr/bin/env python3
"""
Claude Code hook to check package health after reading package.json.
Runs npm outdated and npm audit to identify issues.
"""

import json
import subprocess
import sys
from pathlib import Path


def is_package_json(file_path: str) -> bool:
    """check if file is a package.json"""
    return Path(file_path).name == 'package.json'


def get_project_dir(file_path: str) -> str:
    """get the directory containing package.json"""
    return str(Path(file_path).parent)


def check_outdated(project_dir: str) -> list[str]:
    """run npm outdated and return issues"""
    issues = []
    try:
        result = subprocess.run(
            ['npm', 'outdated', '--json'],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.stdout:
            outdated = json.loads(result.stdout)
            for package, info in outdated.items():
                current = info.get('current', 'unknown')
                latest = info.get('latest', 'unknown')
                if current != latest:
                    issues.append(
                        f"  • {package}: {current} → {latest} available"
                    )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return issues


def check_audit(project_dir: str) -> list[str]:
    """run npm audit and return vulnerabilities"""
    issues = []
    try:
        result = subprocess.run(
            ['npm', 'audit', '--json'],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.stdout:
            audit = json.loads(result.stdout)
            vulnerabilities = audit.get('vulnerabilities', {})
            for package, info in vulnerabilities.items():
                severity = info.get('severity', 'unknown')
                via = info.get('via', [])
                if isinstance(via, list) and via:
                    if isinstance(via[0], dict):
                        title = via[0].get('title', 'vulnerability')
                    else:
                        title = str(via[0])
                else:
                    title = 'vulnerability'
                issues.append(
                    f"  • {package} [{severity}]: {title}"
                )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return issues


def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = input_data.get('tool_input', {})
    file_path = tool_input.get('file_path', '')

    if not file_path or not is_package_json(file_path):
        sys.exit(0)

    # check if node_modules exists (meaning deps are installed)
    project_dir = get_project_dir(file_path)
    node_modules = Path(project_dir) / 'node_modules'

    if not node_modules.exists():
        sys.exit(0)

    outdated = check_outdated(project_dir)
    vulnerabilities = check_audit(project_dir)

    output_parts = []

    if outdated:
        output_parts.append("outdated packages detected:")
        output_parts.extend(outdated)

    if vulnerabilities:
        if output_parts:
            output_parts.append("")
        output_parts.append("security vulnerabilities detected:")
        output_parts.extend(vulnerabilities)

    if output_parts:
        output_parts.append("")
        output_parts.append(
            "reminder: check with the user before upgrading packages - "
            "they may have reasons for specific versions"
        )
        print('\n'.join(output_parts))

    sys.exit(0)


if __name__ == '__main__':
    main()
