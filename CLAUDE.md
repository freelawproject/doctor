# Doctor

A Django microservice that converts and extracts documents for
CourtListener. See README.md for the endpoints and DEVELOPING.md for how to
run it.

## Conventions

- Imports always go at the top of the file, never after other statements.
  Don't use `# noqa: E402` to get around that; restructure instead.
- Use `http.HTTPStatus` for status codes, never bare integers.
- Comment only what the code can't say: a non-obvious decision or a risk.

## Checks

- `uv run pyrefly check` must report no new errors.
- `pre-commit run --all-files` runs ruff (lint and format).
- The test suite runs against the compose stack:
  `docker compose up --build -d && docker compose exec doctor python -m unittest`.
