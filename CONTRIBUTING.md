# Contributing

## Branching
- Use `main` as the release branch.
- Open PRs from short-lived feature branches.

## Versioning
- Version is stored in `VERSION` with format `YYYY.MM.x`.
- Any user-visible change must be reflected in `CHANGELOG.md`.

## Local checks
- `docker compose -f compose.yml config`
- `docker compose -f compose.yml up -d --build`
- Health check: `curl -fsS http://127.0.0.1:3334/health`

## Security and secrets
- Never commit real secrets.
- Keep only templates in `.env.example`.
- Use local `.env` for runtime values.
