# Agent instructions

## Project overview

AWS Region Watch is a static Astro site backed by a Python metadata tracker.
The tracker collects AWS partition, region, endpoint, and service metadata.

## Repository map

- `site/`: Astro application and static build configuration.
- `site/src/pages/index.astro`: dashboard page and data presentation.
- `site/src/scripts/app.js`: client-side search and filters.
- `site/src/styles/global.css`: site styles.
- `tracker/tracker.py`: metadata collection, normalization, change detection, and CLI.
- `tracker/tests/test_tracker.py`: tracker unit tests.
- `data/current.json`: generated snapshot consumed by the site.
- `data/changes/latest.json`: generated result from the latest update.
- `data/history/`: generated snapshots created when an update changes metadata.
- `.github/workflows/`: Python checks, site deployment, and scheduled metadata updates.
- `Makefile`: shared development commands.

## Setup and commands

Use Node.js 22.12 or newer, Python 3.13 or newer, `npm`, and `uv`.

```sh
make install
make dev
make build
make preview
make test
make format-check
make lint
make typecheck
make check
make update
```

Run `make install` before the first build or test run. Use `make dev` for local site development. Use `make build` to build the static site. Use `make preview` to serve the built site.

Use `make update` to fetch public AWS metadata and write the generated data files. The update needs network access. Use `uv --directory tracker run python tracker.py update --allow-partial` only when a source outage justifies writing partial data.

## Verification

Run the narrowest relevant command during development. Run `make test` for tracker changes and `make build` for site changes. Always run `make check` before delivery.
