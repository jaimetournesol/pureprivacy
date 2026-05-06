# Contributing to PurePrivacy

Thanks for taking the time to contribute. PurePrivacy is small, so the bar
for getting something merged is low — but the bar for not breaking the
appliance promise (one-command install, easy to use, survives reboots) is high.

## Before you open a PR

- **Run the full test suite**: `./scripts/test-all.sh`.  This runs:
  - **Layer 1** — Python unit tests for the wizard package (recovery
    hashing, pairing, secrets state, render-config logic).  Requires
    Python 3.10+.
  - **Layer 2** — `test-e2e.sh`: stack up → wizard → MCP round-trip.
  - **Layer 3** — `test-features.sh`: token rotation grace, info /
    info --secrets, user CRUD, pair create/accept (with Synapse restart
    verified), recovery key flow, sentinel adaptation.
  - **Layer 4** — `test-restart.sh`: stop/start, restart, down/up,
    MCP bot session persistence.
  Run it before pushing.  CI runs the same thing.
- **Skip the docker-y layers** with `PUREPRIVACY_NO_DOCKER=1` if you're
  iterating on Python-only changes.  Use `PUREPRIVACY_RESET=1` to wipe
  and rebuild from scratch (destroys your local box's state).
- **Don't break first-boot.** The end-user demo is
  `git clone && pureprivacy init`.  If your change adds steps, fold them
  into the init flow, not the README.
- **Don't expand v0.1 scope.** OAuth/MAS, bridges, group push — open an
  issue first.
- **Match the existing AGPL header on new source files.**

## How to contribute

1. Fork and clone.
2. Create a topic branch: `git checkout -b your-thing`.
3. Make your change. Keep diffs focused.
4. Run `./scripts/test-all.sh` and capture the output.
5. Open a PR against `main`. Reference any related issue.

> **First-clone gotcha.**  Some review tools (e.g. Claude Code's
> `/security-review`, certain CI scripts) run `git diff origin/HEAD...`
> which bails out with `ambiguous argument 'origin/HEAD...'` if your
> clone didn't pick up the remote's default branch.  `./scripts/test-all.sh`
> auto-fixes this by running `git remote set-head origin --auto` once;
> if you'd rather do it explicitly, that's the one-liner.

## Code style

- Python: `ruff format` and `ruff check`. We're not picky beyond that.
- Shell: `shellcheck`-clean.
- Dockerfiles: `hadolint`-clean.
- YAML: 2-space indent.

## License

By contributing, you agree your contributions are licensed under
[AGPL-3.0](LICENSE), the project license.
