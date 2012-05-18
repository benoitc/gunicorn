build:
	virtualenv --no-site-packages .
	bin/python setup.py develop
	bin/pip install coverage
	bin/pip install nose

py3:
	virtualenv --no-site-packages -p python3 .
	bin/python setup.py develop
	bin/pip install coverage
	bin/pip install nose

py26:
	virtualenv --no-site-packages -p python2.6 .
	bin/python setup.py develop
	bin/pip install coverage
	bin/pip install nose

test:
	bin/nosetests

coverage:
	bin/nosetests --with-coverage --cover-html --cover-html-dir=html \
		--cover-package=gunicorn

clean:
	@rm -rf .Python bin lib include man build html
