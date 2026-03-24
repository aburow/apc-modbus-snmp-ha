.PHONY: lint

lint:
	UV_CACHE_DIR=$(PWD)/.tools/uv-cache UV_PROJECT_ENVIRONMENT=$(PWD)/.tools/uv-lint .tools/bin/uv sync --group lint
	PATH="$(PWD)/.tools/uv-lint/bin:$$PATH" pre-commit run --hook-stage manual --all-files
