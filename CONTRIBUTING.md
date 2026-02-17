# Contributing to ClawBridge

Thanks for your interest in contributing to ClawBridge. This guide covers the process for submitting changes.

## Quick Links

- [Issue Tracker](https://github.com/NickRomanek/clawbridge/issues)
- [Security Policy](SECURITY.md) — report vulnerabilities privately, not via issues
- [Changelog](CHANGELOG.md)

## Development Setup

```bash
git clone https://github.com/NickRomanek/clawbridge.git
cd clawbridge
cp .env.example .env
# Add at least one API key to .env
pip install -r requirements-dev.txt
python clawbridge.py
```

Dashboard opens at **http://127.0.0.1:8765**.

## Architecture

ClawBridge follows a **monolith-first** development model. The primary source of truth is `clawbridge.py` (~6,700 lines). The `clawbridge/` package mirrors the monolith for testing but may lag behind.

When contributing:

- **All feature/bugfix changes go to `clawbridge.py` first.**
- The `clawbridge/` package is synced from the monolith periodically by maintainers.
- Tests in `tests/` run against the package, not the monolith.

## Submitting Changes

1. **Fork** the repository and create a branch from `main`.
2. **Name your branch** descriptively: `fix/websocket-auth`, `feat/new-engine`, `docs/api-examples`.
3. **Make your changes** in `clawbridge.py` (see Architecture above).
4. **Run tests** to make sure nothing breaks:
   ```bash
   pytest
   ```
5. **Open a pull request** against `main` with a clear description of what changed and why.

## Pull Request Guidelines

- Keep PRs focused — one feature or fix per PR.
- Include a summary of the change and link any related issues.
- If your change affects the dashboard UI, include a screenshot or short description of the visual change.
- If your change adds a new API endpoint, document the route, method, and expected request/response.
- Don't modify the `clawbridge/` package directly — maintainers sync it from the monolith.

## Code Style

- Python: follow existing conventions in `clawbridge.py`. No strict linter enforced, but keep it readable.
- JavaScript (inline in dashboard): use the existing patterns — `esc()` for user data, WebSocket message handlers in the established format.
- No `time.sleep()` in async functions — use `asyncio.sleep()`.
- Always call `safety_redact()` before writing to memory or logs.
- Escape user data in dashboard HTML — use the `esc()` JS function.

## Reporting Bugs

Use the [bug report template](https://github.com/NickRomanek/clawbridge/issues/new?template=bug_report.md). Include:

- ClawBridge version and OS
- Steps to reproduce
- Expected vs. actual behavior
- Relevant logs (from `logs/` directory)

## Suggesting Features

Use the [feature request template](https://github.com/NickRomanek/clawbridge/issues/new?template=feature_request.md). Describe the problem you're trying to solve, not just the solution.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE.txt).
