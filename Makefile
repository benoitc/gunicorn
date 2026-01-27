build:
	virtualenv venv
	venv/bin/pip install -e .
	venv/bin/pip install -r requirements_dev.txt

docs:
	mkdocs build

docs-serve:
	mkdocs serve

clean:
	@rm -rf .Python MANIFEST build dist venv* *.egg-info *.egg
	@find . -type f -name "*.py[co]" -delete
	@find . -type d -name "__pycache__" -delete

.PHONY: build clean docs docs-serve
