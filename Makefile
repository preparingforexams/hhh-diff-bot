.PHONY: check
check: lint test

.PHONY: lint
lint:
	poetry run black src/
	poetry run ruff check --fix --show-fixes src/
	poetry run mypy src/

.PHONY: test
test:
	poetry run pytest src/
