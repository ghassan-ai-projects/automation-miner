# Contributing

Contributions to code, tests, user documentation, and integrations are welcome.

## Development setup

Prerequisites:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/ghassan-ai-projects/automation-miner.git
cd automation-miner
make sync
make ci-check
```

The test suite is offline by default and uses the deterministic mock model. A provider
API key is not required.

## Contribution rules

- Keep changes scoped and maintainable.
- Add or update tests for behavior changes.
- Preserve structured outputs and deterministic validation boundaries.
- Do not silently discard inputs, opportunities, or errors.
- Update the README when a public command, configuration option, or artifact changes.
- Never commit API keys, customer data, mining workspaces, or private design notes.

## Pull requests

Include:

- the problem being solved
- the chosen approach and important tradeoffs
- compatibility or artifact-schema impact
- tests run
- documentation changes, when applicable

Run the full local quality gate before opening a pull request:

```bash
make ci-check
```

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
