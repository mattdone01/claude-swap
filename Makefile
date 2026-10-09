.PHONY: precommit

precommit:
	uv sync --locked
	@test -z "$$(git ls-files --others --exclude-standard tests)" || \
		{ echo "untracked test files would be absent from CI"; \
		  git ls-files --others --exclude-standard tests; exit 1; }
	uv run python -m compileall -q src
	uv run pytest
