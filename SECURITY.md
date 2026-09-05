# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest `master` | ✅ |
| older tags / branches | ❌ |

## Reporting a Vulnerability

Do **not** open a public issue for security reports.

Use GitHub's private vulnerability reporting:
**Security → Report a vulnerability** at
https://github.com/amd2g2zz/kunglao-agent/security/advisories/new

Include: affected component, reproduction steps, and impact assessment.
You will get an acknowledgement within 7 days.

## Scope

kunglao-agent is an analysis orchestrator that runs on the operator's own
machine and dispatches agents that may execute analysis tooling. Treat the
following as in scope:

- Hook / script code executing unintended commands
- Prompt-injection paths that flip the orchestrator out of its role
- Credential or secret leakage through workspace artifacts or logs

Out of scope: vulnerabilities in the samples being analyzed, or in the
analysis targets themselves.
