build:
	virtualenv --no-site-packages .
	bin/python setup.py develop
	bin/pip install -r requirements_dev.txt

test:
	bin/python setup.py test

coverage:
	bin/python setup.py test --cov

clean:
	@rm -rf .Python bin lib include man build html
