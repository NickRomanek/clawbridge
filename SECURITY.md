# Security Policy

## Threat Model

ClawBridge is a desktop automation agent that controls mouse, keyboard, and browser on the user's actual machine. A security flaw in ClawBridge can mean **full machine compromise** — this is fundamentally different from a typical web application.

### What ClawBridge can access
- Desktop UI (mouse, keyboard, screenshots)
- Browser sessions (including logged-in sites)
- Local files (via browser or desktop automation)
- Network (via browser navigation)

### Known architectural risks
- **Prompt injection**: Malicious content on websites or in documents could influence agent behavior
- **Memory poisoning**: Task results flow into agent memory, which influences future tasks
- **Privilege inheritance**: The agent runs with the same privileges as the user

### Built-in safety layers
- Action whitelist (computer-use engine has no shell/bash tool)
- Supervised mode with human approval for high-risk actions
- Safety scanning for credentials, PII, and injection patterns
- Policy modes (permissive, guarded, strict)
- Audit logging of all task events
- Dashboard authentication (token-based)

## Reporting a Vulnerability

If you discover a security vulnerability in ClawBridge, please report it responsibly:

1. **Do NOT open a public GitHub issue** for security vulnerabilities
2. Use [GitHub Private Vulnerability Reporting](https://github.com/NickRomanek/clawbridge/security/advisories/new) — go to the **Security** tab in the repo and click **Report a vulnerability**
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We aim to acknowledge reports within 48 hours and provide a fix or mitigation plan within 7 days.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| < 0.2   | No        |

## Security Best Practices for Users

1. **Set a dashboard token**: Add `DASHBOARD_TOKEN=<random-string>` to your `.env` file
2. **Use supervised mode** for sensitive tasks: Set `SUPERVISED_MODE=true` in `.env`
3. **Use strict policy mode** when handling sensitive data: Set `POLICY_MODE=strict`
4. **Don't paste API keys into task prompts** — configure them in `.env` instead
5. **Review agent actions** — check the audit log in the dashboard regularly
6. **Keep dependencies updated**: Run `npm install -g openclaw@latest` periodically
