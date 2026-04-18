# package-guard

[![CI](https://github.com/wrxck/package-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/wrxck/package-guard/actions/workflows/ci.yml)

Package management enforcement for Claude Code sessions.

## What it checks

- **Version validation**: blocks `^` and `~` prefixes in package.json -- enforces exact versions only. Also catches range operators, wildcards, and hyphen ranges.
- **Health check**: when reading package.json, runs `npm outdated` and `npm audit` to surface outdated packages and security vulnerabilities.

## Installation

```
claude plugin marketplace add wrxck/claude-plugins
claude plugin install package-guard@wrxck-claude-plugins
```
