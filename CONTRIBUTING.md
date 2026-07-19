# Contributing

Contributions are welcome through issues and pull requests.

## Development

1. Install [uv](https://docs.astral.sh/uv/).
2. Run `uv sync --group dev`.
3. Make focused changes that preserve the security and profile-isolation boundaries in `SECURITY.md`.
4. Run:

```bash
uv run pytest -q
uv run ruff check __init__.py newton_ops_store.py dashboard/plugin_api.py tests
uv run bandit -q -r __init__.py newton_ops_store.py dashboard/plugin_api.py
node --check dashboard/dist/index.js
```

Do not include real Hermes state databases, logs, transcripts, prompts, credentials, dashboard screenshots containing private data, or profile directories in issues or pull requests.

## Reporting security problems

Do not open a public issue containing sensitive data. Use GitHub's private vulnerability reporting feature for this repository.
