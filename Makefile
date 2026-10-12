.PHONY: install test run mcp

install:
	pip install -e . -r requirements.txt

test:
	python -m unittest discover -s tests -v

run:
	uvicorn bundesbrief.api:app --reload --app-dir src

mcp:
	python -m bundesbrief
