#!/usr/bin/env python3
"""
Claude Code PostToolUse hook for Edit|Write|MultiEdit.
Validates package.json dependency versions: requires exact pinned versions,
flags banned semver shorthands (^, ~, >=, bare majors), and warns about
deprecated packages.
"""

import json
import os
import re
import sys
from pathlib import Path


ALLOWED_PROTOCOLS = (
    'file:', 'link:', 'workspace:', 'git+', 'git:', 'http://', 'https://',
    'npm:', 'patch:', 'portal:',
)

ALLOWED_KEYWORDS = {'*', 'latest', 'next'}


EXACT_SEMVER_RE = re.compile(
    r'^\d+\.\d+\.\d+(?:-[\w.+-]+)?(?:\+[\w.+-]+)?$'
)


BANNED_PREFIXES = ('^', '~', '>=', '<=', '>', '<')


DEPRECATED_PACKAGES = {
    'moment': 'dayjs or date-fns',
    'request': 'node-fetch, undici, or axios',
    'tslint': 'eslint with @typescript-eslint',
    'bower': 'npm or pnpm',
    'grunt': 'npm scripts, vite, or esbuild',
}


REACT_DEPRECATED = {
    'jquery': 'native React patterns or a React-friendly library',
}


DEP_SECTIONS = (
    'dependencies',
    'devDependencies',
    'peerDependencies',
    'optionalDependencies',
    'bundleDependencies',
)


def is_package_json(file_path: str) -> bool:
    return Path(file_path).name == 'package.json'


def classify_version(version: str) -> str | None:
    v = version.strip()
    if not v:
        return None
    if v in ALLOWED_KEYWORDS:
        return None
    for proto in ALLOWED_PROTOCOLS:
        if v.startswith(proto):
            return None
    if re.match(r'^[\w.-]+/[\w.-]+', v) and '/' in v and not v[0].isdigit():
        return None
    for prefix in BANNED_PREFIXES:
        if v.startswith(prefix):
            return f"banned range prefix '{prefix}' - pin an exact version"
    if re.match(r'^\d+$', v):
        return "bare major version - pin a full x.y.z"
    if re.match(r'^\d+\.\d+$', v):
        return "partial version - pin a full x.y.z"
    if 'x' in v or '*' in v:
        return "wildcard version - pin a full x.y.z"
    if ' - ' in v or '||' in v:
        return "version range - pin a single exact version"
    if EXACT_SEMVER_RE.match(v):
        return None
    return f"unrecognised version '{v}' - pin an exact x.y.z"


def parse_package_json(content: str) -> dict | None:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def scan_sections(pkg: dict) -> list[tuple[str, str, str, str]]:
    findings = []
    for section in DEP_SECTIONS:
        deps = pkg.get(section)
        if not isinstance(deps, dict):
            continue
        for name, version in deps.items():
            if not isinstance(version, str):
                continue
            problem = classify_version(version)
            if problem:
                findings.append((section, name, version, problem))
    return findings


def deprecated_findings(pkg: dict) -> list[str]:
    warnings = []
    all_deps = {}
    for section in DEP_SECTIONS:
        deps = pkg.get(section)
        if isinstance(deps, dict):
            all_deps.update({k: section for k in deps.keys()})
    for name, replacement in DEPRECATED_PACKAGES.items():
        if name in all_deps:
            warnings.append(f"{name} is deprecated - consider {replacement}")
    if 'react' in all_deps:
        for name, replacement in REACT_DEPRECATED.items():
            if name in all_deps:
                warnings.append(f"{name} in a React project - prefer {replacement}")
    return warnings


def collect_content(tool_input: dict) -> str:
    parts = []
    if tool_input.get('new_string'):
        parts.append(tool_input['new_string'])
    if tool_input.get('content'):
        parts.append(tool_input['content'])
    for edit in tool_input.get('edits', []) or []:
        if isinstance(edit, dict) and edit.get('new_string'):
            parts.append(edit['new_string'])
    return '\n'.join(parts)


def fragment_scan(fragment: str) -> list[tuple[str, str, str]]:
    findings = []
    line_pattern = re.compile(r'"([^"]+)"\s*:\s*"([^"]+)"')
    for match in line_pattern.finditer(fragment):
        name = match.group(1)
        version = match.group(2)
        if name in DEP_SECTIONS or name in ('name', 'version', 'main', 'module', 'types', 'description', 'license', 'author', 'homepage', 'repository', 'bugs', 'engines'):
            continue
        if name.startswith('@') and '/' not in name:
            continue
        problem = classify_version(version)
        if problem:
            findings.append((name, version, problem))
    return findings


def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(2)

    tool_input = input_data.get('tool_input', {})
    file_path = tool_input.get('file_path', '')
    if not file_path or not is_package_json(file_path):
        sys.exit(0)

    disk_content = ''
    if os.path.isfile(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                disk_content = f.read()
        except OSError:
            disk_content = ''

    version_issues: list[str] = []
    deprecations: list[str] = []

    if disk_content:
        pkg = parse_package_json(disk_content)
        if pkg is not None:
            for section, name, version, problem in scan_sections(pkg):
                version_issues.append(f"{section}.{name} = '{version}' - {problem}")
            deprecations = deprecated_findings(pkg)
        else:
            fragment = collect_content(tool_input) or disk_content
            for name, version, problem in fragment_scan(fragment):
                version_issues.append(f"{name} = '{version}' - {problem}")
    else:
        fragment = collect_content(tool_input)
        if not fragment:
            sys.exit(0)
        pkg = parse_package_json(fragment)
        if pkg is not None:
            for section, name, version, problem in scan_sections(pkg):
                version_issues.append(f"{section}.{name} = '{version}' - {problem}")
            deprecations = deprecated_findings(pkg)
        else:
            for name, version, problem in fragment_scan(fragment):
                version_issues.append(f"{name} = '{version}' - {problem}")

    force = os.environ.get('PACKAGE_GUARD_FORCE', '').lower() in ('1', 'true', 'yes')

    if version_issues:
        print("package.json version issues:", file=sys.stderr)
        for issue in version_issues[:20]:
            print(f"  - {issue}", file=sys.stderr)
        if len(version_issues) > 20:
            print(f"  ... and {len(version_issues) - 20} more", file=sys.stderr)
        if deprecations:
            print("", file=sys.stderr)
            print("deprecated packages:", file=sys.stderr)
            for d in deprecations:
                print(f"  - {d}", file=sys.stderr)
        print("", file=sys.stderr)
        print("requirement: pin exact versions (no ^, ~, >=, wildcards, or ranges)", file=sys.stderr)
        sys.exit(2)

    if deprecations:
        if force:
            print("deprecated packages (blocked by PACKAGE_GUARD_FORCE):", file=sys.stderr)
            for d in deprecations:
                print(f"  - {d}", file=sys.stderr)
            sys.exit(2)
        lines = ["deprecated packages detected:"]
        for d in deprecations:
            lines.append(f"  - {d}")
        lines.append("")
        lines.append("set PACKAGE_GUARD_FORCE=1 to block on these; otherwise advisory only.")
        output = {
            'hookSpecificOutput': {
                'hookEventName': 'PostToolUse',
                'additionalContext': '\n'.join(lines),
            }
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == '__main__':
    main()
