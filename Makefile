.PHONY: install test run mcp crosscheck crosscheck-real

install:
	pip install -e . -r requirements.txt

test:
	python -m unittest discover -s tests -v

run:
	uvicorn bundesbrief.api:app --reload --app-dir src

mcp:
	python -m bundesbrief

# Apertus cross-check, stub backend (deterministic, offline): harness validation only.
# Prints the stub banner - these numbers are NOT submission numbers.
crosscheck:
	python scripts/run_apertus_crosscheck.py --allow-stub --zh 0

# The documented OPT-IN real run: locally served quantised Apertus via Ollama
# (pull first; setup in src/bundesbrief/apertus_crosscheck.py docstring).
# Slow on CPU-only hardware by design - small sample, recorded artifact.
crosscheck-real:
	BUNDESBRIEF_REAL_BACKENDS=1 python scripts/run_apertus_crosscheck.py
