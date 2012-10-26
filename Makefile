build:
	virtualenv --no-site-packages .
	bin/python setup.py develop
	bin/pip install -r requirements_dev.txt 

test:
	./bin/py.test tests/

coverage:
	./bin/py.test --cov gunicorn tests/

clean:
	@rm -rf .Python bin lib include man build html
