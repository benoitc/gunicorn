build:
	virtualenv venv
	venv/bin/pip install -e .[dev,testing]

test:
	venv/bin/python -m pytest

coverage:
	venv/bin/python -m converage run --source=gunicorn -m pytest
	venv/bin/python -m converage xml

clean:
	# unlike rm -rf, git-clean -X will only delete files ignored by git
	@git clean -X -f -- .Python MANIFEST build dist "venv*" "*.egg-info" "*.egg" __pycache__

.PHONY: build clean coverage test
