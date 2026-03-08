## Full Release Deployment

Run the complete ClawBridge release process. This is the ONLY way to deploy — follow every step.

### Pre-flight checks

1. Confirm `/e2e` and `/security` have been run this session (or run them now).
2. Run smoke tests against the running server: `python tests/smoke_test.py`
3. If any tests or security checks fail, STOP and fix before deploying.

### Version bump

Bump version in ALL 6 locations (skip if already bumped):
- `clawbridge.py` line ~14 (`__version__`)
- `build.py` line ~32 (`VERSION`)
- `build_macos.py` line ~36 (`VERSION`)
- `installer.iss` line ~10 (`#define MyAppVersion`)
- `website/frontend/src/pages/download.astro` (version string)
- `website/frontend/src/pages/index.astro` (`softwareVersion` in JSON-LD)

Verify all 6 match by grepping for the version string across all files.

### CHANGELOG

Update `CHANGELOG.md` with a new section for the version. Categorize changes as Added/Changed/Fixed.

### Commit, tag, push

```bash
git add <changed files>
# Use -f for website/ files (gitignored)
git commit -m "vX.Y.Z: description"
git tag vX.Y.Z
git push && git push --tags
```

### Wait for CI

Check build status: `gh run list --limit 3`
Wait for the Build & Release workflow to complete: `gh run watch <run_id>`
If build fails, check logs: `gh run view <run_id> --log-failed`

### Deploy website (MANDATORY if download.astro or index.astro changed)

```bash
cd website/frontend && npx astro build && npx wrangler pages deploy dist --project-name clawbridge-site
```

If backend changed: `cd website/backend && npx wrangler deploy`

NOTE: `npm run build` runs `astro check && astro build` — the type checker has pre-existing errors in download.astro. Use `npx astro build` directly to skip type checking.

### Post-deploy verification

1. Check GitHub releases page has all artifacts
2. Verify clawbridge.ai/download shows correct version
3. Verify `curl -s http://127.0.0.1:8765/health` returns the new version

### Past failures to watch for

- **v0.5.4**: Website deploy was SKIPPED even though download.astro changed. Always deploy website when version files change.
- **v0.5.5**: `npm run build` fails due to pre-existing TS errors in download.astro. Use `npx astro build` directly.
- **Python `\n` in JS**: When adding JS regexes in Python strings, use `\\n` not `\n`. The `\n` becomes a literal newline that breaks the `<script>` block.
- **Installer filename**: Must always be `ClawBridge-Setup.exe` — no version suffix.
- **v0.5.5**: `--host 127.0.0.1` is NOT a valid OpenClaw flag. Use `--bind loopback` instead. The wrong flag silently kills the gateway, causing 30s timeouts on every chat task.
- **OpenClaw gateway flags**: Full command is `openclaw gateway --port 18789 --bind loopback --allow-unconfigured --auth none --dev`. Always test gateway startup after changes.
