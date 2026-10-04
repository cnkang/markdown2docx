# Makefile for markdown2docx development tasks

.PHONY: help install install-dev test test-cov lint format type-check quality clean docs build

# Default target
help:
	@echo "Available targets:"
	@echo "  install      - Install package dependencies"
	@echo "  install-dev  - Install package with development dependencies"
	@echo "  test         - Run tests"
	@echo "  test-cov     - Run tests with coverage report"
	@echo "  lint         - Run linting (Ruff)"
	@echo "  format       - Format code (Ruff)"
	@echo "  type-check   - Run type checking (mypy)"
	@echo "  quality      - Run all quality checks (lint + format + type-check)"
	@echo "  clean        - Clean build artifacts and cache files"
	@echo "  docs         - Build documentation"
	@echo "  build        - Build package for distribution"
	@echo "  pre-commit   - Install and run pre-commit hooks"

# Installation targets
install:
	uv sync --locked

install-dev:
	uv sync --locked --group dev --group docs --group test

# Testing targets
test:
	uv run --locked pytest

test-cov:
	uv run --locked pytest --cov=src --cov-report=term-missing --cov-report=html

test-integration:
	uv run --locked pytest -m integration

test-cli:
	uv run --locked pytest -m cli

# Code quality targets
lint:
	uv run --locked ruff check src tests scripts skills/markdown-to-docx/scripts
	uv run --locked bandit -q -r src scripts skills/markdown-to-docx/scripts

format:
	uv run --locked ruff format src tests scripts skills/markdown-to-docx/scripts

format-check:
	uv run --locked ruff format --check src tests scripts skills/markdown-to-docx/scripts

type-check:
	uv run --locked mypy src/markdown2docx

quality: format-check lint type-check
	@echo "✅ All quality checks passed"

# Pre-commit hooks
pre-commit-install:
	uv run pre-commit install

pre-commit:
	uv run pre-commit run --all-files

# Documentation
docs:
	@echo "Documentation build not yet implemented"
	# uv run sphinx-build -b html docs/ docs/_build/html

# Build and distribution
build:
	uv build

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Development workflow
dev-setup: install-dev pre-commit-install
	@echo "✅ Development environment setup complete"

check: quality test
	@echo "✅ All checks passed - ready to commit"

# Example usage targets
example-basic:
	@echo "Running basic conversion example..."
	uv run markdown2docx README.md -o example_output.docx

example-template:
	@echo "Creating template and converting with it..."
	uv run markdown2docx --create-template example_template.docx
	uv run markdown2docx README.md --template example_template.docx -o example_with_template.docx

# CI/CD simulation
ci: install-dev quality test
	@echo "✅ CI pipeline simulation completed successfully"
