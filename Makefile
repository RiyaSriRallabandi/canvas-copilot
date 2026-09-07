.PHONY: check check-local eval fmt

# What CI runs — no Ollama, no Canvas token needed.
check:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/
	uv run pyright
	uv run pytest -q

fmt:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

# Everything, including the live tests (needs Ollama running + a stored token).
check-local: check
	uv run pytest -q --run-live

# The model bake-off / scenario eval (needs Ollama + the model pulled).
eval:
	uv run python -m canvas_copilot.evals.bakeoff --model qwen2.5:3b
