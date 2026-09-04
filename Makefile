.PHONY: install dev build preview test format format-check lint typecheck check update clean

UV_RUN := uv --directory tracker run

install:
	npm ci --prefix site
	uv sync --directory tracker --dev

dev:
	npm run dev --prefix site

build:
	npm run build --prefix site

preview:
	npm run preview --prefix site

test:
	$(UV_RUN) python -m unittest discover -s tests

format:
	$(UV_RUN) ruff format .

format-check:
	$(UV_RUN) ruff format --check .

lint:
	$(UV_RUN) ruff check .

typecheck:
	$(UV_RUN) ty check .

check: format-check lint typecheck test

update:
	$(UV_RUN) python tracker.py update

clean:
	rm -rf site/dist

