#!/usr/bin/env python3
"""
Claude Code PostToolUse hook on Read of package.json.
Caches npm outdated / npm audit results per-project to avoid running on every read.
Fails open (exit 0) even on errors - this is advisory.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


CACHE_TTL_SECONDS = 30 * 60
SUBPROCESS_TIMEOUT = 10


def is_package_json(file_path: str) -> bool:
    return Path(file_path).name == 'package.json'


def get_project_dir(file_path: str) -> str:
    return str(Path(file_path).parent)


def cache_dir() -> Path:
    base = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    d = Path(base) / 'claude-package-guard'
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def project_hash(project_dir: str) -> str:
    h = hashlib.sha256(project_dir.encode('utf-8')).hexdigest()[:16]
    return h


def load_cache(cache_path: Path, mtime: float) -> dict | None:
    try:
        if not cache_path.is_file():
            return None
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if data.get('mtime') != mtime:
            return None
        if time.time() - data.get('created', 0) > CACHE_TTL_SECONDS:
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def save_cache(cache_path: Path, payload: dict) -> None:
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
    except OSError:
        pass


def check_outdated(project_dir: str) -> list[str]:
    issues = []
    try:
        result = subprocess.run(
            ['npm', 'outdated', '--json'],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        if result.stdout:
            outdated = json.loads(result.stdout)
            if isinstance(outdated, dict):
                for package, info in outdated.items():
                    if not isinstance(info, dict):
                        continue
                    current = info.get('current', 'unknown')
                    latest = info.get('latest', 'unknown')
                    if current != latest:
                        issues.append(f"  - {package}: {current} -> {latest} available")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError) as e:
        print(f"package_health_check: npm outdated skipped: {type(e).__name__}", file=sys.stderr)
    return issues


def check_audit(project_dir: str) -> list[str]:
    issues = []
    try:
        result = subprocess.run(
            ['npm', 'audit', '--json'],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        if result.stdout:
            audit = json.loads(result.stdout)
            vulnerabilities = audit.get('vulnerabilities', {}) if isinstance(audit, dict) else {}
            for package, info in vulnerabilities.items():
                if not isinstance(info, dict):
                    continue
                severity = info.get('severity', 'unknown')
                via = info.get('via', [])
                if isinstance(via, list) and via:
                    first = via[0]
                    title = first.get('title', 'vulnerability') if isinstance(first, dict) else str(first)
                else:
                    title = 'vulnerability'
                issues.append(f"  - {package} [{severity}]: {title}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError) as e:
        print(f"package_health_check: npm audit skipped: {type(e).__name__}", file=sys.stderr)
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

    project_dir = get_project_dir(file_path)
    node_modules = Path(project_dir) / 'node_modules'
    if not node_modules.exists():
        sys.exit(0)

    pkg_path = Path(file_path)
    try:
        mtime = pkg_path.stat().st_mtime
    except OSError:
        sys.exit(0)

    cache_path = cache_dir() / f"{project_hash(project_dir)}.json"
    cached = load_cache(cache_path, mtime)

    if cached:
        outdated = cached.get('outdated', [])
        vulnerabilities = cached.get('vulnerabilities', [])
    else:
        outdated = check_outdated(project_dir)
        vulnerabilities = check_audit(project_dir)
        save_cache(cache_path, {
            'mtime': mtime,
            'created': time.time(),
            'outdated': outdated,
            'vulnerabilities': vulnerabilities,
        })

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
